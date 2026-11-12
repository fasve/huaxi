"""T7 AI 润色与小贴士。

- 默认走**规则模板**生成，零外部依赖、结果稳定；
- 配置 `AI_POLISH_BASE_URL / AI_POLISH_API_KEY` 且开启 `FEATURE_AI_POLISH` 时，
  调用 OpenAI 兼容的 /chat/completions 对文案做润色，失败自动回退规则模板；
- 结果按行程缓存在 `trip_enrichment`，避免重复调用与费用膨胀。
"""
from __future__ import annotations

import json
import urllib.request

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Poi, Trip, TripEnrichment
from app.planner.models import MODE_NAMES

TRANSPORT_LABEL = {
    "self_drive": "自驾，注意景区停车与山路会车",
    "taxi": "打车为主，山区路段建议提前约返程车",
    "transit": "公交/地铁为主，预留换乘与步行时间",
    "walk_bike": "步行/骑行串联，穿舒适鞋并注意防晒",
}


def _poi_names(db: Session, trip: Trip) -> dict[int, Poi]:
    ids = {it.poi_id for d in trip.days_plan for it in d.items if it.poi_id}
    if not ids:
        return {}
    return {p.id: p for p in db.query(Poi).filter(Poi.id.in_(ids)).all()}


def build_rule_payload(db: Session, trip: Trip) -> dict:
    """规则模板：不依赖外部服务，保证任何环境都能出小贴士。"""
    mode_name = MODE_NAMES.get(trip.mode, trip.mode)
    stored = dict(trip.pace_config or {})
    transport = (stored.get("cost_prefs") or {}).get("transport") or "transit"
    preset = stored.get("preset_route") or {}
    contains_preset = bool(preset)

    poi_map = _poi_names(db, trip)
    days = []
    for day in sorted(trip.days_plan, key=lambda x: x.day_index):
        items = sorted(day.items, key=lambda x: x.order_index)
        play = [poi_map.get(it.poi_id) for it in items
                if it.slot_type in ("morning", "afternoon", "evening") and it.poi_id]
        play = [p for p in play if p is not None]
        foods = [poi_map.get(it.poi_id) for it in items
                 if it.slot_type in ("lunch", "dinner") and it.poi_id]
        foods = [p for p in foods if p is not None]

        tips: list[dict] = []
        tips.append(dict(type="transport", text=TRANSPORT_LABEL.get(
            transport, "出行前确认交通方式与返程时间")))
        if play:
            tips.append(dict(
                type="highlight",
                text=f"本日重点：{'、'.join(p.name for p in play[:3])}，建议按时间轴顺序游览。",
            ))
        if foods:
            tips.append(dict(
                type="food",
                text=f"用餐推荐：{'、'.join(p.name for p in foods[:2])}；高峰时段建议提前 30 分钟。",
            ))
        elif items:
            tips.append(dict(type="food", text="本日未安排正餐，可在行程间隙就近补给。"))
        if day.day_budget:
            tips.append(dict(
                type="budget",
                text=f"当日建议预算约 {day.day_budget:.0f} 元，已花费约 {day.day_cost:.0f} 元。",
            ))
        if contains_preset and day.day_index == 1 and preset.get("reservation_note"):
            tips.append(dict(type="booking", text="入校/场馆需提前预约："
                             + str(preset["reservation_note"])[:120]))
        tips.append(dict(type="weather", text="花溪山区天气多变，出发前查看当日预报并备雨具。"))

        days.append(dict(
            day_index=day.day_index,
            title=day.theme or f"第 {day.day_index} 天",
            highlight=(play[0].name if play else ""),
            tips=tips,
        ))

    poi_tips = []
    for p in poi_map.values():
        tip = ""
        if p.rating >= 4.7:
            tip = "高分热门，建议错峰前往并预留拍照时间。"
        elif p.category == "scenic" and p.ticket_price == 0:
            tip = "免费开放，适合作为行程中的弹性补充点。"
        elif p.category == "food":
            tip = "本地风味，饭点排队较多，可错峰用餐。"
        if tip:
            poi_tips.append(dict(poi_id=p.id, name=p.name, tip=tip))

    return dict(
        summary=(
            f"这趟 {trip.days} 天「{mode_name}」行程围绕花溪区展开，"
            f"总预算 {trip.budget:.0f} 元，已排入 {sum(len(d.items) for d in trip.days_plan)} 个行程条目。"
            "以下小贴士按天整理，出发前逐条核对即可。"
        ),
        mode_name=mode_name,
        visit_date=trip.visit_date or "",
        days=days,
        poi_tips=poi_tips,
    )


def _ai_polish(rule_payload: dict) -> dict | None:
    """调用 OpenAI 兼容接口润色；任何异常返回 None 由上层回退。"""
    base = settings.AI_POLISH_BASE_URL.strip().rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    body = {
        "model": settings.AI_POLISH_MODEL,
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": (
                "你是贵州花溪本地旅行编辑。请把给定的行程小贴士润色得更自然、具体、有温度，"
                "保持 JSON 结构不变：summary / mode_name / visit_date / days / poi_tips；"
                "days[].tips[].type 仅可沿用原有类型。不要编造不存在的景点或价格。"
            )},
            {"role": "user", "content": json.dumps(rule_payload, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.AI_POLISH_API_KEY.strip()}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=settings.AI_POLISH_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    parsed = json.loads(text[start:end + 1])
    return parsed if isinstance(parsed, dict) and parsed.get("days") else None


def get_or_build(db: Session, trip: Trip, force: bool = False) -> dict:
    """读取缓存的小贴士；不存在或 force 时重新生成。"""
    row = (
        db.query(TripEnrichment)
        .filter(TripEnrichment.trip_id == trip.id, TripEnrichment.scope == "trip")
        .order_by(TripEnrichment.id.desc())
        .first()
    )
    if row is not None and not force:
        payload = dict(row.payload or {})
        payload.setdefault("provider", row.provider)
        payload["cached"] = True
        return payload

    rule_payload = build_rule_payload(db, trip)
    provider = "rule"
    payload = rule_payload
    if settings.FEATURE_AI_POLISH and settings.ai_polish_configured:
        try:
            ai_payload = _ai_polish(rule_payload)
            if ai_payload:
                # 用规则结果补齐 AI 可能缺失的字段，保证前端契约稳定
                merged = dict(rule_payload)
                merged.update(ai_payload)
                payload = merged
                provider = "ai"
        except Exception as exc:  # noqa: BLE001
            payload = dict(rule_payload)
            payload["ai_error"] = str(exc)[:120]
            provider = "rule"

    payload["provider"] = provider
    if row is None:
        row = TripEnrichment(
            trip_id=trip.id, scope="trip", day_index=0,
            provider=provider, payload=payload,
        )
        db.add(row)
    else:
        row.provider = provider
        row.payload = payload
    db.commit()
    payload["cached"] = False
    return payload


def get_cached(db: Session, trip_id: str) -> dict | None:
    row = (
        db.query(TripEnrichment)
        .filter(TripEnrichment.trip_id == trip_id, TripEnrichment.scope == "trip")
        .order_by(TripEnrichment.id.desc())
        .first()
    )
    if row is None:
        return None
    payload = dict(row.payload or {})
    payload.setdefault("provider", row.provider)
    payload["cached"] = True
    return payload
