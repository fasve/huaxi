"""把 static/poi 里已经存在的历史照片「认领」回对应的 POI。

背景：图片策略改成「只展示本地自有素材」后，历史抓取的图被隐藏了。本脚本把
**磁盘上确实存在**的历史图重新挂回原 POI，并如实标记来源，避免冒充管理员上传：

- `image_meta.source = "legacy_local"`（本地存量，允许展示）
- `source_name = "历史存量（本地）"`
- `license = "来源未记录，商用前需替换为已授权素材"`
- `note` 记录原文件名；`placeholder` 来源（自动生成的占位 SVG）一律丢弃，不冒充实拍。

同时修复被误清空的 POI #1（青岩古镇）：它的 5 张图文件仍在磁盘，按原文件名恢复。

用法：
    python scripts/adopt_local_legacy_images.py --dry-run   # 只看计划
    python scripts/adopt_local_legacy_images.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.database import SessionLocal  # noqa: E402
from app.models import Poi  # noqa: E402

IMG_DIR = BASE_DIR / "static" / "poi"

# 误清空的 POI#1（青岩古镇）原始文件，来自清理前的接口返回
RESTORE = {
    1: [
        "ab40e6da8fa1.jpg",
        "037b8ad63497.jpg",
        "9a266b838094.jpg",
        "a3350382c815.jpg",
        "abb5787f535f.jpg",
    ],
}

LICENSE = "来源未记录，商用前需替换为已授权素材"
SOURCE_NAME = "历史存量（本地）"


def meta_for(filename: str) -> dict:
    return dict(source="legacy_local", source_name=SOURCE_NAME, author="",
                license=LICENSE, license_url="", note=f"legacy file: {filename}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库（默认只预览）")
    ap.add_argument("--dry-run", action="store_true", help="仅预览（默认行为）")
    args = ap.parse_args()

    have = {f.name for f in IMG_DIR.glob("*") if f.is_file()}
    db = SessionLocal()
    report = {"adopted": [], "dropped": [], "missing": [], "restored": []}

    for p in db.query(Poi).all():
        images, metas = [], []
        for i, url in enumerate(p.images or []):
            name = os.path.basename(url or "")
            meta = (p.image_meta or [])[i] if i < len(p.image_meta or []) else {}
            src = (meta or {}).get("source")
            if src == "upload":
                images.append(url)
                metas.append(meta)
                continue
            if src == "placeholder":
                report["dropped"].append({"id": p.id, "name": p.name, "file": name,
                                          "why": "placeholder"})
                continue
            if name in have:
                images.append(url)
                metas.append(meta_for(name))
                report["adopted"].append({"id": p.id, "name": p.name, "file": name})
            else:
                report["missing"].append({"id": p.id, "name": p.name, "file": name})

        # 恢复被清空的 POI#1
        if p.id in RESTORE and not images:
            for name in RESTORE[p.id]:
                if name in have:
                    images.append(f"/static/poi/{name}")
                    metas.append(meta_for(name))
                    report["restored"].append({"id": p.id, "name": p.name, "file": name})

        p.images = images
        p.image_meta = metas

    if args.apply:
        db.commit()
    db.close()

    print(f"认领 {len(report['adopted'])} 张（挂回原 POI）")
    print(f"恢复 POI#1 {len(report['restored'])} 张")
    print(f"丢弃占位图 {len(report['dropped'])} 张")
    print(f"文件缺失（引用但磁盘没有） {len(report['missing'])} 张")
    for item in report["dropped"]:
        print(f"  - {item['id']} {item['name']}：{item['file']}（{item['why']}）")
    out = BASE_DIR / "scripts" / "adopt_images_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", out)
    if not args.apply:
        print("\n这是 dry-run，加 --apply 才会写库")


if __name__ == "__main__":
    main()
