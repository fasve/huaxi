"""数据库增量迁移：为 trip 表补个性化字段。

- custom_weights JSON：本次行程实际使用的权重向量（0~1，和为 1），空表示沿用模式默认。
- pace_config JSON：节奏微调（每日点数上限 / 游玩小时上限 / 晚间偏好）。

幂等：可重复执行，已存在则跳过。

用法：python scripts/migrate_trip_personalization.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from app.database import engine

COLUMNS = [
    ("custom_weights", "JSON NULL COMMENT '个性化权重向量（0~1，和为1）；空=模式默认'"),
    ("pace_config", "JSON NULL COMMENT '节奏微调：点数上限/游玩小时/晚间偏好'"),
]


def main() -> None:
    insp = inspect(engine)
    if "trip" not in insp.get_table_names():
        print("trip 表不存在，请先执行 scripts/init_db.py")
        return

    existing = {c["name"] for c in insp.get_columns("trip")}
    added = []
    for name, ddl in COLUMNS:
        if name in existing:
            print(f"trip.{name} 已存在，跳过")
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE trip ADD COLUMN {name} {ddl}"))
        added.append(name)
        print(f"✔ 已为 trip 表新增 {name} 列")

    if not added:
        print("无需变更")
    else:
        print(f"完成，共新增 {len(added)} 列：{', '.join(added)}")


if __name__ == "__main__":
    main()
