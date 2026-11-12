"""行程服务：生成、落库、重排/替换、候选列表、输出组装。"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Poi, PoiExtFood, PoiExtHotel, PoiExtLeisure, PoiExtScenic,
    Trip, TripDay, TripItem, TripModeConfig, UserTripStat,
)
from app.planner.models import DayPlan, PlannerPoi, SLOT_NAMES, MODE_NAMES, TripRequest
from app.planner.engine import generate_trip, replan_day, replace_slot
from app.planner.weights import (
    apply_pace, is_custom, normalize_weights, slider_defaults, weight_profile,
)
from app.services.poi_service import stage1_candidates
from app.services.image_policy import split_visible_images
from app.services.cache import mode_cache
from app.services import guest_stats_service as stats
from app.services import mode_version_service, price_service
from app.services.preset_route_service import resolve_for_generation
from app.planner.preset_routes import parse_visit_date
from app.planner.relax import log_relax


SLOT_NAME_MAP = dict(SLOT_NAMES)

# 游玩类类别（亲子贴士 / 每日点位数估算按它统计）
PLAY_CATEGORIES = ("scenic", "leisure", "study")

_WEEK_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def date_meta(start_date: str | None, day_index: int) -> tuple[str | None, str | None]:
    """出行首日 + 第几天 → (YYYY-MM-DD, 周X)；非法/缺失返回 (None, None)。"""
    if not start_date:
        return None, None
    try:
        base = datetime.strptime(str(start_date).strip()[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None, None
    d = base + timedelta(days=max(0, int(day_index) - 1))
    return d.isoformat(), _WEEK_CN[d.weekday()]


def _gen_trip_id() -> str:
    return "t_" + secrets.token_hex(3)


def get_mode_cfg(db: Session, mode: str):
    """读取模式配置（进程内缓存纯 dict 快照，避免跨 Session 的 ORM 脱离问题）。"""
    cache_key = f"mode:{mode}"
    snap = mode_cache.get(cache_key)
    if snap is None:
        cfg = db.query(TripModeConfig).filter(TripModeConfig.mode == mode).first()
        if not cfg:
            raise HTTPException(404, f"模式不存在: {mode}")
        snap = SimpleNamespace(
            mode=cfg.mode, mode_name=cfg.mode_name, description=cfg.description,
            weights=dict(cfg.weights), hard_rules=dict(cfg.hard_rules),
        )
        mode_cache.set(cache_key, snap)
    return snap


def _poi_brief(db: Session, poi_id: int) -> dict:
    p = db.get(Poi, poi_id)
    if not p:
        return {}
    price = p.ticket_price
    if p.category == "hotel":
        e = db.get(PoiExtHotel, p.id)
        price = e.price_min if e else p.ticket_price
    elif p.category == "food":
        e = db.get(PoiExtFood, p.id)
        price = e.avg_price if e else p.ticket_price
    # A3：生效价格规则优先（酒店间夜 / 餐饮人均同样支持调价）
    override, _ = price_service.price_override(db, p)
    if override is not None:
        price = override
    return dict(
        poi_id=p.id, name=p.name, category=p.category,
        longitude=p.longitude, latitude=p.latitude,
        ticket_price=price, suggest_duration_min=p.suggest_duration_min,
        sub_type=p.sub_type, rating=p.rating, address=p.address,
        images=split_visible_images(p.images, p.image_meta)[0],
    )


def _day_to_out(db: Session, day: TripDay,
                stop_by_poi: dict[int, dict] | None = None) -> dict:
    items = sorted(day.items, key=lambda x: x.order_index)
    out_items = []
    for it in items:
        brief = _poi_brief(db, it.poi_id) if it.poi_id else {}
        st = (stop_by_poi or {}).get(it.poi_id) if it.poi_id else None
        preset = {}
        if st:
            gate = st.get("gate") or {}
            preset = dict(
                seq=st.get("seq", 0), is_study_stop=True,
                narration_title=st.get("narration_title", ""),
                narration_text=st.get("narration_text", ""),
                task_card=(st.get("task_cards") or [{}])[0],
                photo_tip=st.get("photo_tip", ""),
                gate_status=gate.get("status", "open"),
                gate_notes=gate.get("notes", []),
                walk_in_min=st.get("walk_in_min", 0),
                stay_min=st.get("effective_stay_min", st.get("stay_min", 0)),
            )
        out_items.append(dict(
            id=it.id,
            slot=it.slot_type, slot_name=SLOT_NAME_MAP.get(it.slot_type, it.slot_type),
            poi_id=it.poi_id, name=brief.get("name", ""), category=brief.get("category", ""),
            start_time=it.start_time, duration_min=it.duration_min, cost=it.cost,
            travel_from_prev_min=0,
            transport_mode=it.transport_mode,
            longitude=brief.get("longitude"), latitude=brief.get("latitude"),
            ticket_price=brief.get("ticket_price", 0),
            image=(brief.get("images") or [None])[0],
            preset=preset,
        ))
    return dict(
        day_index=day.day_index, theme=day.theme, day_budget=day.day_budget,
        day_cost=day.day_cost, underfilled=False,
        items=[i for i in out_items if i["poi_id"] is not None],
    )


def trip_to_out(db: Session, trip: Trip) -> dict:
    days = sorted(trip.days_plan, key=lambda x: x.day_index)
    hotel = _poi_brief(db, days[0].hotel_id) if days and days[0].hotel_id else None
    stored = dict(trip.pace_config or {})
    preset_route = stored.get("preset_route")
    stop_by_poi: dict[int, dict] = {}
    if preset_route:
        for s in preset_route.get("stops", []):
            pid = s.get("effective_poi_id") or s.get("poi_id")
            if pid:
                stop_by_poi[int(pid)] = s
    days_plan = [_day_to_out(db, d, stop_by_poi) for d in days]
    hotel_total = hotel["ticket_price"] * max(0, trip.days - 1) if hotel else 0
    total_cost = round(sum(d["day_cost"] for d in days_plan) + hotel_total, 1)
    base_w = dict(get_mode_cfg(db, trip.mode).weights)
    custom_w = dict(trip.custom_weights or {})
    return dict(
        trip_id=trip.id, mode=trip.mode, mode_name=MODE_NAMES.get(trip.mode, trip.mode),
        days=trip.days, budget=trip.budget,
        total_cost=total_cost,
        budget_usage=round(total_cost / trip.budget, 3) if trip.budget else 0,
        score=trip.score,
        hotel=hotel, hotel_nights=max(0, trip.days - 1),
        days_plan=days_plan,
        relax_log=trip.relax_log or [],
        explanation=trip.explanation or [],
        custom_weights=custom_w,
        weight_profile=weight_profile(custom_w) if custom_w else weight_profile(base_w),
        is_personalized=bool(custom_w) and is_custom(custom_w, base_w),
        pace_config=stored,
        preset_route=preset_route,
        visit_date=trip.visit_date,
    )


# 出行方式 → 引擎通勤参数（速度 / 通勤代价系数 / 说明）
TRANSPORT_MAP: dict[str, dict] = {
    "self_drive": {"speed_kmh": 35.0, "mu_travel_cost": 0.10, "transit_desc": "自驾"},
    "taxi": {"speed_kmh": 30.0, "mu_travel_cost": 0.12, "transit_desc": "≤2 段打车"},
    "transit": {"speed_kmh": 20.0, "mu_travel_cost": 0.05, "transit_desc": "高（允许公交换乘）"},
    "walk_bike": {"speed_kmh": 8.0, "mu_travel_cost": 0.0, "transit_desc": "步行 / 骑行串联"},
}


def apply_cost_prefs(rules: dict, cost_prefs: dict | None) -> dict:
    """把开销偏好（住宿档位 / 出行方式）翻译进 rules 副本，返回规范化后的 cost_prefs。

    只影响本次生成，不污染库内模式配置。无效值会被忽略并剔除。
    """
    cp = dict(cost_prefs or {})
    hotel_tier = cp.get("hotel_tier")
    if hotel_tier is not None:
        try:
            rules["hotel_price_level_min"] = max(
                int(rules.get("hotel_price_level_min", 0)), int(hotel_tier)
            )
        except (TypeError, ValueError):
            cp.pop("hotel_tier", None)
    transport = cp.get("transport")
    if transport in TRANSPORT_MAP:
        rules.update(TRANSPORT_MAP[transport])
    else:
        cp.pop("transport", None)
    return cp


def create_trip(
    db: Session, days: int, budget: float, mode: str,
    preferences: list[str], party_type: str, seed: int | None, user_id: int | None,
    custom_weights: dict | None = None, pace: dict | None = None,
    cost_prefs: dict | None = None,
    preset_route_code: str | None = None, visit_date: str | None = None,
    include_addon: bool = False,
) -> dict:
    """生成行程并落库（方案 #3 / #15）。

    custom_weights：0~100 的关注度字典（前端滑块原值），归一化后覆盖模式默认权重。
    pace：节奏微调（每日点数上限 / 游玩小时上限 / 晚间偏好），只改本次 rules 副本。
    cost_prefs：开销偏好（住宿档位 / 出行方式），改写 rules 副本以影响实际生成。
    preset_route_code：命中预设主题路线时，站点按 seq 预占第 1 天（5.8 第 1 条），
        剩余槽位仍走正常贪心装箱 →「半天游学 + 半天按 mode 自由生成」。
    visit_date：驱动 date_gate（工作日闭馆 / 花期替换 / 预约提醒）日期感知判定。
    """
    cfg = get_mode_cfg(db, mode)
    rules = dict(cfg.hard_rules)
    base_weights = dict(cfg.weights)
    # A4：灰度命中候选版本时，用候选权重替换本次生成的基线权重
    base_weights, gray_meta = mode_version_service.effective_weights(
        db, mode, base_weights, key=(seed if seed is not None else 0)
    )

    # 权重个性化：归一化后替换模式默认（空则保持默认）
    slider_raw = {k: v for k, v in (custom_weights or {}).items() if v is not None}
    weights = normalize_weights(slider_raw, base_weights) if slider_raw else dict(base_weights)

    # 节奏微调：改写 rules 副本（住宿档次、时间窗等硬约束仍按模式口径）
    rules = apply_pace(rules, pace, mode)

    # 开销偏好：把"小部件"翻译成 rules（只影响本次生成，不污染库内模式配置）
    cost_prefs = apply_cost_prefs(rules, cost_prefs)

    cands, notes = stage1_candidates(db, rules, preferences)
    # 候选为空逐级放宽（5.2）：先去价格上限
    if not cands:
        rules["price_level_cap"] = 5
        cands, notes = stage1_candidates(db, rules, preferences)

    req = TripRequest(
        days=days, budget=budget, mode=mode,
        preferences=preferences, party_type=party_type,
        seed=seed if seed is not None else 0,
    )

    # ---- 预设主题路线（方案 5.8）：date_gate 判定 → 保底站点注入 ----
    preset_brief: dict | None = None
    preset_stops = None
    visit_date_str: str | None = None
    if preset_route_code:
        rr = resolve_for_generation(
            db, preset_route_code, visit_date, include_addon=include_addon
        )
        if not rr.stops:
            raise HTTPException(400, f"预设路线 {preset_route_code} 没有可注入的站点")
        preset_stops = rr.stops
        preset_brief = rr.brief
        visit_date_str = parse_visit_date(visit_date).isoformat()

    plan = generate_trip(cands, req, weights, rules, preset_stops=preset_stops)
    if preset_brief:
        # 日期闸门结论写 relax_log：自动降级 / 替换 / 提醒，而不是报错（5.8 第 2 条）
        for note in rr.relax_notes:
            log_relax(plan.relax_log, 0, 0, note)
        plan.days_plan[0].theme = preset_brief["title"] + " · 半日游学 + 自由游"
        plan.explanation.insert(
            1,
            f"本行程包含官方预设主题路线「{preset_brief['title']}」："
            f"站点按 seq 预占第 1 天，其余槽位按「{MODE_NAMES.get(mode, mode)}」自由补全。",
        )
        if preset_brief.get("reservation_note"):
            plan.explanation.append("⚠️ 入校预约：" + preset_brief["reservation_note"])

    trip_id = _gen_trip_id()
    merged_pace = {**(pace or {}), "cost_prefs": cost_prefs}
    if gray_meta:
        merged_pace["gray_version"] = gray_meta
    if preset_brief:
        # 线路详情存在已有 JSON 列里，重新打开行程（GET /trips/{id}）时仍能渲染逐站讲解
        merged_pace["preset_route"] = preset_brief
        merged_pace["include_addon"] = bool(include_addon)
    trip = Trip(
        id=trip_id, user_id=user_id, mode=mode, days=days, budget=budget,
        preferences=preferences, party_type=party_type,
        total_cost=plan.total_cost, score=plan.score, status="draft",
        seed=req.seed,
        custom_weights=weights if slider_raw else {},
        pace_config=merged_pace,
        preset_route_code=preset_route_code or None,
        visit_date=visit_date_str,
        relax_log=plan.relax_log, explanation=plan.explanation,
    )
    # relax_log/explanation 是 Trip 的 JSON 附加列（模型未定义则用动态属性存 JSON 列）
    db.add(trip)
    db.flush()

    for day in plan.days_plan:
        td = TripDay(trip_id=trip_id, day_index=day.day_index, theme=day.theme,
                     day_budget=day.day_budget, day_cost=day.day_cost,
                     hotel_id=plan.hotel.id if plan.hotel else None)
        db.add(td)
        db.flush()
        for idx, it in enumerate(day.items):
            if it.poi is None:
                continue
            db.add(TripItem(
                trip_day_id=td.id, slot_type=it.slot, poi_id=it.poi.id,
                start_time=it.start_time or "", duration_min=it.duration_min,
                cost=it.cost, order_index=idx,
            ))
    db.commit()

    return _plan_to_out(
        plan, trip_id, weights, merged_pace, base_weights,
        preset_route=preset_brief, visit_date=visit_date_str,
    )


def _plan_to_out(plan, trip_id: str, weights: dict | None = None,
                 pace: dict | None = None, base_weights: dict | None = None,
                 preset_route: dict | None = None,
                 visit_date: str | None = None) -> dict:
    """直接由内存 plan 组装响应（含游学保底站的逐站讲解与 date_gate 结论）。"""
    hotel = None
    if plan.hotel:
        hotel = dict(
            poi_id=plan.hotel.id, name=plan.hotel.name, category="hotel",
            longitude=plan.hotel.longitude, latitude=plan.hotel.latitude,
            ticket_price=plan.hotel.cost, sub_type=plan.hotel.grade,
        )
    days_plan = []
    for d in plan.days_plan:
        items = []
        for it in d.items:
            if it.poi is None:
                continue
            items.append(dict(
                slot=it.slot, slot_name=SLOT_NAME_MAP.get(it.slot, it.slot),
                poi_id=it.poi.id, name=it.poi.name, category=it.poi.category,
                start_time=it.start_time, duration_min=it.duration_min, cost=it.cost,
                travel_from_prev_min=it.travel_from_prev_min,
                longitude=it.poi.longitude, latitude=it.poi.latitude,
                ticket_price=it.poi.ticket_price,
                image=(list(it.poi.images or [None]) or [None])[0],
                preset=dict(it.preset_meta) if it.preset_seq else {},
            ))
        days_plan.append(dict(
            day_index=d.day_index, theme=d.theme, day_budget=d.day_budget,
            day_cost=d.day_cost, underfilled=d.underfilled, items=items,
        ))
    return dict(
        trip_id=trip_id, mode=plan.mode, mode_name=MODE_NAMES.get(plan.mode, plan.mode),
        days=plan.days, budget=plan.budget,
        total_cost=plan.total_cost, budget_usage=plan.budget_usage,
        score=plan.score, hotel=hotel, hotel_nights=plan.hotel_nights,
        days_plan=days_plan, relax_log=plan.relax_log, explanation=plan.explanation,
        custom_weights=dict(weights or {}),
        weight_profile=weight_profile(weights) if weights else [],
        is_personalized=bool(weights) and (
            is_custom(weights, base_weights) if base_weights else True
        ),
        pace_config=dict(pace or {}),
        preset_route=preset_route,
        visit_date=visit_date,
    )


def rebalance(
    db: Session, trip_id: str, day_index: int, action: str,
    slot: str | None, poi_id: int | None,
) -> dict:
    """#4：单日重排（redrop）或槽位替换（replace），其余日锁定。"""
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在或已过期")
    cfg = get_mode_cfg(db, trip.mode)
    rules = dict(cfg.hard_rules)
    base_weights = dict(cfg.weights)
    # 行程若经过个性化，则重排继续沿用其权重与节奏，保证"换一批"口径一致
    custom_w = dict(trip.custom_weights or {})
    weights = custom_w or base_weights
    rules = apply_pace(rules, trip.pace_config or None, trip.mode)

    days = sorted(trip.days_plan, key=lambda x: x.day_index)
    target = next((d for d in days if d.day_index == day_index), None)
    if not target:
        raise HTTPException(404, f"第 {day_index} 天不存在")

    locked_ids = {
        it.poi_id for d in days if d.day_index != day_index
        for it in d.items if it.poi_id
    }
    today_ids = {it.poi_id for it in target.items if it.poi_id}

    cands, _ = stage1_candidates(db, rules, trip.preferences or [])

    if action == "redrop":
        hotel_pp = _load_hotel_pp(db, days[0].hotel_id)
        ctx = dict(
            day_index=day_index, day_budget=target.day_budget,
            locked_ids=locked_ids, today_ids=today_ids,
            hotel=hotel_pp,
            req=TripRequest(days=trip.days, budget=trip.budget, mode=trip.mode,
                            preferences=trip.preferences or [],
                            seed=(trip.seed or 0) + secrets.randbelow(9999) + 1),
        )
        if trip.preset_route_code and day_index == 1:
            # 官方保底动线不能被"换一批"抹掉：整程重算后取第 1 天（5.8 复用全部约束校验）
            stored = dict(trip.pace_config or {})
            try:
                rr = resolve_for_generation(
                    db, trip.preset_route_code, trip.visit_date,
                    include_addon=bool(stored.get("include_addon")),
                )
                full_plan = generate_trip(
                    cands, ctx["req"], weights, rules, preset_stops=rr.stops or None
                )
                new_day = full_plan.days_plan[0]
                new_day.theme = (
                    (stored.get("preset_route") or {}).get("title", "预设主题路线")
                    + " · 半日游学 + 自由游"
                )
            except HTTPException:
                new_day = replan_day(ctx, cands, rules, weights)
        else:
            new_day = replan_day(ctx, cands, rules, weights)

        # 写回 DB：删除当日旧 items，插入新 items
        for it in list(target.items):
            db.delete(it)
        db.flush()
        day_cost = 0.0
        for idx, it in enumerate(new_day.items):
            if it.poi is None:
                continue
            db.add(TripItem(
                trip_day_id=target.id, slot_type=it.slot, poi_id=it.poi.id,
                start_time=it.start_time or "", duration_min=it.duration_min,
                cost=it.cost, order_index=idx,
            ))
            day_cost += it.cost
        target.day_cost = day_cost
        target.theme = new_day.theme
        db.commit()
    else:  # replace
        if not slot:
            raise HTTPException(400, "replace 动作需要 slot 参数")
        item = next((it for it in target.items if it.slot_type == slot), None)
        if not item:
            raise HTTPException(404, f"槽位 {slot} 不存在")

        if poi_id is None:
            # 自动推荐同类候选中分数最高且未使用的
            same_cat = [c for c in cands
                        if c.category == (db.get(Poi, item.poi_id).category if item.poi_id else c.category)
                        and c.id not in (locked_ids | today_ids)]
            if not same_cat:
                raise HTTPException(400, "暂无可替换的同类候选")
            from app.planner.scoring import static_scores
            static_scores(same_cat)
            best = max(same_cat, key=lambda p: sum(
                weights.get(k, 0) * p.static.get(k, 0) for k in weights if k != "budget_fit"))
            poi_id = best.id

        old_poi = item.poi_id
        item.poi_id = poi_id
        new_p = db.get(Poi, poi_id)
        item.duration_min = new_p.suggest_duration_min
        item.cost = (db.get(PoiExtHotel, poi_id).price_min if new_p.category == "hotel"
                     else (db.get(PoiExtFood, poi_id).avg_price if new_p.category == "food"
                           else new_p.ticket_price))
        target.day_cost = sum(it.cost for it in target.items)
        db.commit()

    out = trip_to_out(db, trip)
    return out


def _load_hotel_pp(db: Session, hotel_id: int | None) -> PlannerPoi | None:
    if not hotel_id:
        return None
    p = db.get(Poi, hotel_id)
    if not p:
        return None
    e = db.get(PoiExtHotel, p.id)
    return PlannerPoi(
        id=p.id, name=p.name, category="hotel", longitude=p.longitude,
        latitude=p.latitude, suggest_duration_min=p.suggest_duration_min,
        ticket_price=p.ticket_price, price_level=p.price_level, rating=p.rating,
        hot_score=p.hot_score, quality_score=p.quality_score,
        avg_price=e.price_min if e else p.ticket_price,
    )


def slot_candidates(db: Session, trip_id: str, day_index: int, slot: str) -> list[dict]:
    """槽位替换候选（半屏弹层数据）：同类、未在行程中使用的 POI。"""
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    days = sorted(trip.days_plan, key=lambda x: x.day_index)
    target = next((d for d in days if d.day_index == day_index), None)
    if not target:
        raise HTTPException(404, f"第 {day_index} 天不存在")
    item = next((it for it in target.items if it.slot_type == slot), None)
    cur_cat = db.get(Poi, item.poi_id).category if item and item.poi_id else None

    used_ids = {it.poi_id for d in days for it in d.items if it.poi_id}
    q = db.query(Poi).filter(Poi.visitable.is_(True), Poi.id.notin_(used_ids))
    if cur_cat:
        q = q.filter(Poi.category == cur_cat)
    rows = q.order_by(Poi.hot_score.desc()).limit(12).all()
    return [dict(
        poi_id=p.id, name=p.name, category=p.category, sub_type=p.sub_type,
        rating=p.rating, ticket_price=p.ticket_price,
        suggest_duration_min=p.suggest_duration_min, address=p.address,
        longitude=p.longitude, latitude=p.latitude,
        image=(list(p.images or [None]) or [None])[0],
    ) for p in rows]


def save_trip(db: Session, trip_id: str, user_id: int) -> dict:
    """#10：保存行程（匿名 → 绑定用户）。"""
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    trip.user_id = user_id
    trip.status = "saved"
    _bump_user_stat(db, user_id, trip)
    db.commit()
    return dict(trip_id=trip_id, message="已保存到我的行程")


def _bump_user_stat(db: Session, user_id: int, trip: Trip) -> None:
    """A5：维护用户行程统计表（保存时同步，避免全表聚合查询）。"""
    stat = db.get(UserTripStat, user_id)
    if stat is None:
        stat = UserTripStat(user_id=user_id, trip_count=0, saved_count=0, total_cost=0)
        db.add(stat)
        db.flush()
    stat.saved_count = int(stat.saved_count or 0) + 1
    stat.total_cost = round(float(stat.total_cost or 0) + float(trip.total_cost or 0), 1)
    stat.last_trip_at = trip.created_at or datetime.utcnow()


# ---------- 个性化：权重预览 + 按权重重排 ----------

def preview_weights(
    db: Session,
    mode: str,
    slider_raw: dict | None,
    preferences: list[str] | None = None,
    pace: dict | None = None,
    top_k: int = 12,
) -> dict:
    """权重预览：不落库，只返回按新权重重排后的候选 POI 与分数变化。

    用于前端滑块拖动时的实时反馈——让用户直观看到"权重怎么改，路线怎么变"。
    """
    from app.planner.scoring import static_scores

    cfg = get_mode_cfg(db, mode)
    base_weights = dict(cfg.weights)
    rules = apply_pace(dict(cfg.hard_rules), pace, mode)
    weights = normalize_weights(
        {k: v for k, v in (slider_raw or {}).items() if v is not None}, base_weights
    )

    cands, _ = stage1_candidates(db, rules, preferences or [])
    if not cands:
        rules["price_level_cap"] = 5
        cands, _ = stage1_candidates(db, rules, preferences or [])
    if not cands:
        return dict(mode=mode, weights=weights, items=[], changed=[])

    static_scores(cands)

    def _rank(w: dict[str, float]) -> dict[int, float]:
        out = {}
        for p in cands:
            s = sum(w.get(k, 0.0) * p.static.get(k, 0.0)
                    for k in w if k != "budget_fit")
            s += w.get("budget_fit", 0.0) * 0.6  # 预算贴合用中位水平近似，仅用于排序参考
            out[p.id] = round(s, 4)
        return out

    base_rank = _rank(base_weights)
    new_rank = _rank(weights)

    def _order(rank: dict[int, float]) -> list[int]:
        return sorted(rank.keys(), key=lambda i: -rank[i])

    base_order = _order(base_rank)
    new_order = _order(new_rank)
    base_pos = {pid: i for i, pid in enumerate(base_order)}

    by_id = {p.id: p for p in cands}
    items = []
    for pid in new_order[:top_k]:
        p = by_id[pid]
        items.append(dict(
            poi_id=p.id, name=p.name, category=p.category, sub_type=p.sub_type,
            rating=p.rating, ticket_price=p.ticket_price,
            suggest_duration_min=p.suggest_duration_min,
            score=new_rank[pid], base_score=base_rank[pid],
            rank=new_order.index(pid) + 1,
            base_rank=base_pos.get(pid, 0) + 1,
            image=(list(p.images or [None]) or [None])[0],
        ))

    base_top = set(base_order[:top_k])
    new_top = set(new_order[:top_k])
    changed = []
    for pid in list(new_top - base_top)[:6]:
        p = by_id[pid]
        changed.append(dict(
            poi_id=p.id, name=p.name, direction="up",
            image=(list(p.images or [None]) or [None])[0],
        ))
    for pid in list(base_top - new_top)[:6]:
        p = by_id[pid]
        changed.append(dict(
            poi_id=p.id, name=p.name, direction="down",
            image=(list(p.images or [None]) or [None])[0],
        ))

    return dict(
        mode=mode,
        weights=weights,
        profile=weight_profile(weights),
        base_weights=base_weights,
        is_personalized=is_custom(weights, base_weights),
        items=items,
        changed=changed,
    )


def reweight_trip(
    db: Session,
    trip_id: str,
    slider_raw: dict | None,
    pace: dict | None = None,
    keep_budget: bool = True,
) -> dict:
    """按新权重重排既有行程：沿用天数/预算/偏好，仅换权重与节奏。

    行程已保存到"我的行程"时，保留 user_id 与 status。
    """
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在或已过期")

    cfg = get_mode_cfg(db, trip.mode)
    base_weights = dict(cfg.weights)
    weights = normalize_weights(
        {k: v for k, v in (slider_raw or {}).items() if v is not None}, base_weights
    )
    rules = apply_pace(dict(cfg.hard_rules), pace, trip.mode)
    stored = dict(trip.pace_config or {})
    # 重排沿用既有开销偏好（住宿档位 / 出行方式），保证"换一批"口径一致
    stored_cost = stored.get("cost_prefs") or {}
    incoming_cost = dict(pace or {}).get("cost_prefs") or {}
    cost_prefs = apply_cost_prefs(rules, {**stored_cost, **incoming_cost})

    cands, _ = stage1_candidates(db, rules, trip.preferences or [])
    if not cands:
        rules["price_level_cap"] = 5
        cands, _ = stage1_candidates(db, rules, trip.preferences or [])

    req = TripRequest(
        days=trip.days, budget=trip.budget, mode=trip.mode,
        preferences=trip.preferences or [], party_type=trip.party_type or "",
        seed=(trip.seed or 0) + secrets.randbelow(9999) + 1,
    )
    # 游学行程按权重重排时，官方保底动线继续注入，不能被重排抹掉（5.8 复用全部逻辑）
    preset_stops = None
    preset_notes: list[str] = []
    if trip.preset_route_code:
        try:
            rr = resolve_for_generation(
                db, trip.preset_route_code, trip.visit_date,
                include_addon=bool(stored.get("include_addon")),
            )
            preset_stops = rr.stops
            preset_notes = rr.relax_notes
        except HTTPException:
            preset_stops = None   # 线路已下架时退化为普通重排，不阻断
    plan = generate_trip(cands, req, weights, rules, preset_stops=preset_stops)
    if preset_stops:
        for note in preset_notes:
            log_relax(plan.relax_log, 0, 0, note)
        if plan.days_plan:
            plan.days_plan[0].theme = (
                (stored.get("preset_route") or {}).get("title", "预设主题路线")
                + " · 半日游学 + 自由游"
            )

    # 清空旧日程并写入新日程（行程 id 保持不变，历史链接不失效）
    for d in list(trip.days_plan):
        db.delete(d)
    db.flush()

    for day in plan.days_plan:
        td = TripDay(
            trip_id=trip_id, day_index=day.day_index, theme=day.theme,
            day_budget=day.day_budget, day_cost=day.day_cost,
            hotel_id=plan.hotel.id if plan.hotel else None,
        )
        db.add(td)
        db.flush()
        for idx, it in enumerate(day.items):
            if it.poi is None:
                continue
            db.add(TripItem(
                trip_day_id=td.id, slot_type=it.slot, poi_id=it.poi.id,
                start_time=it.start_time or "", duration_min=it.duration_min,
                cost=it.cost, order_index=idx,
            ))

    trip.custom_weights = weights
    merged_pace = {**(pace or {}), "cost_prefs": cost_prefs}
    if stored.get("preset_route"):
        merged_pace["preset_route"] = stored["preset_route"]
    if stored.get("include_addon"):
        merged_pace["include_addon"] = True
    trip.pace_config = merged_pace
    trip.total_cost = plan.total_cost
    trip.score = plan.score
    trip.relax_log = plan.relax_log
    trip.explanation = plan.explanation
    trip.seed = req.seed
    db.commit()
    db.refresh(trip)
    return trip_to_out(db, trip)


def my_trips(db: Session, user_id: int, page: int, page_size: int):
    q = db.query(Trip).filter(Trip.user_id == user_id, Trip.status == "saved") \
        .order_by(Trip.created_at.desc())
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    out = []
    for t in rows:
        out.append(dict(
            trip_id=t.id, mode=t.mode, mode_name=MODE_NAMES.get(t.mode, t.mode),
            days=t.days, budget=t.budget, total_cost=t.total_cost,
            score=t.score, created_at=t.created_at.isoformat() if t.created_at else "",
        ))
    return total, out

