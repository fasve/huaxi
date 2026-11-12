"""A3 价格分档与「价格 / 开放时间」生效时间管理。

设计要点：
- 价格分档规则表 `price_band_rule` 可后台调整；未配置时使用内置默认区间。
- `poi_effective_rule` 支持按日期区间覆盖票价与开放时间，到点自动生效，无需改代码。
- 所有解析走进程内 TTL 快照，避免在列表 / 生成链路里逐 POI 查库（N+1）。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import Poi, PoiEffectiveRule, PriceBandRule
from app.services.cache import TTLCache

rule_cache = TTLCache(ttl_seconds=60, max_items=16)

# 默认分档（元）：免费/低价 → 高价，映射 1~5 档
DEFAULT_BANDS: list[tuple[float, float, int]] = [
    (0, 50, 1), (50, 100, 2), (100, 200, 3), (200, 500, 4), (500, 10 ** 9, 5),
]


def invalidate() -> None:
    """管理端改动后清空快照，下一次请求重新加载。"""
    rule_cache.invalidate_prefix("")


def _today(on_date: str | date | None) -> str:
    if isinstance(on_date, date):
        return on_date.isoformat()
    return (on_date or date.today().isoformat())[:10]


def _in_window(valid_from: str, valid_to: str, day: str) -> bool:
    if valid_from and day < valid_from:
        return False
    if valid_to and day > valid_to:
        return False
    return True


def _effective_snapshot(db: Session, day: str) -> dict[tuple[int, str], PoiEffectiveRule]:
    """一次加载全部生效规则，按 (poi_id, kind) 建索引；同日多次调用走缓存。"""
    key = f"eff:{day}"
    snap = rule_cache.get(key)
    if snap is not None:
        return snap
    rows = db.query(PoiEffectiveRule).filter(PoiEffectiveRule.enabled.is_(True)).all()
    out: dict[tuple[int, str], PoiEffectiveRule] = {}
    for r in rows:
        if not _in_window(r.valid_from or "", r.valid_to or "", day):
            continue
        # 多条命中时，起效日更晚者优先（模拟"最新调价"）
        prev = out.get((r.poi_id, r.kind))
        if prev is None or (r.valid_from or "") >= (prev.valid_from or ""):
            out[(r.poi_id, r.kind)] = r
    rule_cache.set(key, out)
    return out


def price_override(
    db: Session, poi: Poi, on_date: str | date | None = None,
) -> tuple[float | None, int | None]:
    """仅在存在生效价格规则时返回覆盖值，否则 (None, None)。

    供酒店间夜价 / 餐饮人均价等非门票口径复用，避免误覆盖扩展表价格。
    """
    day = _today(on_date)
    rule = _effective_snapshot(db, day).get((poi.id, "price"))
    if not (rule and isinstance(rule.value, dict) and rule.value.get("price") is not None):
        return None, None
    try:
        price = float(rule.value["price"])
    except (TypeError, ValueError):
        return None, None
    try:
        level = int(rule.value["price_level"]) if rule.value.get("price_level") is not None else None
    except (TypeError, ValueError):
        level = None
    return price, level


def effective_price(
    db: Session, poi: Poi, on_date: str | date | None = None,
) -> tuple[float, int | None]:
    """返回 (生效票价, 生效 price_level|null)。无生效规则时回退主表值。"""
    price, level = price_override(db, poi, on_date)
    if price is not None:
        return price, level
    return float(poi.ticket_price or 0), None


def effective_open_time(
    db: Session, poi: Poi, on_date: str | date | None = None,
) -> list:
    """返回生效开放时间列表；无规则时回退主表 open_time。"""
    day = _today(on_date)
    rule = _effective_snapshot(db, day).get((poi.id, "hours"))
    if rule and isinstance(rule.value, dict) and isinstance(rule.value.get("open_time"), list):
        return list(rule.value["open_time"])
    return list(poi.open_time or [])


# ---------------- 价格分档 ----------------

def _bands(db: Session) -> list[tuple[float, float, int]]:
    snap = rule_cache.get("bands")
    if snap is not None:
        return snap
    rows = (
        db.query(PriceBandRule)
        .filter(PriceBandRule.enabled.is_(True))
        .order_by(PriceBandRule.min_price.asc())
        .all()
    )
    bands = (
        [(float(r.min_price or 0), float(r.max_price), int(r.price_level)) for r in rows]
        if rows else list(DEFAULT_BANDS)
    )
    rule_cache.set("bands", bands)
    return bands


def level_for_price(db: Session, price: float) -> int:
    """按分档规则把票价映射为 1~5 档。"""
    p = float(price or 0)
    for lo, hi, level in _bands(db):
        if lo <= p < hi:
            return max(1, min(5, level))
    return 5


def apply_bands(db: Session, category: str | None = None) -> dict:
    """把分档规则批量落到 POI 主表（可按类别限定），返回变更统计。"""
    q = db.query(Poi)
    if category:
        q = q.filter(Poi.category == category)
    updated = 0
    for poi in q.all():
        # 酒店 / 美食的成本口径是间夜价、人均价，不按门票分档覆盖
        if poi.category in ("hotel", "food"):
            continue
        price, _ = effective_price(db, poi)
        level = level_for_price(db, price)
        if level != poi.price_level:
            poi.price_level = level
            updated += 1
    db.commit()
    invalidate()
    return dict(updated=updated, category=category or "all")
