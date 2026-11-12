"""T4 增量重算：改天数 / 预算后只做必要调整，不整单重生成。

策略：
- 天数增加：保留原有日程，仅追加新的一天（候选排除已用 POI，避免重复）；
- 天数减少：保留前 N 天，删除多余日程；
- 预算变化：按新预算重新分摊每日额度；预算下调时从得分最低的非保底条目开始裁剪，
  直到回到弹性上限内。
- 若同时传入权重 / 节奏，则在天数预算落库后复用既有 `reweight_trip` 完成重排。
"""
from __future__ import annotations

import random

from sqlalchemy.orm import Session

from app.models import Trip, TripDay, TripItem
from app.planner.engine import _order_windows, _pack_one_day
from app.planner.models import TripRequest
from app.planner.ordering import order_day_items
from app.planner.relax import log_relax
from app.planner.weights import apply_pace
from app.services.poi_service import stage1_candidates


def incremental_replan(
    db: Session, trip_id: str,
    days: int | None = None, budget: float | None = None,
    weights: dict | None = None, pace: dict | None = None,
) -> dict:
    from app.services.trip_service import (
        _load_hotel_pp, get_mode_cfg, reweight_trip, trip_to_out,
    )

    trip = db.get(Trip, trip_id)
    if trip is None:
        raise ValueError("行程不存在或已过期")

    new_days = int(days or trip.days)
    new_budget = float(budget if budget is not None else trip.budget)
    changed = new_days != trip.days or abs(new_budget - trip.budget) > 0.001
    if changed:
        cfg = get_mode_cfg(db, trip.mode)
        rules = apply_pace(dict(cfg.hard_rules), trip.pace_config or None, trip.mode)
        base_weights = dict(cfg.weights)
        weights_for_plan = dict(trip.custom_weights or base_weights)

        days_sorted = sorted(trip.days_plan, key=lambda x: x.day_index)
        hotel_id = days_sorted[0].hotel_id if days_sorted else None
        hotel_pp = _load_hotel_pp(db, hotel_id)
        hotel_total = (hotel_pp.cost if hotel_pp else 0) * max(0, new_days - 1)
        day_budget = round(max(0.0, new_budget - hotel_total) / new_days, 1)

        # ---- 1) 删减多余天数 ----
        for d in days_sorted:
            if d.day_index > new_days:
                db.delete(d)
        keep = [d for d in days_sorted if d.day_index <= new_days]
        db.flush()

        # ---- 2) 追加新天数（保留原日程不动） ----
        max_kept = max((d.day_index for d in keep), default=0)
        if new_days > max_kept:
            _append_days(db, trip, rules, weights_for_plan, hotel_pp,
                         day_budget, max_kept + 1, new_days)

        # ---- 3) 重设每日预算 ----
        for d in keep:
            d.day_budget = day_budget
            if hotel_id is not None:
                d.hotel_id = hotel_id

        # ---- 4) 超出弹性上限时裁剪（含加天数带来的住宿增支） ----
        relax = list(trip.relax_log or [])
        _trim_to_budget(db, trip, hotel_total, rules, relax, new_budget)
        log_relax(
            relax, 0, 0,
            f"已按新参数增量重算：{trip.days} 天 → {new_days} 天，"
            f"预算 {trip.budget:.0f} → {new_budget:.0f} 元（保留原有日程）。",
        )

        trip.days = new_days
        trip.budget = new_budget
        trip.relax_log = relax
        explanation = list(trip.explanation or [])
        note = f"本次为增量重算：天数 {new_days} 天、预算 {new_budget:.0f} 元，已保留可复用日程。"
        if note not in explanation:
            explanation.append(note)
        trip.explanation = explanation
        _refresh_total(db, trip, hotel_total)
        db.commit()

    if weights or pace:
        return reweight_trip(db, trip_id, slider_raw=weights, pace=pace)
    return trip_to_out(db, trip)


def _append_days(
    db: Session, trip: Trip, rules: dict, weights: dict,
    hotel_pp, day_budget: float, start: int, end: int,
) -> None:
    """用与全量生成一致的贪心装箱追加新的一天。"""
    cands, _ = stage1_candidates(db, rules, trip.preferences or [])
    if not cands:
        rules = dict(rules)
        rules["price_level_cap"] = 5
        cands, _ = stage1_candidates(db, rules, trip.preferences or [])
    play_pool = [p for p in cands if p.category in ("scenic", "leisure")]
    food_pool = [p for p in cands if p.category == "food"]

    used = {it.poi_id for d in trip.days_plan for it in d.items if it.poi_id}
    if hotel_pp is not None:
        used.add(hotel_pp.id)

    req = TripRequest(
        days=end, budget=trip.budget, mode=trip.mode,
        preferences=list(trip.preferences or []), party_type=trip.party_type or "",
        seed=trip.seed or 0,
    )
    relax: list[dict] = []
    for day_index in range(start, end + 1):
        rng = random.Random((trip.seed or 0) + day_index)
        day = _pack_one_day(
            day_index, [], play_pool, food_pool, hotel_pp,
            day_budget, rules, weights, rng, used, req, relax,
        )
        order_day_items(
            day, hotel_pp, rules["speed_kmh"], rules["day_start"], rules["day_end"],
            **_order_windows(rules, trip.mode),
        )
        td = TripDay(
            trip_id=trip.id, day_index=day.day_index, theme=day.theme,
            day_budget=day.day_budget, day_cost=day.day_cost,
            hotel_id=hotel_pp.id if hotel_pp else None,
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
    db.flush()


def _trim_to_budget(
    db: Session, trip: Trip, hotel_total: float, rules: dict,
    relax: list[dict], new_budget: float,
) -> None:
    """预算下调：从评分最低的非保底条目开始移除，直到进入弹性区间。"""
    from app.models import Poi

    preset = (trip.pace_config or {}).get("preset_route") or {}
    preset_ids = {
        int(s.get("effective_poi_id") or s.get("poi_id"))
        for s in (preset.get("stops") or [])
        if s.get("effective_poi_id") or s.get("poi_id")
    }

    cap = new_budget * float(rules.get("budget_elasticity_max", 1.1))
    # 以数据库为准：追加/删除天数后 trip.days_plan 关系可能尚未刷新
    days = (
        db.query(TripDay)
        .filter(TripDay.trip_id == trip.id)
        .order_by(TripDay.day_index.asc())
        .all()
    )
    cur = hotel_total + sum(float(d.day_cost or 0) for d in days)
    removed_ids: set[int] = set()
    guard = 0
    while cur > cap and guard < 40:
        guard += 1
        worst: TripItem | None = None
        worst_key: tuple[float, float] | None = None
        for d in days:
            for it in d.items:
                # 已删除条目可能仍在集合中，需显式跳过，避免重复扣减
                if it.id in removed_ids or not it.poi_id or it.poi_id in preset_ids:
                    continue
                poi = db.get(Poi, it.poi_id)
                key = (
                    float(poi.rating or 0) if poi else 0.0,
                    -float(it.cost or 0),
                )
                if worst_key is None or key < worst_key:
                    worst, worst_key = it, key
        if worst is None:
            break
        poi_name = (db.get(Poi, worst.poi_id).name if worst.poi_id else "条目")
        cur -= float(worst.cost or 0)
        removed_ids.add(worst.id)
        log_relax(
            relax, 0, 2,
            f"预算下调：已移除「{poi_name}」",
        )
        db.delete(worst)
        db.flush()

    # 按剩余条目重算每日花费，避免增量扣减产生负数
    for d in days:
        d.day_cost = round(
            sum(float(it.cost or 0) for it in d.items if it.id not in removed_ids), 1
        )
    db.flush()
    if cur > cap:
        log_relax(relax, 0, 2, "预算下调后仍略超弹性上限，建议适当提高预算或减少天数")


def _refresh_total(db: Session, trip: Trip, hotel_total: float) -> None:
    from sqlalchemy import func

    db.flush()
    day_total = (
        db.query(func.coalesce(func.sum(TripDay.day_cost), 0.0))
        .filter(TripDay.trip_id == trip.id)
        .scalar()
    ) or 0.0
    total = round(hotel_total + float(day_total), 1)
    trip.total_cost = total
    trip.budget_usage = round(total / trip.budget, 3) if trip.budget else 0
