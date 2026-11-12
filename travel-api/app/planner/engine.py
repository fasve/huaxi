"""Stage3 日程分配：贪心装箱 + 约束校验 + 分级松弛（方案 5.4）。

对外三个入口：
  generate_trip —— 全量生成（#3 接口）
  replan_day   —— 单日重排，其余日锁定（#4 redrop）
  replace_slot —— 槽位手动替换（#4 replace）
"""
from __future__ import annotations

import math
import random

from app.planner.models import DayPlan, PlannerPoi, SlotItem, TripPlan, TripRequest
from app.planner.scoring import estimate_travel_min, score_hotel, static_scores
from app.planner.relax import log_relax
from app.planner.ordering import order_day_items

PLAY_SLOTS = ("morning", "afternoon", "evening")


def _order_windows(rules: dict, mode: str) -> dict:
    """槽位时间窗（与 _pack_one_day 口径一致）。"""
    return dict(
        lunch_start=rules["lunch_window"][0],
        dinner_start=rules.get("dinner_start", "18:30" if mode == "premium" else "18:00"),
        evening_start="19:00",
    )


# ---------- 时间工具 ----------

def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


# ---------- 内部工具 ----------

def _mid(p: PlannerPoi) -> tuple[float, float]:
    return p.longitude, p.latitude


def _cluster_center(pois: list[PlannerPoi]) -> tuple[float, float]:
    if not pois:
        return 106.675, 26.408  # 花溪城区中心兜底
    return (
        sum(x.longitude for x in pois) / len(pois),
        sum(x.latitude for x in pois) / len(pois),
    )


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    """小范围近似距离（就近粗排用）。"""
    return math.hypot((a[0] - b[0]) * 92, (a[1] - b[1]) * 111)


def _static_total(p: PlannerPoi, weights: dict[str, float]) -> float:
    """静态加权和（不含动态项）。"""
    return sum(w * p.static.get(k, 0.0) for k, w in weights.items() if k != "budget_fit")  # type: ignore[attr-defined]


SNACK_SUBTYPES = ("街头小吃", "甜品伴手礼")  # 正餐位排除（blitz 可用）


def _pick_meal(
    food_pool: list[PlannerPoi],
    used: set[int],
    meal: str,                       # "午" / "晚" / "夜"
    anchor: tuple[float, float],
    day_remaining: float,
    rules: dict,
    weights: dict[str, float],
    mode: str,
    boost_fn=None,
    top_k: int = 8,
    min_duration: int | None = None,
) -> PlannerPoi | None:
    """用餐锚点：先按分数取 TopK，再就近匹配（方案 5.4 第 3 条）。

    正餐位排除街头小吃/甜品摊（blitz 不受限，符合"快餐/粉面位"口径）。
    min_duration：正餐规格下限（如晚餐 ≥45min）。
    """
    cap = day_remaining * rules["budget_elasticity_max"]
    dur_ok = (lambda p: True) if min_duration is None else \
        (lambda p: p.suggest_duration_min >= min_duration)  # noqa: E731
    cands = [
        p for p in food_pool
        if p.id not in used and meal in (p.meal_period or "") and p.cost <= cap
        and (mode == "blitz" or p.sub_type not in SNACK_SUBTYPES) and dur_ok(p)
    ]
    if not cands:  # 放宽：任意时段可用的正餐
        cands = [p for p in food_pool
                 if p.id not in used and p.cost <= max(cap, day_remaining)
                 and (mode == "blitz" or p.sub_type not in SNACK_SUBTYPES) and dur_ok(p)]
    if not cands:  # 再放宽（接近弹尽粮绝时）
        cands = [p for p in food_pool if p.id not in used
                 and p.cost <= max(cap, day_remaining)]
    if not cands:
        return None
    cands.sort(key=lambda p: -_static_total(p, weights))
    short = cands[:top_k]
    if boost_fn:
        short.sort(key=lambda p: (0 if boost_fn(p) else 1, _dist(_mid(p), anchor)))
    else:
        short.sort(key=lambda p: _dist(_mid(p), anchor))
    return short[0]


def _pick_play(
    pools: list[PlannerPoi],
    used: set[int],
    prev: PlannerPoi | None,
    day_selected_subtypes: set[str],
    day_remaining: float,
    minutes_left: int,
    rules: dict,
    weights: dict[str, float],
    rng: random.Random | None,
    ignore_overlap: bool = False,
    light_only: bool = False,
    slot: str = "morning",
    cur_abs: int | None = None,
    deadline: int | None = None,
) -> PlannerPoi | None:
    """贪心取当前最高分且满足时间/费用约束的游玩 POI（含 4.4 全部动态项）。

    cur_abs：当前时刻（自 00:00 起的分钟数），用于 deadline 判定。
    deadline：绝对截止时刻；越过即放弃该 POI（保证下午不挤占晚餐窗口）。
    """
    from app.planner.scoring import score_poi

    best, best_score = None, -1e9
    mu = rules["mu_travel_cost"]
    speed = rules["speed_kmh"]
    thr = rules.get("budget_fit_threshold", 0.3)
    for p in pools:
        if p.id in used:
            continue
        # 仅夜间营业的场所（夜市等）只能进晚间槽
        if p.night_only and slot != "evening":
            continue
        if light_only and (p.suggest_duration_min > 30 or p.cost > 0):
            continue
        travel = estimate_travel_min(prev, p, speed)
        if travel + p.suggest_duration_min > minutes_left:
            continue
        # 绝对截止线：下午景点须在晚餐窗口前收尾，晚餐/晚间同理
        if deadline is not None and cur_abs is not None:
            if cur_abs + travel + p.suggest_duration_min > deadline:
                continue
        if p.cost > day_remaining * rules["budget_elasticity_max"]:
            continue
        jitter = rng.uniform(0.0, 0.05) if rng else 0.0
        sc = score_poi(
            p, weights, mu, speed, day_remaining, prev,
            set() if ignore_overlap else day_selected_subtypes,
            thr, jitter,
        )
        if sc > best_score:
            best, best_score = p, sc
    return best


# ---------- 主流程 ----------

def generate_trip(
    candidates: list[PlannerPoi],
    req: TripRequest,
    weights: dict[str, float],
    rules: dict,
    preset_stops: list | None = None,
) -> TripPlan:
    """四阶段流水线主体（Stage1 由服务层完成）。

    preset_stops：预设主题路线经 date_gate 判定后的保底站点（方案 5.8）。
    命中时把它们按 seq 预占第 1 天的上午/下午槽，剩余槽位仍走正常贪心装箱，
    从而得到「半天游学 + 半天按 mode 自由生成」的混合行程；不另写一套引擎。
    """
    rng = random.Random(req.seed or 0)
    static_scores(candidates)

    play_pool = [p for p in candidates if p.category in ("scenic", "leisure")]
    food_pool = [p for p in candidates if p.category == "food"]
    hotel_pool = [p for p in candidates if p.category == "hotel"]

    plan = TripPlan(mode=req.mode, days=req.days, budget=req.budget)
    relax_log = plan.relax_log

    # ---- 1. 住宿锁定（5.4 第 1 条）
    plan.hotel_nights = max(0, req.days - 1)
    if plan.hotel_nights > 0 and hotel_pool:
        nightly_cap = req.budget * 0.45 / plan.hotel_nights  # 住宿占比上限 45%
        ok = [
            p for p in hotel_pool
            if rules["hotel_price_level_min"] <= p.price_level <= rules["hotel_price_level_max"]
            and p.cost <= nightly_cap
        ]
        if not ok:  # 松弛：档次下限内不限预算
            ok = [p for p in hotel_pool if p.price_level >= rules["hotel_price_level_min"]]
        if ok:
            plan.hotel = max(ok, key=score_hotel)
            if plan.hotel.cost > nightly_cap:
                log_relax(relax_log, 0, 2,
                          f"住宿「{plan.hotel.name}」间夜价超出建议占比，已压缩游玩预算")
        else:
            log_relax(relax_log, 0, 5, "无满足档次要求的酒店，本程不含住宿安排")
    if plan.hotel:
        plan.hotel_total_cost = round(plan.hotel.cost * plan.hotel_nights, 1)

    activity_budget = req.budget - plan.hotel_total_cost
    day_budget = activity_budget / req.days

    # ---- 2. 打卡游地标保底注入（4.3）
    preoccupied: dict[int, list[PlannerPoi]] = {d: [] for d in range(1, req.days + 1)}
    topn = rules.get("landmark_must_cover_topn", 0)
    if topn:
        landmarks = sorted(
            [p for p in play_pool if p.is_landmark],
            key=lambda p: (-p.hot_score, -p.rating),
        )[:topn]
        for i, lm in enumerate(landmarks):
            preoccupied[i % req.days + 1].append(lm)

    used: set[int] = set()
    if plan.hotel:
        used.add(plan.hotel.id)

    # ---- 3. 逐日贪心装箱
    for d in range(1, req.days + 1):
        day = _pack_one_day(
            d, preoccupied[d], play_pool, food_pool, plan.hotel,
            day_budget, rules, weights, rng, used, req, relax_log,
            preset_stops=preset_stops if d == 1 else None,
        )
        plan.days_plan.append(day)

    # ---- 4. 全局预算终检（5.4 第 5 条）
    _global_budget_check(plan, rules, weights, relax_log)

    # ---- 5. Stage4 排序 + 时间轴
    for day in plan.days_plan:
        order_day_items(
            day, plan.hotel, rules["speed_kmh"],
            rules["day_start"], rules["day_end"],
            **_order_windows(rules, plan.mode),
        )

    # ---- 6. 汇总
    plan.total_cost = round(
        plan.hotel_total_cost + sum(dd.day_cost for dd in plan.days_plan), 1
    )
    plan.budget_usage = round(plan.total_cost / req.budget, 3) if req.budget else 0
    scores = [
        _static_total(it.poi, weights)
        for dd in plan.days_plan for it in dd.items
        if it.poi and it.slot in PLAY_SLOTS
    ]
    plan.score = round(sum(scores) / len(scores), 3) if scores else 0
    _build_explanation(plan, rules)
    return plan


def _pack_one_day(
    day_index: int,
    preocc: list[PlannerPoi],
    play_pool: list[PlannerPoi],
    food_pool: list[PlannerPoi],
    hotel: PlannerPoi | None,
    day_budget: float,
    rules: dict,
    weights: dict[str, float],
    rng: random.Random,
    used: set[int],
    req: TripRequest,
    relax_log: list[dict],
    preset_stops: list | None = None,
) -> DayPlan:
    """单日槽位装箱：morning→lunch→afternoon→dinner→evening。

    preset_stops 仅作用于第 1 天（方案 5.8 拼接能力）：站点按 seq 预占槽位，
    步行衔接用站内预置值而非 Haversine，剩余槽位继续由贪心补全。
    """
    day = DayPlan(day_index=day_index, day_budget=round(day_budget, 1))
    day_remaining = day_budget
    subtypes: set[str] = set()
    prev = hotel
    play_count = 0
    play_minutes = 0
    max_count = rules["daily_poi_max"]
    max_minutes = rules["daily_play_hours_max"] * 60
    # 保底站点不占模式的 POI 名额：游学线 5 站 + 模式原有的自由点额度
    if preset_stops:
        max_count += len(preset_stops)

    # 绝对时钟（自 00:00 起的分钟数）：与 ordering 的时间轴口径一致，
    # 用于判断"某槽位是否来得及在下一个槽位窗口前收尾"。
    t_start = _hm(rules["day_start"])
    t_lunch = _hm(rules["lunch_window"][0])
    lunch_dur = 30 if req.mode == "blitz" else 60
    t_dinner = _hm(rules.get("dinner_start", "18:30" if req.mode == "premium" else "18:00"))
    dinner_dur = int(rules.get("dinner_duration_min", 90 if req.mode == "premium" else 60))
    t_end = _hm(rules["day_end"])
    # 上午截止于午餐窗口开启；下午截止于晚餐窗口开启；晚间截止于当日收工
    dl_morning = t_lunch
    dl_afternoon = t_dinner
    dl_evening = t_end
    cur_abs = t_start

    def _add(poi: PlannerPoi | None, slot: str, duration: int | None = None,
             travel: int = 0) -> SlotItem | None:
        """登记一个已排入的槽位条目，并推进绝对时钟。"""
        nonlocal day_remaining, prev, play_count, play_minutes, cur_abs
        if poi is None:
            return None
        dur = duration or poi.suggest_duration_min
        it = SlotItem(slot=slot, poi=poi, duration_min=dur, cost=poi.cost)
        used.add(poi.id)
        day_remaining -= poi.cost
        if slot in PLAY_SLOTS:
            play_count += 1
            play_minutes += dur
            if poi.sub_type:
                subtypes.add(poi.sub_type)
        prev = poi
        cur_abs += travel + dur
        day.items.append(it)
        return it

    def _fill_slot(
        slot: str, minutes: int, ignore_overlap: bool = False,
        deadline: int | None = None,
    ) -> None:
        """循环填满一个游玩槽的时间预算。"""
        nonlocal play_count, play_minutes, prev
        while play_count < max_count and minutes > 60 and play_minutes < max_minutes:
            poi = _pick_play(
                play_pool, used, prev, subtypes, day_remaining,
                minutes, rules, weights, rng,
                ignore_overlap=ignore_overlap, slot=slot,
                cur_abs=cur_abs, deadline=deadline,
            )
            if poi is None:
                break
            travel = estimate_travel_min(prev, poi, rules["speed_kmh"])
            minutes -= travel + poi.suggest_duration_min
            _add(poi, slot, travel=travel)

    # 时间窗（按模式）：morning 可用至 lunch_window 结束（午饭顺延也仍在窗口内）
    # t_start / t_lunch / t_dinner / t_end 已在绝对时钟初始化处定义
    morning_minutes = _hm(rules["lunch_window"][1]) - t_start
    afternoon_minutes = t_dinner - (t_lunch + lunch_dur)
    evening_minutes = t_end - (t_dinner + dinner_dur)

    # ---- 预设主题路线保底站点（方案 5.8 第 1/5 条） ----
    # 站点按 seq 预占上午/下午槽；walk_in_min 为校内实测步行，覆盖 Haversine 估算；
    # locked 项在 Stage4 免于 2-opt 重排，保证游学动线顺序不被通勤优化打乱。
    deferred_preset: list = []

    def _inject_preset(st, bucket: str) -> bool:
        """注入一个游学保底站；返回是否成功入程。"""
        nonlocal morning_minutes, afternoon_minutes
        if st.poi.id in used:
            return False
        travel = max(0, int(st.walk_in_min or 0))
        stay = max(10, int(st.stay_min or 0))
        need = travel + stay
        if bucket == "morning":
            if cur_abs + need > dl_morning or need > morning_minutes:
                return False
            morning_minutes -= need
        else:
            if cur_abs + need > dl_afternoon:
                log_relax(relax_log, day_index, 4,
                          f"游学站点「{st.poi.name}」当日时间所限未入程")
                return False
            afternoon_minutes = max(0, afternoon_minutes - need)
        it = _add(st.poi, bucket, duration=stay, travel=travel)
        if it is None:
            return False
        it.preset_seq = int(st.seq)
        it.locked = True
        it.travel_override_min = travel
        it.estimated = False
        it.preset_meta = dict(
            seq=int(st.seq), is_study_stop=True,
            narration_title=st.narration_title,
            narration_text=st.narration_text,
            task_card=st.task_card or {},
            photo_tip=st.photo_tip or "",
            gate_status=st.gate_status,
            gate_notes=list(st.gate_notes or []),
            walk_in_min=travel, stay_min=stay,
            must_visit=bool(st.must_visit),
        )
        return True

    if preset_stops and day_index == 1:
        for st in sorted([s for s in preset_stops if (s.slot or "morning") == "morning"],
                         key=lambda s: s.seq):
            if not _inject_preset(st, "morning"):
                deferred_preset.append(st)   # 上午放不下 → 顺延到午餐后

    # ---- 保底地标（checkin：Top 地标必入程；须消耗时间预算）
    deferred_preocc: list[PlannerPoi] = []
    for lm in preocc:
        if lm.id in used or play_count >= max_count:
            continue
        travel = estimate_travel_min(prev, lm, rules["speed_kmh"])
        need = travel + lm.suggest_duration_min
        if need <= morning_minutes and cur_abs + need <= dl_morning:
            morning_minutes -= need
            _add(lm, "morning", travel=travel)
        else:
            deferred_preocc.append(lm)  # 上午放不下 → 延迟到午后的下午槽

    # ---- morning
    _fill_slot("morning", morning_minutes, deadline=dl_morning)

    # ---- lunch（blitz 优先粉面快餐；premium 优先正餐黔菜）
    anchor = (
        _cluster_center([it.poi for it in day.items if it.poi])
        if any(it.poi for it in day.items)
        else (_mid(hotel) if hotel else (106.675, 26.408))
    )
    lunch = _pick_meal(
        food_pool, used, "午", anchor, day_remaining, rules, weights, req.mode,
        boost_fn=(lambda p: p.sub_type in ("粉面小吃", "快餐")) if req.mode == "blitz"
        else (lambda p: p.cuisine in ("黔菜", "贵州菜") and p.price_level >= 3) if req.mode == "premium"
        else None,
    )
    if lunch is None and rules.get("require_lunch"):
        log_relax(relax_log, day_index, 3, "候选餐厅不足，午餐未安排")
    lunch_travel = estimate_travel_min(prev, lunch, rules["speed_kmh"]) if lunch else 0
    _add(lunch, "lunch", travel=lunch_travel)

    # ---- 游学线下午站：午餐后按 seq 继续（含上午放不下而顺延的站点）
    if preset_stops and day_index == 1:
        afternoon_stops = [
            s for s in preset_stops if (s.slot or "morning") != "morning"
        ] + deferred_preset
        for st in sorted(afternoon_stops, key=lambda s: s.seq):
            _inject_preset(st, "afternoon")

    # ---- 延迟保底地标入下午
    for lm in deferred_preocc:
        if lm.id in used or play_count >= max_count:
            continue
        travel = estimate_travel_min(prev, lm, rules["speed_kmh"])
        need = travel + lm.suggest_duration_min
        if need <= afternoon_minutes and cur_abs + need <= dl_afternoon:
            afternoon_minutes -= need
            _add(lm, "afternoon", travel=travel)
        else:
            log_relax(relax_log, day_index, 4,
                      f"地标「{lm.name}」当日时间所限未入程")

    # ---- afternoon
    _fill_slot("afternoon", afternoon_minutes, deadline=dl_afternoon)

    # ---- checkin 每日必含 1 次小吃探店（4.3：1 次小吃探店）
    if rules.get("require_snack"):
        snack = _pick_meal(
            food_pool, used, "夜", anchor, day_remaining, rules, weights, req.mode,
            boost_fn=lambda p: p.price_level <= 2 and ("小吃" in p.sub_type or "粉面" in p.sub_type),
            top_k=20,
        )
        if snack is None:
            snack = _pick_meal(food_pool, used, "晚", anchor, day_remaining, rules, weights, req.mode)
        snack_travel = estimate_travel_min(prev, snack, rules["speed_kmh"]) if snack else 0
        _add(snack, "afternoon",
             duration=min(30, snack.suggest_duration_min) if snack else 30,
             travel=snack_travel)

    # ---- dinner（非 blitz 要求正餐规格：时长 ≥ 45min 的坐店餐厅）
    anchor2 = _cluster_center([it.poi for it in day.items if it.poi]) if day.items else anchor
    dinner = _pick_meal(
        food_pool, used, "晚", anchor2, day_remaining, rules, weights, req.mode,
        boost_fn=(lambda p: p.is_time_honored or p.price_level >= 3) if req.mode in ("premium", "checkin")
        else (lambda p: p.sub_type in ("粉面小吃", "快餐")) if req.mode == "blitz"
        else None,
        min_duration=None if req.mode == "blitz" else 45,
    )
    if dinner is None and rules.get("require_dinner"):
        log_relax(relax_log, day_index, 3, "候选餐厅不足，晚餐未安排")
    dinner_travel = estimate_travel_min(prev, dinner, rules["speed_kmh"]) if dinner else 0
    _add(dinner, "dinner", travel=dinner_travel)

    # ---- evening（按 4.3 晚间槽策略；数量上限与其他槽一致）
    # evening_slot 优先取用户"晚间偏好"微调后的规则，缺省才回落到模式口径：
    #   none=可省夜游 / rest=泡汤轻休闲 / dine_night=观景晚宴 / landmark_night=夜市灯光
    evening_type = rules.get("evening_slot") or {
        "premium": "dine_night", "checkin": "landmark_night",
        "leisure": "rest", "blitz": "none",
    }.get(req.mode, "none")
    if evening_minutes > 45 and play_minutes < max_minutes and play_count < max_count:
        if evening_type == "dine_night":
            # 强制：观景餐厅/温泉类夜间休闲
            pool_night = [p for p in play_pool if p.category == "leisure"
                          and (p.night_open or "温泉" in p.play_type or "观景" in p.sub_type)]
            poi = _pick_play(pool_night or play_pool, used, prev, subtypes,
                             day_remaining, evening_minutes, rules, weights, rng, slot="evening",
                             cur_abs=cur_abs, deadline=dl_evening)
            if poi is None:
                log_relax(relax_log, day_index, 3, "晚间缺少温泉/观景类场所，已留白")
            _add(poi, "evening")
        elif evening_type == "landmark_night":
            # 强制：夜市/灯光打卡
            pool_night = [p for p in play_pool if
                          ((p.category == "leisure" or "夜景" in p.sub_type or "夜市" in p.sub_type)
                           and p.night_open) or "夜景" in p.sub_type or "夜市" in p.sub_type]
            poi = _pick_play(pool_night or play_pool, used, prev, subtypes,
                             day_remaining, evening_minutes, rules, weights, rng, slot="evening",
                             cur_abs=cur_abs, deadline=dl_evening)
            if poi is None:
                log_relax(relax_log, day_index, 3, "晚间缺少夜市/灯光类场所，已留白")
            _add(poi, "evening")
        elif evening_type == "rest":
            # 弱：泡汤/室内轻休闲（可不填）
            pool_soft = [p for p in play_pool
                         if p.category == "leisure" and (p.indoor or "温泉" in p.play_type)]
            _add(_pick_play(pool_soft, used, prev, subtypes,
                            day_remaining, evening_minutes, rules, weights, rng, slot="evening",
                            cur_abs=cur_abs, deadline=dl_evening), "evening")
        else:  # evening_slot=none：可省夜游，把时间留给游玩加练
            _fill_slot("evening", evening_minutes, deadline=dl_evening)

    # ---- 回填与松弛（5.4 第 4 条）
    if play_count < rules["daily_poi_min"]:
        # L1 放宽多样性
        while play_count < rules["daily_poi_min"] and play_minutes < max_minutes:
            poi = _pick_play(
                play_pool, used, prev, subtypes, day_remaining,
                afternoon_minutes + evening_minutes, rules, weights, rng,
                ignore_overlap=True, slot="evening",
                cur_abs=cur_abs, deadline=dl_evening,
            )
            if poi is None:
                break
            _add(poi, "evening")
            log_relax(relax_log, day_index, 1)
        # L3 轻量槽（≤30min 免费打卡）
        if play_count < rules["daily_poi_min"]:
            poi = _pick_play(
                play_pool, used, prev, subtypes, day_remaining,
                90, rules, weights, rng,
                ignore_overlap=True, light_only=True, slot="evening",
                cur_abs=cur_abs, deadline=dl_evening,
            )
            if poi is not None:
                _add(poi, "evening")
                log_relax(relax_log, day_index, 3)
        # L5 underfilled
        if play_count < rules["daily_poi_min"]:
            day.underfilled = True
            log_relax(relax_log, day_index, 5,
                      f"当日仅排入 {play_count} 个游玩点，建议调整天数或预算")

    day.day_cost = sum(it.cost for it in day.items)
    scenic_names = [it.poi.name for it in day.items if it.poi and it.slot in ("morning", "afternoon")]
    if preset_stops and day_index == 1:
        day.theme = "预设主题路线 · 游学线（半日） + 自由游"
    else:
        day.theme = (scenic_names[0] + "线") if scenic_names else "花溪自由漫游"
    return day


def _global_budget_check(
    plan: TripPlan,
    rules: dict,
    weights: dict[str, float],
    relax_log: list[dict],
) -> None:
    """超支降级：从最低分 POI 逐个移除直至进入弹性区间（blitz/premium 禁超支）。"""
    cap = plan.budget * rules["budget_elasticity_max"]
    cur = plan.hotel_total_cost + sum(dd.day_cost for dd in plan.days_plan)
    guard = 0
    while cur > cap and guard < 20:
        guard += 1
        worst_day, worst_item, worst_score = None, None, 1e9
        for dd in plan.days_plan:
            for it in dd.items:
                # 游学保底站是专家编排的必选动线，不参与预算降级的移除候选
                if it.poi is None or it.locked or it.slot not in PLAY_SLOTS:
                    continue
                sc = _static_total(it.poi, weights)
                if sc < worst_score:
                    worst_day, worst_item, worst_score = dd, it, sc
        if worst_item is None or worst_item.poi is None:
            break
        log_relax(relax_log, worst_day.day_index if worst_day else 0, 2,
                  f"为守住预算红线，已移除「{worst_item.poi.name}」")
        worst_item.poi = None
        worst_item.duration_min = 0
        worst_item.cost = 0.0
        for dd in plan.days_plan:
            dd.day_cost = sum(it.cost for it in dd.items)
        cur = plan.hotel_total_cost + sum(dd.day_cost for dd in plan.days_plan)
    # 节余提示
    if plan.budget and cur / plan.budget < rules["budget_utilization_min"] - 0.15:
        log_relax(relax_log, 0, 6,
                  f"预算利用率偏低（{cur / plan.budget:.0%}），可考虑升级住宿或餐饮")


def _build_explanation(plan: TripPlan, rules: dict) -> None:
    """模式说明卡文案（供 T3 前端"为何这样排"）。"""
    from app.planner.models import MODE_DESCRIPTIONS, MODE_NAMES
    plan.explanation = [
        f"本行程按「{MODE_NAMES.get(plan.mode)}」模式编排：{MODE_DESCRIPTIONS.get(plan.mode, '')}",
        f"节奏：单日游玩点 {rules['daily_poi_min']}~{rules['daily_poi_max']} 个，"
        f"最长游玩 {rules['daily_play_hours_max']} 小时；通勤策略：{rules['transit_desc']}。",
        f"预算口径：住宿优先锁定，剩余按天均摊；弹性区间 "
        f"{rules['budget_elasticity_min']:.0%}~{rules['budget_elasticity_max']:.0%}。",
    ]


# ---------- 增量重算（#4 接口） ----------

def replan_day(
    day_plan_ctx: dict,
    candidates: list[PlannerPoi],
    rules: dict,
    weights: dict[str, float],
    seed_offset: int = 0,
) -> DayPlan:
    """单日重排：其余日 POI 锁定（排除在候选外），仅重算当日，成本 O(1 日)。

    day_plan_ctx: { day_index, day_budget, locked_ids, today_ids, hotel, req }
    """
    req: TripRequest = day_plan_ctx["req"]
    rng = random.Random((req.seed or 0) + seed_offset)
    static_scores(candidates)
    play_pool = [p for p in candidates if p.category in ("scenic", "leisure")]
    food_pool = [p for p in candidates if p.category == "food"]

    used = set(day_plan_ctx["locked_ids"])
    # 当日 POI 释放回候选池
    used -= set(day_plan_ctx["today_ids"])

    relax_log: list[dict] = []
    day = _pack_one_day(
        day_plan_ctx["day_index"], [], play_pool, food_pool,
        day_plan_ctx.get("hotel"), day_plan_ctx["day_budget"],
        rules, weights, rng, used, req, relax_log,
    )
    order_day_items(day, day_plan_ctx.get("hotel"), rules["speed_kmh"],
                    rules["day_start"], rules["day_end"],
                    **_order_windows(rules, req.mode))
    day.__dict__["relax_log"] = relax_log
    return day


def replace_slot(
    day: DayPlan,
    slot: str,
    new_poi: PlannerPoi | None,
    used_ids: set[int],
    rules: dict,
    hotel: PlannerPoi | None,
    mode: str = "leisure",
) -> DayPlan:
    """手动替换槽位：只重排该日时间轴，其余不动。"""
    for it in day.items:
        if it.slot == slot:
            if it.poi is not None:
                used_ids.discard(it.poi.id)
            it.poi = new_poi
            if new_poi is not None:
                used_ids.add(new_poi.id)
                it.duration_min = new_poi.suggest_duration_min
                it.cost = new_poi.cost
            else:
                it.duration_min = 0
                it.cost = 0.0
            break
    day.day_cost = sum(it.cost for it in day.items)
    order_day_items(day, hotel, rules["speed_kmh"], rules["day_start"], rules["day_end"],
                    **_order_windows(rules, mode))
    return day
