"""合规版「智能解析」：用户粘贴攻略文本 → 提取地点 → 匹配本站 POI → 生成行程。

不抓取任何外部链接/网页；只处理用户主动粘贴的文本。
大模型负责"提取地名 + 判断天数"，匹配与排程全部由本地数据与确定性逻辑完成。
"""
from __future__ import annotations

import json
import logging
import math
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Poi, Trip, TripDay, TripItem
from app.services import llm_client, trip_edit, trip_service

log = logging.getLogger("travel.guide_parse")

_EXTRACT_SYSTEM = """你是旅游攻略解析器。用户会粘贴一段攻略文本，请：
1. 按文中出现顺序提取所有"可游玩/可吃饭的地点"名称（景点、公园、古镇、餐厅、小吃店、商圈；不要提取酒店、车站、城市名）；
2. 推断这份攻略适合的天数（1~7 的整数）。
只输出严格 JSON，不要 markdown 代码块：
{"places": ["名称1", "名称2"], "days": 2}
不要解释，不要编造文本里没有的地点。"""


def _normalize(name: str) -> str:
    s = str(name or "").strip()
    s = re.sub(r"[（(].*?[)）]", "", s)
    s = re.sub(r"[\s·、，,。.!！?？:：;；\"'“”‘’《》<>]", "", s)
    return s


def _extract_places_llm(text: str) -> tuple[list[str], int | None] | None:
    if not llm_client.configured():
        return None
    try:
        out = llm_client.chat(
            [{"role": "system", "content": _EXTRACT_SYSTEM},
             {"role": "user", "content": text[:4000]}],
            temperature=0.1, max_tokens=800,
        )
    except llm_client.LlmError as exc:
        log.warning("[guide] LLM 提取失败 %s: %s", exc.code, exc.message)
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
    places = [str(p).strip() for p in (data.get("places") or []) if str(p).strip()]
    days = data.get("days")
    try:
        days = int(days) if days is not None else None
    except (TypeError, ValueError):
        days = None
    if days is not None:
        days = max(1, min(7, days))
    return places, days


def _extract_places_heuristic(text: str) -> list[str]:
    """兜底：按行/顿号/箭头切分，去时间词与常见客套词。"""
    parts = re.split(r"[\n\r；;。]+|→|->|—>", text)
    out: list[str] = []
    for p in parts:
        p = re.sub(r"^(Day\s*\d+|第[一二三四五六七\d]+天|上午|中午|下午|晚上|早上|傍晚)[:：\s]*", "", p.strip(), flags=re.I)
        p = re.sub(r"^\d{1,2}[:：]\d{2}\s*[-~至]\s*\d{1,2}[:：]\d{2}\s*", "", p)
        p = re.split(r"[，,、]|去|到|逛|吃|玩|游|前往|然后|接着", p)[0].strip()
        if 2 <= len(p) <= 20:
            out.append(p)
    return out[:20]


def _match_poi(db: Session, name: str) -> Poi | None:
    norm = _normalize(name)
    if not norm:
        return None

    # 依次尝试：完整名 → 去掉"花溪/贵阳/贵州"前缀 → 前 12 字 → 前 6/5 字（合并候选集）
    keys = [norm[:12]]
    for prefix in ("花溪", "贵阳", "贵州"):
        if norm.startswith(prefix) and len(norm) > len(prefix) + 1:
            keys.append(norm[len(prefix):][:12])
            break
    keys.append(norm[:6])
    if len(norm) >= 5:
        keys.append(norm[:5])
    if len(norm) >= 4:
        keys.append(norm[:4])
    if len(norm) >= 3:
        keys.append(norm[:3])
    rows: dict[int, Poi] = {}
    for key in keys:
        if len(key) < 2:
            continue
        for p in db.query(Poi).filter(Poi.name.like(f"%{key}%")).limit(50):
            rows[p.id] = p
    if not rows:
        return None
    candidates = list(rows.values())

    # 优先"有评分人数"的种子/已验证数据，避免匹配到同名子点位或未核实长尾
    reviewed = [p for p in candidates if (p.review_count or 0) > 0]
    pool = reviewed or candidates

    def score(p: Poi) -> float:
        pn = _normalize(p.name)
        overlap = len(set(norm) & set(pn)) / max(1, len(set(norm)))
        exact = 1.0 if pn == norm else 0.0
        length_pen = abs(len(pn) - len(norm)) * 0.12
        return overlap * 2 + exact * 1.5 - length_pen + float(p.rating or 0) * 0.05

    return max(pool, key=score)


def _base_name(name: str) -> str:
    """去掉 "·"、"-"、括号后的子点位后缀，用于同景区去重。"""
    return _normalize(re.split(r"[·\-—]", str(name or ""))[0])[:10]


def _scan_known_pois(db: Session, text: str) -> list[Poi]:
    """在完整文本里按出现位置扫描库内 POI 名称（本地兜底，不依赖大模型）。

    只取长度 ≥3 的名字，避免「青岩」「花溪」这类短词把半个文本都点亮；
    结果按在原文中的位置排序，保证行程顺序与攻略叙述一致。
    """
    hits: list[tuple[int, Poi]] = []
    seen: set[int] = set()
    for p in db.query(Poi).filter(Poi.visitable.is_(True)).all():
        name = _normalize(p.name)
        for cand in {name, _base_name(p.name)}:
            if len(cand) < 3:
                continue
            pos = text.find(cand)
            if pos >= 0 and p.id not in seen:
                seen.add(p.id)
                hits.append((pos, p))
                break
    hits.sort(key=lambda x: x[0])
    return [p for _, p in hits]


def _slot_for(poi: Poi, idx: int, total: int) -> str:
    if poi.category == "food":
        return "lunch" if idx < max(1, total / 2) else "dinner"
    if poi.category == "leisure":
        return "afternoon" if idx < total else "evening"
    ratio = idx / max(1, total)
    return "morning" if ratio < 0.34 else ("afternoon" if ratio < 0.7 else "evening")


def parse_guide(
    db: Session, text: str, *, start_date: str | None = None,
    mode: str = "leisure", budget: float | None = None,
    conversation_id: str | None = None, user_id: int | None = None,
) -> dict:
    text = (text or "").strip()
    if len(text) < 10:
        raise HTTPException(422, "攻略文本太短，至少粘贴 10 个字")
    if len(text) > 6000:
        raise HTTPException(422, "攻略文本过长，请截取 6000 字以内")

    llm_res = _extract_places_llm(text)
    if llm_res:
        raw_places, llm_days = llm_res
    else:
        raw_places, llm_days = _extract_places_heuristic(text), None
    raw_places = [p for p in raw_places if p][:24]
    if not raw_places:
        raise HTTPException(422, "没有从文本中识别到地点，请换一段攻略试试")

    matched: list[Poi] = []
    unmatched: list[str] = []
    seen: set[int] = set()
    seen_base: set[str] = set()
    for name in raw_places:
        poi = _match_poi(db, name)
        if poi and poi.id not in seen:
            base = _base_name(poi.name)
            if base and base in seen_base:
                continue
            seen.add(poi.id)
            if base:
                seen_base.add(base)
            matched.append(poi)
        elif not poi:
            unmatched.append(name)

    # 本地兜底：把整段文本拿去和库内 POI 名称做子串扫描（不依赖模型），
    # 弥补启发式切句把「上午去青岩古镇」整句当地点名导致的漏匹配。
    if len(matched) < 2:
        for poi in _scan_known_pois(db, text):
            if poi.id in seen:
                continue
            base = _base_name(poi.name)
            if base and base in seen_base:
                continue
            seen.add(poi.id)
            if base:
                seen_base.add(base)
            matched.append(poi)

    if len(matched) < 2:
        raise HTTPException(
            422,
            "识别到的地点不足 2 个" + (("：" + "、".join(unmatched[:6])) if unmatched else "，请换一段攻略试试"),
        )

    raw_days = llm_days or max(1, math.ceil(len(matched) / 4))
    # 每天至少安排 2 个点位：识别到的地点不足以铺满原文天数时，合并天数，避免出现"一天 1 个点、0 段通勤"的空行程
    if len(matched) >= 2:
        days = max(1, min(raw_days, 7, len(matched) // 2))
    else:
        days = 1
    # 按顺序均分到各天
    per_day = math.ceil(len(matched) / days)

    trip = Trip(
        id=trip_service._gen_trip_id(), user_id=None, mode=mode, days=days,
        budget=float(budget) if budget else 1000.0,
        preferences=[], party_type="", status="draft", seed=0,
        visit_date=(str(start_date).strip()[:10] if start_date else None),
        custom_weights={}, pace_config={},
        relax_log=[], explanation=[f"由攻略文本解析生成（匹配 {len(matched)} 个点位）"],
    )
    db.add(trip)
    db.flush()

    day_rows: list[TripDay] = []
    for d in range(1, days + 1):
        td = TripDay(trip_id=trip.id, day_index=d, theme="攻略路线",
                     day_budget=0, day_cost=0)
        db.add(td)
        db.flush()
        day_rows.append(td)

    total_cost = 0.0
    day_first: dict[int, Poi] = {}
    for idx, poi in enumerate(matched):
        day_no = min(days, idx // per_day + 1)
        day_first.setdefault(day_no, poi)
        td = day_rows[day_no - 1]
        duration = int(poi.suggest_duration_min or 60)
        cost = float(poi.ticket_price or 0)
        total_cost += cost
        trip_item = TripItem(
            trip_day_id=td.id,
            slot_type=_slot_for(poi, idx % per_day, per_day),
            poi_id=poi.id, start_time="", duration_min=duration,
            cost=cost, order_index=idx % per_day,
        )
        db.add(trip_item)
    db.flush()

    # 时间轴：用确定性重算（每段通勤按距离估算）；天主题取当日第一个点位
    for d in day_rows:
        first = day_first.get(d.day_index)
        if first:
            d.theme = first.name[:12] + "线"
        d.day_cost = round(sum(float(it.cost or 0) for it in d.items), 1)
        trip_edit._retime_day(db, trip, d)
    trip.total_cost = round(sum(d.day_cost for d in day_rows), 1)
    if not budget:
        trip.budget = round(max(600.0, trip.total_cost * 1.3), 1)
    db.commit()
    db.refresh(trip)

    out = trip_service.trip_to_out(db, trip)
    note = "地点来自你粘贴的文本，已匹配本站 POI 并重新排程；未匹配的地点不会自动编造。"
    if days < raw_days:
        note = (f"原文约 {raw_days} 天，但只匹配到 {len(matched)} 个地点；"
                f"为保证每天至少 2 个点位，已合并为 {days} 天。"
                "地点来自你粘贴的文本，未匹配地点不会编造。")

    matched_text = "、".join(p.name for p in matched[:10])
    answer = (
        f"已从攻略中识别 {len(matched)} 个地点，生成 {days} 天行程：{matched_text}。"
        + (f"\n未匹配：{'、'.join(unmatched[:8])}。" if unmatched else "")
        + f"\n{note}"
    )
    conv_id = conversation_id
    try:
        from app.services import qa_service  # 局部导入避免循环依赖

        recorded = qa_service.record_exchange(
            db, "【智能解析】" + text[:400], answer,
            conversation_id=conversation_id, user_id=user_id,
        )
        conv_id = recorded["conversation_id"]
    except Exception as exc:  # noqa: BLE001 —— 历史记录失败不影响解析结果
        log.warning("[guide] 会话记录失败：%s", exc)

    return {
        "trip": out,
        "matched": [p.name for p in matched],
        "unmatched": unmatched[:10],
        "days": days,
        "note": note,
        "answer": answer,
        "conversation_id": conv_id,
    }
