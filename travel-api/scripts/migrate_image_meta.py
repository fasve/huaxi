"""数据库增量迁移：为 poi 表补 image_meta 列（图片授权元信息）。

幂等：可重复执行。已存在则跳过。

用法：python scripts/migrate_image_meta.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from app.database import engine


def main() -> None:
    insp = inspect(engine)
    if "poi" not in insp.get_table_names():
        print("poi 表不存在，请先执行 scripts/init_db.py")
        return

    cols = {c["name"] for c in insp.get_columns("poi")}
    if "image_meta" in cols:
        print("poi.image_meta 已存在，跳过")
        return

    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE poi ADD COLUMN image_meta JSON NULL "
            "COMMENT '图片授权元信息，与 images 同序'"
        ))
    print("✔ 已为 poi 表新增 image_meta 列")


if __name__ == "__main__":
    main()
