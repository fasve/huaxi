"""对话式行程编辑：自然语言 → 结构化 ops → 确定性执行 → 重算时间轴。

设计原则：大模型只负责"把话翻译成 ops"（或由本地规则兜底），
所有真正改动都由本模块确定性执行，时间/费用全部重算，避免模型编造行程。
"""
from __future__ import annotations

import json
import logging
import re

from app.models import Poi, Trip, TripDay, TripItem
from app.services import llm_client, trip_edit, trip_service

log = logging.getLogger("travel.trip_edit_chat")

VALID_MODES = ("walking", "riding", "taxi", "driving", "transit")
MODE_NAMES = {
    "walking": "步行", "riding": "骑行", "taxi": "打车",
    "driving": "驾车", "transit": "公共交通",
}

_SYSTEM = """你是行程编辑指令解析器。用户在编辑一份已生成的旅游行程。
你会收到行程 JSON 与用户这句话，请把它翻译成严格 JSON（不要 markdown 代码块）：
{"ops": [...], "reply": "一句中文说明"}

可用操作：
1. {"op":"set_transport","day":1,"leg_index":1,"mode":"riding"}
   leg_index 为该点在其所在天 items 数组中的下标（从 0 开始，表示从前一个点到该点的交通方式）
2. {"op":"set_day_start","day":1,"start_time":"08:00"}
3. {"op":"remove_poi","name":"点位名"}
4. {"op":"add_poi","day":1,"name":"点位名"}
5. {"op":"add_meal","day":1}
6. {"op":"move_poi","name":"点位名","target_day":2}
7. {"op":"regenerate_day","day":1}

规则：
- 只输出 JSON，不要解释；
- 用户说"最后一段改成骑行"：找到最后一天的最后一个 leg（items 下标 = 长度-1）；
- 用户说"8点出发"：set_day_start 对应天；
- 用户提到行程里没有的地点，不要编造，放到 reply 里说明"行程里没有找到该点位"；
- 不确定时 ops 为空数组，reply 用一句话反问。"""

_HEURISTIC_MODE = re.compile(r"(步行|走路|骑行|骑车|打车|驾车|开车|公交|地铁)")
_RE_TIME = re.compile(r"(?:(\d{1,2})[:：点](\d{2})?|(\d{1,2})\s*点).{0,4}?(?:出发|开始)")
_RE_DELETE = re.compile(r"(?:删除|删掉|去掉|移除|不要)\s*[「\"']?([\u4e00-\u9fa5A-Za-z0-9()（）·\-]{2,20})[」\"']?")
_RE_ADD = re.compile(r"(?:加上|增加|添加|加个|加一个|加入)\s*[「\"']?([\u4e00-\u9fa5A-Za-z0-9()（）·\-]{2,20})[」\"']?")
_RE_MOVE = re.compile(r"(?:把|将)?\s*[「\"']?([\u4e00-\u9fa5A-Za-z0-9()（）·\-]{2,20})[」\"']?\s*(?:移动|挪|换)\s*(?:到|至)\s*(?:第\s*)?([1-7一二三四五六七])\s*天")


def _day_no(s: str) -> int:
    return {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}.get(s, int(s) if s.isdigit() else 1)


def _trip_ctx_placeholder() -> None:  # pragma: no cover - 保留占位，实际使用 _build_ctx
    return None


def _build_ctx(db: Session, trip: Trip) -> dict:
    days = []
    for d in sorted(trip.days_plan, key=lambda x: x.day_index):
        items = []
        for idx, it in enumerate(sorted(d.items, key=lambda x: x.order_index)):
            poi = db.get(Poi, it.poi_id) if it.poi_id else None
            items.append({
                "index": idx,
                "name": poi.name if poi else "",
                "time": it.start_time,
                "category": poi.category if poi else "",
                "transport_from_prev": it.transport_mode or "",
            })
        days.append({"day": d.day_index, "items": items})
    return {"days": days}


def _find_item(db: Session, trip: Trip, name: str) -> tuple[TripDay, TripItem] | None:
    """按名称在行程中查找点位（包含匹配）。"""
    key = (name or "").strip()
    if not key:
        return None
    for d in sorted(trip.days_plan, key=lambda x: x.day_index):
        for it in sorted(d.items, key=lambda x: x.order_index):
            poi = db.get(Poi, it.poi_id) if it.poi_id else None
            if poi and (key in poi.name or poi.name in key):
                return d, it
    return None


def _find_poi(db: Session, name: str, categories: tuple[str, ...] | None = None) -> Poi | None:
    key = (name or "").strip()
    if not key:
        return None
    q = db.query(Poi)
    if categories:
        q = q.filter(Poi.category.in_(categories))
    exact = q.filter(Poi.name == key).first()
    if exact:
        return exact
    return (q.filter(Poi.name.like(f"%{key}%"))
            .order_by(Poi.rating.desc().nullslast() if hasattr(Poi.rating, "desc") else Poi.id)
            .first())


# ---------- ops 解析 ----------

def _parse_ops_llm(db: Session, trip: Trip, text: str) -> list[dict] | None:
    if not llm_client.configured():
        return None
    ctx = _build_ctx(db, trip)
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"行程 JSON：\n{json.dumps(ctx, ensure_ascii=False)}\n\n用户：{text}"},
    ]
    try:
        out = llm_client.chat(messages, temperature=0.1, max_tokens=600)
    except llm_client.LlmError as exc:
        log.warning("[chat-edit] LLM 解析失败 %s: %s", exc.code, exc.message)
        return None
    raw = (out.get("answer") or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return None
    ops = data.get("ops")
    return ops if isinstance(ops, list) else None


def _parse_ops_heuristic(db: Session, trip: Trip, text: str) -> list[dict]:
    """本地兜底：覆盖"改骑行/删X/加X/几点出发/把X移到第2天"等高频表达。"""
    ops: list[dict] = []
    t = (text or "").strip()
    day_match = re.search(r"第\s*([1-7一二三四五六七两])\s*天|day\s*([1-7])", t, re.I)
    day = _day_no((day_match.group(1) or day_match.group(2))) if day_match else 1

    # 交通方式
    mode_m = _HEURISTIC_MODE.search(t)
    if mode_m and ("改" in t or "换" in t or "走" in t or "用" in t or "建议" in t or "吧" in t):
        mode_map = {"步行": "walking", "走路": "walking", "骑行": "riding", "骑车": "riding",
                    "打车": "taxi", "驾车": "driving", "开车": "driving", "公交": "transit", "地铁": "transit"}
        mode = mode_map.get(mode_m.group(1), "walking")
        day_obj = next((d for d in trip.days_plan if d.day_index == day), None)
        if day_obj:
            items = sorted(day_obj.items, key=lambda x: x.order_index)
            if len(items) >= 2:
                ops.append({"op": "set_transport", "day": day, "leg_index": len(items) - 1, "mode": mode})

    # 出发时间
    tm = _RE_TIME.search(t)
    if tm:
        if tm.group(1):
            hh, mm = int(tm.group(1)), int(tm.group(2) or 0)
        else:
            hh, mm = int(tm.group(3)), 0
        if 0 <= hh <= 23:
            ops.append({"op": "set_day_start", "day": day, "start_time": f"{hh:02d}:{mm:02d}"})

    # 移动
    mv = _RE_MOVE.search(t)
    if mv:
        ops.append({"op": "move_poi", "name": mv.group(1), "target_day": _day_no(mv.group(2))})

    # 删除
    if "删" in t or "去掉" in t or "移除" in t or "不要" in t:
        dm = _RE_DELETE.search(t)
        if dm:
            ops.append({"op": "remove_poi", "name": dm.group(1)})

    # 添加（美食关键词 → add_meal）
    am = _RE_ADD.search(t)
    if am:
        if "美食" in t:
            ops.append({"op": "add_meal", "day": day})
        else:
            ops.append({"op": "add_poi", "day": day, "name": am.group(1)})
    return ops


def _parse_ops(db: Session, trip: Trip, text: str) -> list[dict]:
    return _parse_ops_llm(db, trip, text) or _parse_ops_heuristic(db, trip, text)


# ---------- 执行 ----------

def _apply_ops(db: Session, trip: Trip, ops: list[dict]) -> tuple[list[str], set[int]]:
    changes: list[str] = []
    touched_days: set[int] = set()

    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        try:
            if kind == "set_transport":
                day_no = int(op.get("day") or 1)
                day = next((d for d in trip.days_plan if d.day_index == day_no), None)
                if not day:
                    continue
                items = sorted(day.items, key=lambda x: x.order_index)
                idx = int(op.get("leg_index") or 0)
                mode = str(op.get("mode") or "")
                if mode not in VALID_MODES or not (0 <= idx < len(items)):
                    continue
                items[idx].transport_mode = mode
                touched_days.add(day_no)
                poi = db.get(Poi, items[idx].poi_id) if items[idx].poi_id else None
                changes.append(
                    f"Day{day_no} 前往「{poi.name if poi else '该点位'}」改为{MODE_NAMES.get(mode, mode)}"
                )

            elif kind == "set_day_start":
                day_no = int(op.get("day") or 1)
                day = next((d for d in trip.days_plan if d.day_index == day_no), None)
                if not day:
                    continue
                sm = re.match(r"^(\d{1,2}):(\d{2})$", str(op.get("start_time") or ""))
                if not sm:
                    continue
                start_min = int(sm.group(1)) * 60 + int(sm.group(2))
                items = sorted(day.items, key=lambda x: x.order_index)
                prev = None
                cursor = start_min
                for it in items:
                    if prev is not None:
                        cursor += trip_edit._travel_minutes(db, prev, it)
                    it.start_time = trip_edit._fmt_hhmm(cursor)
                    cursor += int(it.duration_min or 60)
                    prev = it
                changes.append(f"Day{day_no} 改为 {op.get('start_time')} 出发")
                # 已在此处理，避免再统一 retime
                touched_days.discard(day_no)

            elif kind == "remove_poi":
                found = _find_item(db, trip, str(op.get("name") or ""))
                if not found:
                    continue
                day, item = found
                day.items.remove(item)
                db.delete(item)
                db.flush()
                trip_edit._renumber(day)
                touched_days.add(day.day_index)
                changes.append(f"已删除「{(db.get(Poi, item.poi_id).name if item.poi_id else '')}」")

            elif kind == "add_poi":
                day_no = int(op.get("day") or 1)
                day = next((d for d in trip.days_plan if d.day_index == day_no), None)
                poi = _find_poi(db, str(op.get("name") or ""))
                if not day or not poi:
                    continue
                existing = {it.poi_id for it in day.items}
                if poi.id in existing:
                    continue
                item = TripItem(
                    trip_day_id=day.id, slot_type="spot", poi_id=poi.id,
                    start_time="", duration_min=poi.suggest_duration_min or 60,
                    cost=float(poi.ticket_price or 0), order_index=len(day.items),
                )
                day.items.append(item)
                db.add(item)
                db.flush()
                touched_days.add(day_no)
                changes.append(f"Day{day_no} 已加入「{poi.name}」")

            elif kind == "add_meal":
                day_no = int(op.get("day") or 1)
                day = next((d for d in trip.days_plan if d.day_index == day_no), None)
                if not day:
                    continue
                items = sorted(day.items, key=lambda x: x.order_index)
                anchor = items[-1] if items else None
                anchor_poi = db.get(Poi, anchor.poi_id) if anchor and anchor.poi_id else None
                used = {it.poi_id for d in trip.days_plan for it in d.items}
                q = db.query(Poi).filter(Poi.category == "food")
                if used:
                    q = q.filter(~Poi.id.in_(used))
                meals = q.order_by(Poi.rating.desc()).limit(30).all()
                if not meals:
                    continue
                def dist(p: Poi) -> float:
                    if not anchor_poi or None in (p.longitude, p.latitude):
                        return 999.0
                    return trip_edit._haversine_km(
                        p.longitude, p.latitude, anchor_poi.longitude, anchor_poi.latitude
                    )
                meal = min(meals, key=dist)
                item = TripItem(
                    trip_day_id=day.id, slot_type="dinner", poi_id=meal.id,
                    start_time="", duration_min=meal.suggest_duration_min or 60,
                    cost=float(meal.ticket_price or 40), order_index=len(day.items),
                )
                day.items.append(item)
                db.add(item)
                db.flush()
                touched_days.add(day_no)
                changes.append(f"Day{day_no} 已加入当地美食「{meal.name}」")

            elif kind == "move_poi":
                found = _find_item(db, trip, str(op.get("name") or ""))
                target_day = int(op.get("target_day") or 1)
                dst = next((d for d in trip.days_plan if d.day_index == target_day), None)
                if not found or not dst or found[0].id == dst.id:
                    continue
                src_day, item = found
                src_day.items.remove(item)
                dst.items.append(item)
                item.trip_day_id = dst.id
                db.flush()
                trip_edit._renumber(src_day)
                item.order_index = len(dst.items) - 1
                touched_days.update({src_day.day_index, target_day})
                changes.append(f"已把「{item.poi_id and db.get(Poi, item.poi_id).name}」移到 Day{target_day}")

            elif kind == "regenerate_day":
                day_no = int(op.get("day") or 1)
                day = next((d for d in trip.days_plan if d.day_index == day_no), None)
                if not day:
                    continue
                touched_days.add(day_no)
                changes.append(f"Day{day_no} 将重新安排")
                # 由调用方在改动后统一重排；这里仅标记，避免 rebalance 内部再提交
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("[chat-edit] 跳过非法 op %s: %s", op, exc)

    return changes, touched_days


def chat_edit(db: Session, trip_id: str, text: str) -> dict:
    trip = trip_edit._trip(db, trip_id)
    ops = _parse_ops(db, trip, text)
    if not ops:
        return {
            "trip": trip_service.trip_to_out(db, trip),
            "reply": "我没听清要改哪里～可以说「最后一段改成骑行」「8点出发」「删掉XXX」「加个当地美食」这类话试试。",
            "changes": [],
            "ops": [],
        }

    changes, touched_days = _apply_ops(db, trip, ops)
    db.flush()
    for d in trip.days_plan:
        if d.day_index in touched_days:
            trip_edit._retime_day(db, trip, d)
    trip_edit._recalc_cost(db, trip)
    db.commit()
    db.refresh(trip)
    out = trip_service.trip_to_out(db, trip)
    if changes:
        reply = f"好的，已按你的要求更新行程（{len(changes)} 处改动）。"
    else:
        reply = "这次没改到行程，换个说法再试？"
    return {"trip": out, "reply": reply, "changes": changes, "ops": ops}
