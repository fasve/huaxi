"""为历史已抓取的图片回填授权元数据。

背景：早期版本的抓取逻辑没有记录图片来源与授权，导致 poi.image_meta 为空，
无法满足"每张图都能追溯授权"的要求。本脚本为存量图片补一份标注。

处理方式：
1. 逐个 POI 读取 images 列表；
2. 按文件名哈希反查本地静态目录，确认文件仍在（区分实拍与占位图）；
3. 占位图（.svg）标注为"内置占位图 / 本地生成"；
4. 实拍图标注为"历史抓取 / 来源待确认"，并写明处理建议：
   商用前应重新用合规图库（Wikimedia / Openverse / Pixabay / Pexels）抓取替换。

用法：python scripts/backfill_image_meta.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Poi  # noqa: E402
from app.services.image_service import POI_IMG_DIR  # noqa: E402


def main() -> None:
    db = SessionLocal()
    rows = db.query(Poi).all()
    filled = 0
    for p in rows:
        images = list(p.images or [])
        if not images:
            continue
        metas = []
        for url in images:
            fname = os.path.basename(url)
            path = os.path.join(POI_IMG_DIR, fname)
            exists = os.path.exists(path)
            if fname.endswith(".svg"):
                metas.append(dict(
                    source="placeholder", source_name="内置占位图",
                    author="", license="本地生成（SVG）", license_url="",
                ))
            else:
                metas.append(dict(
                    source="legacy", source_name="历史抓取",
                    author="", license="未知授权，商用前请替换为合规图库素材",
                    license_url="",
                ))
            if not exists:
                metas[-1]["license"] = "本地文件缺失，需重新抓取"
        if metas != (p.image_meta or []):
            p.image_meta = metas
            filled += 1
    db.commit()
    print(f"✔ 已回填 {filled} 条 POI 的图片授权元数据（共 {len(rows)} 条 POI）")


if __name__ == "__main__":
    main()
