"""P1/P2 扩展表初始化：启动期幂等建表 + 价格分档默认种子。

新表（trip_enrichment / trip_reminder / user_trip_stat / price_band_rule /
poi_effective_rule / tag_synonym / trip_mode_config_version）由 `create_all` 自动创建；
已存在的库只需补种默认分档，不覆盖管理员配置。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import PriceBandRule

DEFAULT_PRICE_BANDS = [
    ("免费/低价", 0, 50, 1, "公共绿地、免费开放点位"),
    ("常规", 50, 100, 2, "常规收费景点"),
    ("中价", 100, 200, 3, "含讲解/体验的景区"),
    ("高价", 200, 500, 4, "主题乐园 / 深度体验"),
    ("高价", 500, 10 ** 9, 5, "高端组合票 / 套票"),
]


def seed_price_bands(db: Session) -> int:
    if db.query(PriceBandRule).count() > 0:
        return 0
    for name, lo, hi, level, desc in DEFAULT_PRICE_BANDS:
        db.add(PriceBandRule(
            name=name, min_price=lo, max_price=hi,
            price_level=level, enabled=True, description=desc,
        ))
    db.commit()
    return len(DEFAULT_PRICE_BANDS)


def ensure_extensions() -> dict:
    """一步到位：建表 + 补种子。重跑安全。"""
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        seeded = seed_price_bands(db)
    finally:
        db.close()
    return dict(price_bands_seeded=seeded)
