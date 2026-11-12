"""Stage4 日内路线排序：最近邻 + 2-opt（方案 5.5）。

- 酒店位置作为每日首尾锚；
- 游玩 POI 分槽位组（上午/下午/晚间）就近排序，组间以用餐点为锚；
- 时间轴按槽位窗口对齐（午餐不早于饭点、晚餐不早于 18:00 等）。
"""
from app.planner.models import DayPlan, PlannerPoi, SlotItem
from app.planner.scoring import estimate_travel_min

PLAY_SLOTS = ("morning", "afternoon", "evening")

# 各槽位最早开始时间（HH:MM），低于此时间则顺延对齐
SLOT_MIN_START = {
    "morning": None,   # 按模式 day_start
    "lunch": "11:30",
    "afternoon": None,  # 午餐后自然衔接
    "dinner": "18:00",
    "evening": "19:00",
}


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _mh(v: int) -> str:
    return f"{v // 60:02d}:{v % 60:02d}"


def _nn_2opt(items: list[SlotItem], anchor: PlannerPoi | None, speed: float) -> None:
    """对一组游玩 SlotItem 整体重排（最近邻 + 2-opt），保持 poi/时长/费用绑定。"""
    if len(items) < 2:
        return
    # 最近邻
    cur = anchor or items[0].poi
    remaining = [it for it in items if it.poi is not cur] if anchor else items[1:]
    ordered = [items[0]] if not anchor else []
    if not anchor:
        ordered = [items[0]]
        remaining = items[1:]
        cur = items[0].poi
    while remaining:
        nxt = min(remaining, key=lambda it: estimate_travel_min(cur, it.poi, speed))
        ordered.append(nxt)
        # 按对象身份移除（SlotItem 按字段相等会误删同类项）
        for i, r in enumerate(remaining):
            if r is nxt:
                del remaining[i]
                break
        cur = nxt.poi

    def _route_cost(seq: list[SlotItem]) -> float:
        total = estimate_travel_min(anchor, seq[0].poi, speed) if anchor else 0.0
        for a, b in zip(seq, seq[1:]):
            total += estimate_travel_min(a.poi, b.poi, speed)
        return total

    # 2-opt 区间反转
    improved, guard = True, 0
    while improved and guard < 30:
        improved = False
        guard += 1
        for i in range(len(ordered) - 1):
            for j in range(i + 1, len(ordered)):
                cand = ordered[:i] + ordered[i:j + 1][::-1] + ordered[j + 1:]
                if _route_cost(cand) < _route_cost(ordered) - 1e-6:
                    ordered = cand
                    improved = True

    # 先快照排好的内容，再写回原槽位（items 与 ordered 引用同一批对象，
    # 直接边读边写会造成别名污染：A.poi=B.poi 执行后 B.poi 已被覆盖）
    snapshot = [(it.poi, it.duration_min, it.cost) for it in ordered]
    for old, (poi, dur, cost) in zip(items, snapshot):
        old.poi, old.duration_min, old.cost = poi, dur, cost


def order_day_items(
    day: DayPlan,
    hotel: PlannerPoi | None,
    speed_kmh: float,
    day_start: str,
    day_end: str,
    lunch_start: str = "11:30",
    dinner_start: str = "18:00",
    evening_start: str = "19:00",
) -> None:
    """日内排序 + 时间轴重算。"""
    groups: dict[str, list[SlotItem]] = {s: [] for s in PLAY_SLOTS}
    for it in day.items:
        if it.poi is not None and it.slot in groups:
            groups[it.slot].append(it)

    # 分组就近排序：morning 从酒店出发；afternoon 从午餐地出发；evening 从晚餐地出发
    lunch_poi = next((it.poi for it in day.items if it.slot == "lunch" and it.poi), None)
    dinner_poi = next((it.poi for it in day.items if it.slot == "dinner" and it.poi), None)

    def _sort_free(items: list[SlotItem], anchor: PlannerPoi | None) -> None:
        """只重排普通点位；游学保底站（locked）保持专家编排的 seq 顺序。"""
        free = [it for it in items if not it.locked]
        _nn_2opt(free, anchor, speed_kmh)

    _sort_free(groups["morning"], hotel)
    _sort_free(groups["afternoon"], lunch_poi)
    _sort_free(groups["evening"], dinner_poi)

    _recalc_times(day, hotel, speed_kmh, day_start, day_end,
                  lunch_start, dinner_start, evening_start)


def _recalc_times(
    day: DayPlan,
    hotel: PlannerPoi | None,
    speed_kmh: float,
    day_start: str,
    day_end: str,
    lunch_start: str = "11:30",
    dinner_start: str = "18:00",
    evening_start: str = "19:00",
) -> None:
    """按槽位顺序推进时间轴，并对齐槽位最早开始时间。

    超时的条目（在 day_end 前无法完成）置空并重新收紧时间轴，直至稳定。
    """
    for _round in range(5):
        dropped = False
        cur = _hm(day_start)
        end = _hm(day_end)
        prev = hotel
        for it in day.items:
            if it.poi is None:
                continue
            # 游学线校内站点用预置的实测步行时长，不走 Haversine / 外部路径 API（5.8 第 5 条）
            travel = (
                it.travel_override_min if it.travel_override_min is not None
                else (estimate_travel_min(prev, it.poi, speed_kmh) if prev else 0)
            )
            start = cur + travel
            floor = {"lunch": _hm(lunch_start), "dinner": _hm(dinner_start),
                     "evening": _hm(evening_start)}.get(it.slot)
            if floor is not None and start < floor:
                start = floor  # 顺延到槽位窗口（如晚餐 18:00 后）
            grace = 60 if it.slot in ("lunch", "dinner") else 0
            if start + it.duration_min > end + grace:
                if it.locked:
                    # 保底动线绝不置空：压缩停留至可用时间窗（最少 10 分钟）
                    it.duration_min = max(10, end + grace - start)
                else:
                    # 时间窗内无法完成：置空该条目（数量下限由 relax 层兜底）
                    it.poi = None
                    it.duration_min = 0
                    it.cost = 0.0
                    dropped = True
                    continue
            it.travel_from_prev_min = start - cur
            it.start_time = _mh(start)
            cur = start + it.duration_min
            prev = it.poi
        if not dropped:
            break
    day.day_cost = sum(it.cost for it in day.items)
