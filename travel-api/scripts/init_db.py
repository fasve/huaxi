"""初始化数据库：建库 → 建表 → 导入种子数据（M1 验收脚本）。

用法：python scripts/init_db.py
幂等：重复执行会清空 travel 库内相关表后重建。
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import (
    Poi, PoiExtScenic, PoiExtFood, PoiExtHotel, PoiExtLeisure,
    Tag, PoiTag, TripModeConfig,
)
from app.planner.models import (
    DEFAULT_HARD_RULES, DEFAULT_WEIGHTS, MODE_DESCRIPTIONS, MODE_NAMES,
    SLOT_TEMPLATE,
)
from app.services.admin_auth import init_admin_auth
import scripts.seed_data as sd


def norm(vals: list[float], v: float) -> float:
    lo, hi = min(vals), max(vals)
    return (v - lo) / (hi - lo) if hi > lo else 1.0


def build_hot_quality(rows: list[dict]) -> None:
    """按方案 3.3 合成 hot_score；quality 以评分为主、热度微调（离线可刷）。"""
    ratings = [r["rating"] for r in rows]
    logs = [math.log10(max(r["reviews"], 1)) for r in rows]
    for r in rows:
        hot = (
            0.5 * norm(ratings, r["rating"])
            + 0.3 * norm(logs, math.log10(max(r["reviews"], 1)))
            + 0.2 * 0.5  # search_index_norm 一期固定 0.5
        )
        r["hot_score"] = round(min(1.0, max(0.0, hot)), 3)
        r["quality_score"] = round(min(1.0, 0.8 * r["rating"] / 5 + 0.2 * r["hot_score"]), 3)


def create_database() -> None:
    """独立连接创建 travel 库（不存在则建）。"""
    url = (
        f"mysql+pymysql://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/?charset=utf8mb4"
    )
    raw = create_engine(url)
    with raw.connect() as conn:
        conn.execute(text(
            f"CREATE DATABASE IF NOT EXISTS `{settings.DB_NAME}` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
        conn.commit()
    raw.dispose()
    print(f"[1/4] 数据库 `{settings.DB_NAME}` 就绪")


def main() -> None:
    create_database()

    # 清空重建（幂等）
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    init_admin_auth()   # 首次创建默认管理员账号（密码哈希存储）
    print("[2/4] 表结构创建完成（POI + 扩展表 + 标签 + 模式配置 + 行程三表 + user + 管理员/会话）")

    # --- 标签字典 ---
    db = SessionLocal()
    tag_map: dict[str, Tag] = {}
    for code, name in sd.TAGS:
        t = Tag(code=code, name=name)
        db.add(t)
        tag_map[code] = t
    db.flush()
    print(f"[3/4] 标签字典导入 {len(sd.TAGS)} 条")

    # --- 模式权重配置 ---
    for mode, weights in DEFAULT_WEIGHTS.items():
        db.add(TripModeConfig(
            mode=mode,
            mode_name=MODE_NAMES[mode],
            weights=weights,
            hard_rules=DEFAULT_HARD_RULES[mode],
            slot_template=SLOT_TEMPLATE,
            description=MODE_DESCRIPTIONS[mode],
            version=1,
        ))

    # --- POI 四类 ---
    all_rows: list[dict] = []
    for cat, rows in (("scenic", sd.SCENIC), ("food", sd.FOOD),
                      ("hotel", sd.HOTEL), ("leisure", sd.LEISURE)):
        for r in rows:
            r["category"] = cat
            all_rows.append(r)
    build_hot_quality(all_rows)

    for r in all_rows:
        price = r.get("ticket", r.get("price_min", 0)) if r["category"] != "food" else r["avg"]
        poi = Poi(
            name=r["name"], category=r["category"], sub_type=r["sub_type"],
            address=r["address"], longitude=r["lon"], latitude=r["lat"],
            open_time=r["open"], suggest_duration_min=r["duration"],
            ticket_price=float(price), price_level=r["price_level"],
            rating=r["rating"], review_count=r["reviews"],
            hot_score=r["hot_score"], quality_score=r["quality_score"],
            visitable=True, images=[],
        )
        db.add(poi)
        db.flush()

        # 扩展表
        ext = r.get("ext", {})
        if r["category"] == "scenic":
            db.add(PoiExtScenic(
                poi_id=poi.id, level=ext.get("level", ""),
                need_reservation=ext.get("need_reservation", False),
                best_season=ext.get("best_season", "全季"),
                indoor=ext.get("indoor", False),
                physical_level=ext.get("physical_level", 2),
                is_landmark=ext.get("is_landmark", False),
            ))
        elif r["category"] == "food":
            db.add(PoiExtFood(
                poi_id=poi.id, cuisine=ext.get("cuisine", "黔菜"),
                signature=ext.get("signature", []), avg_price=float(r["avg"]),
                meal_period=ext.get("meal_period", "午,晚"),
                is_time_honored=ext.get("is_time_honored", False),
            ))
        elif r["category"] == "hotel":
            db.add(PoiExtHotel(
                poi_id=poi.id, grade=ext.get("grade", "经济"),
                star=ext.get("star", 0), facility_tags=ext.get("facilities", []),
                price_min=float(r["price_min"]),
                with_breakfast=ext.get("with_breakfast", False),
            ))
        else:
            db.add(PoiExtLeisure(
                poi_id=poi.id, play_type=ext.get("play_type", ""),
                night_open=ext.get("night_open", False),
                indoor=ext.get("indoor", False),
            ))

        # 打标（必打 1~5 个）
        for code, weight in r["tags"]:
            db.add(PoiTag(poi_id=poi.id, tag_id=tag_map[code].id, weight=weight))

    db.commit()

    # --- 校验输出 ---
    from sqlalchemy import func
    n_poi = db.query(func.count(Poi.id)).scalar()
    n_landmark = db.query(func.count(Poi.id)).filter(
        Poi.category == "scenic", Poi.name.in_(["青岩古镇", "花溪公园"])
    ).scalar()
    missing = db.query(Poi).filter(
        (Poi.longitude.is_(None)) | (Poi.suggest_duration_min.is_(None))
    ).count()
    db.close()

    print(f"[4/4] POI 种子数据导入 {n_poi} 条（scenic {len(sd.SCENIC)} / food {len(sd.FOOD)} / "
          f"hotel {len(sd.HOTEL)} / leisure {len(sd.LEISURE)}）")
    print(f"      hot/quality 已按方案 3.3 公式合成；坐标缺失数 = {missing}（红线：0）")
    assert n_poi >= 80, "M1 验收要求 ≥80 条"
    assert missing == 0, "坐标/时长缺失的 POI 不得上架"
    print("初始化完成 ✔")


if __name__ == "__main__":
    main()
