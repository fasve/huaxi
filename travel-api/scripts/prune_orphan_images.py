"""清理 static/poi 里不被任何 POI 引用的孤儿图片。

安全策略：默认只预览；`--apply` 时先把文件复制到指定备份目录（默认系统临时目录），
再删除原文件，并写出清单，方便事后核对或恢复。

用法：
    python scripts/prune_orphan_images.py                 # 预览
    python scripts/prune_orphan_images.py --apply         # 备份 + 删除
    python scripts/prune_orphan_images.py --apply --backup-dir D:\\poi_backup
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.database import SessionLocal  # noqa: E402
from app.models import Poi  # noqa: E402

IMG_DIR = BASE_DIR / "static" / "poi"


def referenced_names() -> set[str]:
    """数据库里被任何 POI 引用（含被策略隐藏的来源）的文件名。"""
    db = SessionLocal()
    try:
        names: set[str] = set()
        for p in db.query(Poi).all():
            for url in p.images or []:
                if url:
                    names.add(os.path.basename(url))
        return names
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="备份后删除（默认只预览）")
    ap.add_argument("--backup-dir", default="", help="备份目录，默认 %TEMP%\\poi_orphans_<日期>")
    args = ap.parse_args()

    refs = referenced_names()
    disk = {f.name: f for f in IMG_DIR.glob("*") if f.is_file() and f.name != ".gitkeep"}
    orphans = sorted(name for name in disk if name not in refs)
    total_bytes = sum(disk[n].stat().st_size for n in orphans)

    print(f"磁盘文件 {len(disk)} 个 | 被引用 {len(refs & set(disk))} 个 | 孤儿 {len(orphans)} 个 / {total_bytes / 1048576:.1f} MB")
    for name in orphans:
        print(f"  {name}  {disk[name].stat().st_size / 1024:.0f} KB")

    if not args.apply:
        print("\n这是预览，加 --apply 才会备份并删除")
        return

    backup = Path(args.backup_dir) if args.backup_dir else Path(os.environ.get("TEMP", ".")) / f"poi_orphans_{time.strftime('%Y%m%d')}"
    backup.mkdir(parents=True, exist_ok=True)
    manifest = {"deleted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "backup_dir": str(backup), "files": []}
    for name in orphans:
        src = disk[name]
        shutil.copy2(src, backup / name)
        manifest["files"].append({"name": name, "size": src.stat().st_size})
        src.unlink()

    out = BASE_DIR / "scripts" / f"orphans_deleted_{time.strftime('%Y%m%d')}.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已删除 {len(orphans)} 个文件；备份在 {backup}")
    print("清单:", out)


if __name__ == "__main__":
    main()
