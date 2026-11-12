"""行程编辑与体检：删除 / 移动 / 复制 / 替换点位 + 时间轴重算 + 规则诊断。

原则：编辑操作用户确认后由后端确定性执行（不依赖大模型），时间轴根据
「点位停留时长 + 相邻通勤估算」重新推算，保证编辑后行程仍然自洽。
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Poi, PoiExtScenic, Trip, TripDay, TripItem
from app.services.trip_service import PLAY_CATEGORIES, date_meta, get_mode_cfg, trip_to_out

SPEED_KMH = 20.0          # 通勤平均速度（与引擎默认公交/混合口径一致）
ROAD_FACTOR = 1.4         # 直线 → 道路绕行系数
TRANSFER_MIN = 5          # 每段额外换乘/步行缓冲
MODE_SPEED_KMH = {        # 用户指定出行方式时的估算速度
    "walking": 4.5, "riding": 12.0, "taxi": 30.0, "driving": 30.0, "transit": 20.0,
}


# ---------- 基础工具 ----------

def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _poi(db: Session, poi_id: int) -> Poi:
    poi = db.get(Poi, poi_id) if poi_id else None
    if not poi:
        raise HTTPException(404, "点位不存在")
    return poi


def _travel_minutes(db: Session, a: TripItem, b: TripItem) -> int:
    if not a.poi_id or not b.poi_id:
        return 0
    pa, pb = db.get(Poi, a.poi_id), db.get(Poi, b.poi_id)
    if not pa or not pb or None in (pa.longitude, pa.latitude, pb.longitude, pb.latitude):
        return TRANSFER_MIN
    dist = _haversine_km(pa.longitude, pa.latitude, pb.longitude, pb.latitude) * ROAD_FACTOR
    mode = getattr(b, "transport_mode", None)
    speed = MODE_SPEED_KMH.get(mode or "", SPEED_KMH)
    buffer = 5 if (mode or "transit") in ("walking", "transit") else 3
    return int(round(dist / speed * 60)) + buffer


def _hhmm_to_min(s: str | None, default: int) -> int:
    try:
        parts = str(s or "").strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return default


def _fmt_hhmm(minutes: int) -> str:
    minutes = max(0, min(int(minutes), 23 * 60 + 59))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ---------- 时间轴重算与费用汇总 ----------

def _retime_day(db: Session, trip: Trip, day: TripDay) -> None:
    """按点位顺序重推当天每个点的开始时间（含通勤）。"""
    items = sorted(day.items, key=lambda x: x.order_index)
    rules = get_mode_cfg(db, trip.mode).hard_rules or {}
    cursor = _hhmm_to_min(rules.get("day_start"), 9 * 60)
    prev: TripItem | None = None
    for it in items:
        if prev is not None:
            cursor += _travel_minutes(db, prev, it)
        it.start_time = _fmt_hhmm(cursor)
        cursor += int(it.duration_min or 60)
        prev = it


def _recalc_cost(db: Session, trip: Trip) -> None:
    """按当前点位重算每天花费与行程总花费（住宿按首日酒店价 × 晚数）。"""
    days = sorted(trip.days_plan, key=lambda x: x.day_index)
    for day in days:
        day.day_cost = round(sum(float(it.cost or 0) for it in day.items), 1)
    hotel_total = 0.0
    if days and days[0].hotel_id:
        hotel = db.get(Poi, days[0].hotel_id)
        if hotel:
            hotel_total = float(hotel.ticket_price or 0) * max(0, trip.days - 1)
    trip.total_cost = round(sum(d.day_cost for d in days) + hotel_total, 1)


def _renumber(day: TripDay) -> None:
    for idx, it in enumerate(sorted(day.items, key=lambda x: x.order_index)):
        it.order_index = idx


def _trip(db: Session, trip_id: str) -> Trip:
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在或已过期")
    return trip


def _item(db: Session, trip: Trip, item_id: int) -> tuple[TripDay, TripItem]:
    day = next((d for d in trip.days_plan if any(it.id == item_id for it in d.items)), None)
    if not day:
        raise HTTPException(404, "行程项不存在")
    return day, next(it for it in day.items if it.id == item_id)


def _day_by_index(trip: Trip, day_index: int) -> TripDay:
    day = next((d for d in trip.days_plan if d.day_index == day_index), None)
    if not day:
        raise HTTPException(404, "行程日不存在")
    return day


def _finish(db: Session, trip: Trip) -> dict:
    db.commit()
    db.refresh(trip)
    return trip_to_out(db, trip)


# ---------- 编辑操作 ----------

def delete_item(db: Session, trip_id: str, item_id: int) -> dict:
    trip = _trip(db, trip_id)
    day, item = _item(db, trip, item_id)
    day.items.remove(item)
    db.delete(item)
    db.flush()
    _renumber(day)
    _retime_day(db, trip, day)
    _recalc_cost(db, trip)
    return _finish(db, trip)


def move_item(
    db: Session, trip_id: str, item_id: int, target_day: int, target_index: int | None = None,
) -> dict:
    trip = _trip(db, trip_id)
    src_day, item = _item(db, trip, item_id)
    dst_day = _day_by_index(trip, target_day)
    if dst_day.id == src_day.id:
        raise HTTPException(400, "目标与当前天相同，直接上下移动即可")
    src_day.items.remove(item)
    dst_day.items.append(item)
    item.trip_day_id = dst_day.id
    db.flush()
    _renumber(src_day)
    if target_index is None:
        item.order_index = len(dst_day.items) - 1
    else:
        ordered = sorted(dst_day.items, key=lambda x: x.order_index)
        ordered.remove(item)
        ordered.insert(max(0, min(int(target_index), len(ordered))), item)
        for idx, it in enumerate(ordered):
            it.order_index = idx
    db.flush()
    for day in {src_day.id: src_day, dst_day.id: dst_day}.values():
        _retime_day(db, trip, day)
    _recalc_cost(db, trip)
    return _finish(db, trip)


def copy_item(db: Session, trip_id: str, item_id: int, target_day: int) -> dict:
    trip = _trip(db, trip_id)
    src_day, item = _item(db, trip, item_id)
    dst_day = _day_by_index(trip, target_day)
    clone = TripItem(
        trip_day_id=dst_day.id, slot_type=item.slot_type, poi_id=item.poi_id,
        start_time=item.start_time, duration_min=item.duration_min,
        cost=item.cost, order_index=len(dst_day.items),
        transport_mode=getattr(item, "transport_mode", None),
    )
    db.add(clone)
    db.flush()
    _retime_day(db, trip, dst_day)
    _recalc_cost(db, trip)
    return _finish(db, trip)


def replace_item(db: Session, trip_id: str, item_id: int, poi_id: int) -> dict:
    trip = _trip(db, trip_id)
    day, item = _item(db, trip, item_id)
    poi = _poi(db, poi_id)
    if poi.category in ("hotel",):
        raise HTTPException(400, "住宿不能作为行程槽位替换")
    item.poi_id = poi.id
    item.cost = round(float(poi.ticket_price or 0), 1)
    _retime_day(db, trip, day)
    _recalc_cost(db, trip)
    return _finish(db, trip)


# ---------- 行程体检（行程判官） ----------

def diagnose(db: Session, trip_id: str) -> dict:
    trip = _trip(db, trip_id)
    rules = get_mode_cfg(db, trip.mode).hard_rules or {}
    poi_cache: dict[int, Poi] = {}
    issues: list[dict] = []

    def poi_of(it: TripItem) -> Poi | None:
        if not it.poi_id:
            return None
        if it.poi_id not in poi_cache:
            poi_cache[it.poi_id] = db.get(Poi, it.poi_id)
        return poi_cache[it.poi_id]

    max_items = int(rules.get("daily_poi_max") or 99)
    min_items = int(rules.get("daily_poi_min") or 1)
    max_hours = float(rules.get("daily_play_hours_max") or 24)

    for day in sorted(trip.days_plan, key=lambda x: x.day_index):
        items = sorted(day.items, key=lambda x: x.order_index)
        # 只统计"游玩类"点位（餐饮/住宿槽位不计入模式点位上限与游玩时长）
        play_items = [it for it in items
                      if (poi := poi_of(it)) is not None and poi.category in PLAY_CATEGORIES]
        if len(play_items) > max_items:
            issues.append(dict(level="warn", day_index=day.day_index, title="当天游玩点位偏多",
                               detail=f"当前 {len(play_items)} 个游玩点，超过模式上限 {max_items} 个，建议删减或分天。",
                               item_ids=[it.id for it in play_items]))
        if len(play_items) < min_items:
            issues.append(dict(level="info", day_index=day.day_index, title="当天游玩点位偏少",
                               detail=f"当前 {len(play_items)} 个游玩点，低于模式建议下限 {min_items} 个。",
                               item_ids=[it.id for it in play_items]))
        play_minutes = sum(int(it.duration_min or 0) for it in play_items)
        if play_minutes / 60 > max_hours:
            issues.append(dict(level="warn", day_index=day.day_index, title="当天游玩时长偏紧",
                               detail=f"游玩合计约 {play_minutes/60:.1f} 小时，超过模式上限 {max_hours:g} 小时，注意体力与闭园时间。",
                               item_ids=[it.id for it in play_items]))

        # 相邻点位距离：>15km 视为折返；2~15km 给出交通建议
        for prev, cur in zip(items, items[1:]):
            pa, pb = poi_of(prev), poi_of(cur)
            if not pa or not pb or None in (pa.longitude, pa.latitude, pb.longitude, pb.latitude):
                continue
            dist = _haversine_km(pa.longitude, pa.latitude, pb.longitude, pb.latitude)
            if dist > 15:
                issues.append(dict(
                    level="warn", day_index=day.day_index, title="相邻点位跨度较大",
                    detail=f"「{pa.name}」→「{pb.name}」直线约 {dist:.1f} km，可能来回折返，建议调整顺序或合并到同一天。",
                    item_ids=[prev.id, cur.id],
                ))
            elif dist > 2:
                issues.append(dict(
                    level="info", day_index=day.day_index, title="建议确认交通方式",
                    detail=f"「{pa.name}」→「{pb.name}」直线约 {dist:.1f} km，步行偏累，建议骑行/打车或公交。",
                    item_ids=[prev.id, cur.id],
                ))

        # 开放时间冲突（只检查能解析出 HH:MM-HH:MM 的点位）
        for it in items:
            poi = poi_of(it)
            if not poi or not poi.open_time or "-" not in poi.open_time:
                continue
            try:
                open_s, close_s = [x.strip() for x in poi.open_time.split("-")[:2]]
                open_m = _hhmm_to_min(open_s, 0)
                close_m = _hhmm_to_min(close_s, 24 * 60)
                start_m = _hhmm_to_min(it.start_time, 0)
            except ValueError:
                continue
            if start_m < open_m:
                issues.append(dict(level="warn", day_index=day.day_index, title="早于开放时间",
                                   detail=f"「{poi.name}」开放时间 {poi.open_time}，但安排 {it.start_time} 到达。",
                                   item_ids=[it.id]))
            elif start_m >= close_m:
                issues.append(dict(level="warn", day_index=day.day_index, title="晚于开放时间",
                                   detail=f"「{poi.name}」开放时间 {poi.open_time}，但安排在 {it.start_time} 之后。",
                                   item_ids=[it.id]))

    # 同一地点重复出现
    seen: dict[int, list[str]] = {}
    for day in trip.days_plan:
        for it in day.items:
            if it.poi_id:
                seen.setdefault(it.poi_id, []).append(f"Day{day.day_index}")
    for poi_id, days in seen.items():
        if len(days) > 1:
            poi = db.get(Poi, poi_id)
            issues.append(dict(level="info", day_index=None, title="点位重复出现",
                               detail=f"「{poi.name if poi else poi_id}」在 {'、'.join(days)} 重复安排，可考虑替换。",
                               item_ids=[]))

    # 预算
    if trip.budget and trip.total_cost > trip.budget:
        issues.append(dict(level="warn", day_index=None, title="预算超支",
                           detail=f"预计花费 ¥{trip.total_cost:.0f} 超过预算 ¥{trip.budget:.0f}，建议换更便宜的餐饮/住宿或减少点位。",
                           item_ids=[]))
    elif trip.budget and trip.total_cost / trip.budget < 0.6:
        issues.append(dict(level="info", day_index=None, title="预算利用偏低",
                           detail=f"预计花费仅占预算 {trip.total_cost / trip.budget:.0%}，可考虑升级住宿或增加体验项目。",
                           item_ids=[]))

    # ---- 每天通勤摘要（距离/耗时/打车估算/区域离散度）----
    day_summaries: list[dict] = []
    centroids: list[tuple[int, float | None, float | None]] = []
    for day in sorted(trip.days_plan, key=lambda x: x.day_index):
        items = sorted(day.items, key=lambda x: x.order_index)
        commute_km = 0.0
        coords: list[tuple[float, float]] = []
        for prev, cur in zip(items, items[1:]):
            pa, pb = poi_of(prev), poi_of(cur)
            if pa and pb and None not in (pa.longitude, pa.latitude, pb.longitude, pb.latitude):
                commute_km += _haversine_km(
                    pa.longitude, pa.latitude, pb.longitude, pb.latitude
                ) * ROAD_FACTOR
        for it in items:
            p = poi_of(it)
            if p and p.longitude is not None and p.latitude is not None:
                coords.append((p.longitude, p.latitude))
        center = (
            (sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords))
            if coords else None
        )
        spread = 0.0
        if center:
            spread = max(
                (_haversine_km(center[0], center[1], lng, lat) for lng, lat in coords),
                default=0.0,
            )
        play_items = [
            it for it in items
            if (poi_of(it) is not None and poi_of(it).category in PLAY_CATEGORIES)
        ]
        day_summaries.append(dict(
            day_index=day.day_index,
            theme=day.theme,
            date=date_meta(trip.visit_date, day.day_index)[0],
            week=date_meta(trip.visit_date, day.day_index)[1],
            item_count=len(items),
            play_count=len(play_items),
            play_hours=round(sum(int(it.duration_min or 0) for it in play_items) / 60, 1),
            commute_km=round(commute_km, 1),
            commute_min=int(round(commute_km / SPEED_KMH * 60)),
            taxi_cost=int(round(8 + 2.2 * commute_km)) if commute_km > 0.05 else 0,
            spread_km=round(spread, 1),
            start_time=items[0].start_time if items else "",
            end_time=items[-1].start_time if items else "",
        ))
        centroids.append((day.day_index, center[0] if center else None, center[1] if center else None))

    # ---- 优化建议（可与「一键优化同日顺序」联动）----
    suggestions: list[dict] = []
    for ds in day_summaries:
        if ds["commute_km"] >= 25:
            suggestions.append(dict(
                title=f"Day{ds['day_index']} 通勤偏多（约 {ds['commute_km']} km / {ds['commute_min']} 分钟 / 打车约 ¥{ds['taxi_cost']}）",
                detail="建议先点「一键优化」同一天内重排；若仍偏远，可在编辑模式把该天部分点位移到相邻天。",
                action="optimize",
            ))
        elif ds["spread_km"] >= 10:
            suggestions.append(dict(
                title=f"Day{ds['day_index']} 点位较分散（最远点距当天中心约 {ds['spread_km']} km）",
                detail="可把同方向的点位归到同一天，再点「一键优化」压缩通勤。",
                action="optimize",
            ))
    # 两天区域高度重叠：提示可交换聚类
    overlap_days: list[dict] = []
    for i in range(len(centroids)):
        for j in range(i + 1, len(centroids)):
            d1, lng1, lat1 = centroids[i]
            d2, lng2, lat2 = centroids[j]
            if None in (lng1, lat1, lng2, lat2):
                continue
            dist = _haversine_km(lng1, lat1, lng2, lat2)
            if dist < 3 and day_summaries[i]["play_count"] >= 2 and day_summaries[j]["play_count"] >= 2:
                overlap_days.append((d1, d2, round(dist, 1)))
    if overlap_days:
        pairs = "、".join(f"Day{a}↔Day{b}（中心相距 {d} km）" for a, b, d in overlap_days[:2])
        suggestions.append(dict(
            title=f"部分天的活动区域重合：{pairs}",
            detail="可以点「按区域重排」把全部点位按地理位置重新分组到各天，通常能明显减少跨区折返。",
            action="redistribute",
        ))

    # 预约提醒
    trip_poi_ids = [it.poi_id for d in trip.days_plan for it in d.items if it.poi_id]
    reserved = []
    if trip_poi_ids:
        for ext in (db.query(PoiExtScenic)
                    .filter(PoiExtScenic.poi_id.in_(trip_poi_ids),
                            PoiExtScenic.need_reservation.is_(True)).all()):
            poi = db.get(Poi, ext.poi_id)
            if poi:
                reserved.append(poi.name)
    if reserved:
        suggestions.append(dict(
            title=f"{len(reserved)} 个点位需提前预约：{'、'.join(reserved[:3])}",
            detail="出发前请以景区官方渠道确认预约与开放时间。",
            action="",
        ))

    # ---- 清单化：等级景点 / 预约清单 / 逐段通勤费用 ----
    level_points: list[dict] = []
    reservations: list[dict] = []
    segments: list[dict] = []
    seen_poi: set[int] = set()
    for day in sorted(trip.days_plan, key=lambda x: x.day_index):
        items = sorted(day.items, key=lambda x: x.order_index)
        for it in items:
            poi = poi_of(it)
            if not poi or poi.id in seen_poi:
                continue
            seen_poi.add(poi.id)
            ext = db.get(PoiExtScenic, poi.id)
            level = (ext.level if ext else "") or ""
            need_res = bool(ext.need_reservation) if ext else False
            # 只把真正的 A 级/等级（5A/4A/3A…）列入"等级景点"，seed 里还有"公益场馆/古镇段"等描述值
            if level and re.match(r"^[1-5]A", level):
                level_points.append(dict(
                    poi_id=poi.id, name=poi.name, level=level,
                    need_reservation=need_res, district=poi.district or "",
                ))
            if need_res:
                reservations.append(dict(
                    poi_id=poi.id, name=poi.name, level=level,
                    open_time=poi.open_time if isinstance(poi.open_time, str) else "",
                ))
        for prev, cur in zip(items, items[1:]):
            pa, pb = poi_of(prev), poi_of(cur)
            if not pa or not pb or None in (pa.longitude, pa.latitude, pb.longitude, pb.latitude):
                continue
            direct = _haversine_km(pa.longitude, pa.latitude, pb.longitude, pb.latitude)
            dist = round(direct * ROAD_FACTOR, 1)
            segments.append(dict(
                day_index=day.day_index,
                from_name=pa.name, to_name=pb.name,
                distance_km=dist,
                duration_min=int(round(dist / SPEED_KMH * 60)),
                taxi_cost=int(round(8 + 2.2 * dist)),
            ))

    warn = sum(1 for i in issues if i["level"] == "warn")
    # 整体评级
    stars = 5 if warn == 0 else (4 if warn == 1 else (3 if warn == 2 else 2))
    total_km = round(sum(s["commute_km"] for s in day_summaries), 1)
    total_min = sum(s["commute_min"] for s in day_summaries)
    taxi_total = sum(s["taxi_cost"] for s in day_summaries)
    overall_text = (
        f"整体通勤约 {total_km} km / {total_min} 分钟（全程打车约 ¥{taxi_total}）"
        + ("，动线整体顺畅。" if warn == 0 else f"，另有 {warn} 处需要留意（见下方清单）。")
    )
    return dict(
        trip_id=trip.id,
        trip_days=trip.days,
        total_cost=trip.total_cost,
        budget=trip.budget,
        issue_count=len(issues),
        warn_count=warn,
        issues=issues,
        suggestions=suggestions,
        day_summaries=day_summaries,
        level_points=level_points,
        reservations=reservations,
        segments=segments,
        overall=dict(
            stars=stars,
            level=["", "", "二星", "三星", "四星", "五星"][stars],
            summary=overall_text,
            total_commute_km=total_km,
            total_commute_min=total_min,
            taxi_total=taxi_total,
        ),
        summary=("行程整体可行，注意例行提示即可。" if warn == 0
                 else f"发现 {warn} 个需要调整的问题，详见下方清单。"),
    )

# ---------- 路线优化：同一天内重排点位顺序，减少通勤距离 ----------

def _order_distance(db: Session, items: list[TripItem]) -> float:
    total = 0.0
    for a, b in zip(items, items[1:]):
        pa = db.get(Poi, a.poi_id) if a.poi_id else None
        pb = db.get(Poi, b.poi_id) if b.poi_id else None
        if not pa or not pb or None in (pa.longitude, pa.latitude, pb.longitude, pb.latitude):
            continue
        total += _haversine_km(pa.longitude, pa.latitude, pb.longitude, pb.latitude)
    return total


def _optimized_order(db: Session, items: list[TripItem]) -> tuple[list[TripItem], float, float]:
    """按通勤距离最小重排一组点位（≤7 点全排列，>7 点 2-opt），返回 (顺序, 前 km, 后 km)。"""
    import itertools

    if len(items) < 2:
        return items, 0.0, 0.0
    before = _order_distance(db, items)
    best_order, best_dist = items, before
    if len(items) <= 7:
        for perm in itertools.permutations(items):
            d = _order_distance(db, list(perm))
            if d < best_dist - 1e-6:
                best_dist, best_order = d, list(perm)
    else:
        improved = True
        while improved:
            improved = False
            for i in range(len(items) - 1):
                for j in range(i + 2, len(items) + 1):
                    cand = items[:i] + list(reversed(items[i:j])) + items[j:]
                    d = _order_distance(db, cand)
                    if d < best_dist - 1e-6:
                        best_dist, best_order = d, cand
                        improved = True
        items = best_order
    return best_order, before, best_dist


def optimize_route(db: Session, trip_id: str) -> dict:
    """每天内尝试所有排列（≤7 个点时全排列；更多时用 2-opt），按通勤距离最小择优。"""
    trip = _trip(db, trip_id)
    improvements: list[dict] = []
    for day in sorted(trip.days_plan, key=lambda x: x.day_index):
        items = sorted(day.items, key=lambda x: x.order_index)
        if len(items) < 3:
            continue
        best_order, before, best_dist = _optimized_order(db, items)
        for idx, it in enumerate(best_order):
            it.order_index = idx
        db.flush()
        _retime_day(db, trip, day)
        if best_dist < before - 0.05:
            improvements.append(dict(
                day_index=day.day_index, before_km=round(before, 2),
                after_km=round(best_dist, 2), saved_km=round(before - best_dist, 2),
            ))
    _recalc_cost(db, trip)
    out = _finish(db, trip)
    return {"trip": out, "improvements": improvements}


def add_item(db: Session, trip_id: str, poi_id: int, day_index: int) -> dict:
    """把外部点位（如「待计划」篮子里的收藏）排入指定天。"""
    trip = _trip(db, trip_id)
    day = _day_by_index(trip, day_index)
    poi = _poi(db, poi_id)
    if poi.category == "hotel":
        raise HTTPException(400, "住宿不能直接排入行程槽位")
    if poi.category == "food":
        items = sorted(day.items, key=lambda x: x.order_index)
        slot = "lunch" if len(items) < 2 else "dinner"
    else:
        slot = "afternoon" if len(day.items) >= 2 else "morning"
    item = TripItem(
        trip_day_id=day.id, slot_type=slot, poi_id=poi.id, start_time="",
        duration_min=int(poi.suggest_duration_min or 60),
        cost=float(poi.ticket_price or 0), order_index=len(day.items),
    )
    day.items.append(item)
    db.add(item)
    db.flush()
    _retime_day(db, trip, day)
    _recalc_cost(db, trip)
    return _finish(db, trip)


# ---------- 跨天按区域重排：KMeans 聚类 + 均衡分天 + 同日排序 ----------

def _kmeans_assign(coords: list[tuple[int, float, float]], k: int) -> dict[int, int]:
    """对 (item_id, lng, lat) 做确定性 KMeans（最远点初始化），返回 item_id → 天下标。"""
    if not coords:
        return {}
    k = max(1, min(k, len(coords)))
    centers: list[tuple[float, float]] = [(coords[0][1], coords[0][2])]
    while len(centers) < k:
        far = max(
            coords,
            key=lambda c: (min(_haversine_km(c[1], c[2], x, y) for x, y in centers), -c[0]),
        )
        centers.append((far[1], far[2]))
    assign: dict[int, int] = {}
    for _ in range(30):
        assign = {}
        for iid, lng, lat in coords:
            assign[iid] = min(
                range(k),
                key=lambda i: (_haversine_km(lng, lat, centers[i][0], centers[i][1]), i),
            )
        new_centers = []
        for i in range(k):
            members = [c for c in coords if assign[c[0]] == i]
            if members:
                new_centers.append((
                    sum(c[1] for c in members) / len(members),
                    sum(c[2] for c in members) / len(members),
                ))
            else:
                new_centers.append(centers[i])
        if new_centers == centers:
            break
        centers = new_centers
    return assign


def redistribute_days(db: Session, trip_id: str) -> dict:
    """跨天按区域重排：KMeans 把点位按地理聚类到各天，均衡数量后再按距离排序、重算时间轴。"""
    trip = _trip(db, trip_id)
    days = sorted(trip.days_plan, key=lambda x: x.day_index)
    if len(days) < 2:
        raise HTTPException(400, "只有 1 天的行程不需要跨天重排")
    all_items = [it for d in days for it in sorted(d.items, key=lambda x: x.order_index)]
    if len(all_items) < len(days) * 2:
        raise HTTPException(400, "点位太少（每天不足 2 个），跨天重排意义不大")

    # 记录重排前每天归属与通勤
    before_map = {it.id: next(d.day_index for d in days if it in d.items) for it in all_items}
    before_km = round(sum(_order_distance(db, sorted(d.items, key=lambda x: x.order_index)) for d in days), 2)

    # 只对「游玩点位」做地理聚类（餐饮跟随最近一天），避免总点位均衡但每天游玩时长失衡
    play_items: list[TripItem] = []
    other_items: list[TripItem] = []
    for it in all_items:
        poi = db.get(Poi, it.poi_id) if it.poi_id else None
        if poi and poi.category in PLAY_CATEGORIES:
            play_items.append(it)
        else:
            other_items.append(it)

    coord_by_id: dict[int, tuple[int, float, float]] = {}
    for it in all_items:
        poi = db.get(Poi, it.poi_id) if it.poi_id else None
        if poi and poi.longitude is not None and poi.latitude is not None:
            coord_by_id[it.id] = (it.id, poi.longitude, poi.latitude)

    play_coords = [coord_by_id[it.id] for it in play_items if it.id in coord_by_id]
    assign: dict[int, int] = {}
    if play_coords:
        assign.update(_kmeans_assign(play_coords, len(days)))
    # 无坐标游玩点：跟随原天
    for it in play_items:
        if it.id not in assign:
            assign[it.id] = max(0, min(len(days) - 1, before_map[it.id] - 1))

    def _day_center(g: int) -> tuple[float, float]:
        pts = [c for c in play_coords if assign.get(c[0]) == g]
        if not pts:
            return (0.0, 0.0)
        return (sum(p[1] for p in pts) / len(pts), sum(p[2] for p in pts) / len(pts))

    # 均衡每天游玩点数（kmeans 可能 4/2/3，尽量靠近均分）
    play_counts = {i: sum(1 for v in assign.values() if v == i) for i in range(len(days))}
    for _ in range(200):
        hi = max(play_counts, key=lambda i: play_counts[i])
        lo = min(play_counts, key=lambda i: play_counts[i])
        if play_counts[hi] - play_counts[lo] <= 1:
            break
        c_lo = _day_center(lo)
        big = [iid for iid, g in assign.items() if g == hi and iid in coord_by_id]
        if not big:
            break
        move = min(
            big,
            key=lambda iid: _haversine_km(
                coord_by_id[iid][1], coord_by_id[iid][2], c_lo[0], c_lo[1]
            ),
        )
        assign[move] = lo
        play_counts[hi] -= 1
        play_counts[lo] += 1

    # 餐饮/其他：跟随最近的一天中心
    for it in other_items:
        if it.id in coord_by_id:
            lng, lat = coord_by_id[it.id][1], coord_by_id[it.id][2]
            assign[it.id] = min(
                range(len(days)),
                key=lambda g: (
                    _haversine_km(lng, lat, _day_center(g)[0], _day_center(g)[1]), g,
                ),
            )
        else:
            assign[it.id] = max(0, min(len(days) - 1, before_map[it.id] - 1))

    # ---- 约束修复：保证每天游玩点位数/游玩时长不超过模式上限 ----
    rules = get_mode_cfg(db, trip.mode).hard_rules or {}
    max_play = int(rules.get("daily_poi_max") or 99)
    max_hours = float(rules.get("daily_play_hours_max") or 24)
    meta: dict[int, tuple[int, bool]] = {}
    for it in all_items:
        poi = db.get(Poi, it.poi_id) if it.poi_id else None
        meta[it.id] = (int(it.duration_min or 0), bool(poi and poi.category in PLAY_CATEGORIES))
    members: dict[int, list[int]] = {i: [] for i in range(len(days))}
    for iid, g in assign.items():
        members.setdefault(g, []).append(iid)
    play_count = {i: sum(1 for iid in members[i] if meta[iid][1]) for i in members}
    play_hours = {i: sum(meta[iid][0] for iid in members[i] if meta[iid][1]) / 60 for i in members}

    def _center(group: int) -> tuple[float, float]:
        pts = [coord_by_id[iid] for iid in members[group] if iid in coord_by_id]
        if not pts:
            return (0.0, 0.0)
        return (sum(p[1] for p in pts) / len(pts), sum(p[2] for p in pts) / len(pts))

    centers = {i: _center(i) for i in members}

    for _ in range(300):
        over = [i for i in members
                if play_count[i] > max_play or play_hours[i] > max_hours + 0.01]
        if not over:
            break
        donor = max(over, key=lambda i: (play_count[i] - max_play, play_hours[i] - max_hours))
        movable = [iid for iid in members[donor] if meta[iid][1] and iid in coord_by_id]
        if not movable:
            break
        options: list[tuple[float, int, int]] = []
        for iid in movable:
            dur_h = meta[iid][0] / 60
            for rid in members:
                if rid == donor:
                    continue
                if play_count[rid] + 1 > max_play or play_hours[rid] + dur_h > max_hours + 0.01:
                    continue
                dist = _haversine_km(
                    coord_by_id[iid][1], coord_by_id[iid][2],
                    centers[rid][0], centers[rid][1],
                )
                options.append((dist, iid, rid))
        if options:
            _, iid, rid = min(options, key=lambda x: (x[0], x[1], x[2]))
        else:
            # 没有严格容量的接收天：搬到当前最空的一天，允许轻微超限
            rid = min((i for i in members if i != donor),
                      key=lambda i: (play_count[i], play_hours[i]))
            iid = min(
                movable,
                key=lambda x: _haversine_km(
                    coord_by_id[x][1], coord_by_id[x][2],
                    centers[rid][0], centers[rid][1],
                ),
            )
        members[donor].remove(iid)
        members[rid].append(iid)
        assign[iid] = rid
        play_count[donor] -= 1
        play_count[rid] += 1
        dur_h = meta[iid][0] / 60
        play_hours[donor] -= dur_h
        play_hours[rid] += dur_h
        centers[donor] = _center(donor)
        centers[rid] = _center(rid)

    # 写入新分组
    new_lists: dict[int, list[TripItem]] = {d.day_index: [] for d in days}
    for it in all_items:
        dno = days[assign.get(it.id, before_map[it.id] - 1)].day_index
        new_lists[dno].append(it)
    for d in days:
        d.items = new_lists[d.day_index]

    # ---- 后置约束修复（基于最终分组再做一次，确保模式上限不被突破）----
    def _play_items(day: TripDay) -> list[TripItem]:
        out = []
        for it in day.items:
            poi = db.get(Poi, it.poi_id) if it.poi_id else None
            if poi and poi.category in PLAY_CATEGORIES:
                out.append(it)
        return out

    for _ in range(300):
        counts = {d.day_index: len(_play_items(d)) for d in days}
        hours = {d.day_index: sum(int(it.duration_min or 0) for it in _play_items(d)) / 60 for d in days}
        over = [d for d in days
                if counts[d.day_index] > max_play or hours[d.day_index] > max_hours + 0.01]
        if not over:
            break
        donor = max(over, key=lambda d: (counts[d.day_index] - max_play, hours[d.day_index] - max_hours))
        donor_play = _play_items(donor)
        if not donor_play:
            break
        moved = False
        for it in sorted(donor_play, key=lambda x: x.order_index):
            poi = db.get(Poi, it.poi_id)
            dur_h = int(it.duration_min or 0) / 60
            for target in days:
                if target.id == donor.id:
                    continue
                if counts[target.day_index] + 1 > max_play or hours[target.day_index] + dur_h > max_hours + 0.01:
                    continue
                target_play = _play_items(target)
                if target_play:
                    pl = [db.get(Poi, x.poi_id) for x in target_play if x.poi_id]
                    pl = [p for p in pl if p and p.longitude is not None]
                    if pl:
                        c = (sum(p.longitude for p in pl) / len(pl), sum(p.latitude for p in pl) / len(pl))
                        # 只搬到离目标天更近的点
                        if _haversine_km(poi.longitude, poi.latitude, c[0], c[1]) > 12:
                            continue
                donor.items.remove(it)
                target.items.append(it)
                it.trip_day_id = target.id
                moved = True
                break
            if moved:
                break
        if not moved:
            # 无法直接搬点时，尝试交换两天各一个游玩点（交换不改变点位数，只调时长）
            best_swap = None
            donor_play = _play_items(donor)
            for it in donor_play:
                d_it = int(it.duration_min or 0) / 60
                p_it = db.get(Poi, it.poi_id) if it.poi_id else None
                if not p_it or p_it.longitude is None:
                    continue
                for other in days:
                    if other.id == donor.id:
                        continue
                    other_play = _play_items(other)
                    if not other_play:
                        continue
                    pts = [db.get(Poi, x.poi_id) for x in other_play if x.poi_id]
                    pts = [p for p in pts if p and p.longitude is not None]
                    c_other = (
                        (sum(p.longitude for p in pts) / len(pts), sum(p.latitude for p in pts) / len(pts))
                        if pts else (0.0, 0.0)
                    )
                    for jt in other_play:
                        d_jt = int(jt.duration_min or 0) / 60
                        if hours[donor.day_index] - d_it + d_jt > max_hours + 0.01:
                            continue
                        if hours[other.day_index] - d_jt + d_it > max_hours + 0.01:
                            continue
                        p_jt = db.get(Poi, jt.poi_id) if jt.poi_id else None
                        if not p_jt or p_jt.longitude is None:
                            continue
                        # 交换代价：两个点各自离对方团的中心距离
                        cost = _haversine_km(
                            p_it.longitude, p_it.latitude, c_other[0], c_other[1]
                        )
                        donor_pts = [db.get(Poi, x.poi_id) for x in donor_play if x.poi_id]
                        donor_pts = [p for p in donor_pts if p and p.longitude is not None]
                        c_donor = (
                            (sum(p.longitude for p in donor_pts) / len(donor_pts),
                             sum(p.latitude for p in donor_pts) / len(donor_pts))
                            if donor_pts else (0.0, 0.0)
                        )
                        cost += _haversine_km(p_jt.longitude, p_jt.latitude, c_donor[0], c_donor[1])
                        if best_swap is None or cost < best_swap[0]:
                            best_swap = (cost, it, jt)
            if best_swap:
                _, it, jt = best_swap
                other_day = next(d for d in days if jt in d.items)
                donor.items.remove(it)
                other_day.items.remove(jt)
                donor.items.append(jt)
                other_day.items.append(it)
                it.trip_day_id = other_day.id
                jt.trip_day_id = donor.id
                moved = True
        if not moved:
            break

    changes: list[dict] = []
    for d in days:
        moved_in = [it for it in d.items if before_map.get(it.id) != d.day_index]
        moved_out = [it for it in all_items if before_map.get(it.id) == d.day_index and assign.get(it.id) != d.day_index - 1]
        # 用新归属重新判断移出
        moved_out = [
            it for it in all_items
            if before_map.get(it.id) == d.day_index
            and assign.get(it.id, before_map[it.id] - 1) != d.day_index - 1
        ]
        names = []
        for it in (moved_in + moved_out)[:6]:
            poi = db.get(Poi, it.poi_id) if it.poi_id else None
            if poi:
                names.append(poi.name)
        if moved_in or moved_out:
            changes.append(dict(
                day_index=d.day_index,
                moved_in=[(db.get(Poi, it.poi_id).name if it.poi_id and db.get(Poi, it.poi_id) else "")
                          for it in moved_in[:5]],
                moved_out_count=len(moved_out),
                moved_in_count=len(moved_in),
                sample=names,
            ))

    # 每天：按距离排序、分配槽位、写主题
    for d in days:
        items = [it for it in d.items]
        ordered, _, _ = _optimized_order(db, items)
        n = len(ordered)
        food_idx = play_idx = 0
        play_total = sum(
            1 for it in ordered
            if it.poi_id and (db.get(Poi, it.poi_id) and db.get(Poi, it.poi_id).category in PLAY_CATEGORIES)
        )
        for idx, it in enumerate(ordered):
            poi = db.get(Poi, it.poi_id) if it.poi_id else None
            if poi and poi.category == "food":
                it.slot_type = "lunch" if idx < n / 2 else "dinner"
                food_idx += 1
            else:
                if play_total <= 1:
                    it.slot_type = "morning"
                else:
                    ratio = play_idx / play_total
                    it.slot_type = "morning" if ratio < 0.34 else ("afternoon" if ratio < 0.7 else "evening")
                play_idx += 1
            it.order_index = idx
        # 主题：当天第一个游玩点
        first_play = next(
            (db.get(Poi, it.poi_id) for it in ordered
             if it.poi_id and db.get(Poi, it.poi_id) and db.get(Poi, it.poi_id).category in PLAY_CATEGORIES),
            None,
        )
        if first_play:
            d.theme = first_play.name[:12] + "线"
        _retime_day(db, trip, d)

    db.flush()
    _recalc_cost(db, trip)
    after_km = round(sum(_order_distance(db, sorted(d.items, key=lambda x: x.order_index)) for d in days), 2)
    out = _finish(db, trip)
    return dict(
        trip=out,
        changes=changes,
        improvements=dict(
            before_total_km=before_km,
            after_total_km=after_km,
            saved_km=round(before_km - after_km, 2),
        ),
    )
