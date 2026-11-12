"""体检：每个 POI 的图片是否配齐、元信息是否齐全、文件是否都在、有无孤儿。

用法：
    python scripts/check_poi_images.py                # 按默认期望 2 张
    python scripts/check_poi_images.py --expect 3     # 期望 3 张
    python scripts/check_poi_images.py --strict       # 有缺失就返回非 0（CI/门禁用）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api/v1")
IMG_DIR = BASE_DIR / "static" / "poi"


def fetch_all() -> list[dict]:
    items, page = [], 1
    while True:
        url = f"{API_BASE}/pois?page={page}&page_size=50"
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        items.extend(data.get("items", []))
        if len(items) >= data.get("total", 0) or not data.get("items"):
            return items
        page += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect", type=int, default=2)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    pois = fetch_all()
    total = len(pois)
    by_cat: Counter = Counter()
    missing: list[tuple[str, str, int]] = []
    bad_meta: list[str] = []
    files = 0

    for p in pois:
        n = len(p.get("images") or [])
        by_cat[p["category"]] += 1
        if n < args.expect:
            missing.append((p["category"], p["name"], n))
        for m in p.get("image_meta") or []:
            if not m.get("license") or not m.get("source_name"):
                bad_meta.append(p["name"])
                break
        files += n

    referenced = set()
    for p in pois:
        for url in p.get("images") or []:
            # 用相对 /static/poi/ 的路径比较，才能覆盖 covers/ 子目录
            rel = url.split("/static/poi/", 1)[-1] if "/static/poi/" in url else os.path.basename(url)
            referenced.add(rel)
    disk = {
        f.relative_to(IMG_DIR).as_posix()
        for f in IMG_DIR.rglob("*")
        if f.is_file() and f.name != ".gitkeep"
    }
    missing_files = referenced - disk
    orphan = disk - referenced

    print("=" * 56)
    print(f"POI 总数 {total}，期望每个 ≥{args.expect} 张")
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:<8} {n}")
    print(f"已配图引用 {files} 张 | 磁盘文件 {len(disk)} 个")
    print(f"配齐度：{total - len(missing)}/{total}（{(total - len(missing)) / max(total, 1) * 100:.0f}%）")
    if missing:
        print(f"\n缺图 POI {len(missing)} 个（前 12 个）：")
        for cat, name, n in missing[:12]:
            print(f"  [{cat}] {name}  现有 {n}")
    if bad_meta:
        print(f"\n元信息不全（缺 license / source_name）{len(bad_meta)} 个：{', '.join(bad_meta[:6])}")
    if missing_files:
        print(f"\n引用存在但磁盘缺失（会 404）{len(missing_files)} 个：{', '.join(sorted(missing_files)[:5])}")
    if orphan:
        print(f"\n磁盘孤儿文件 {len(orphan)} 个（不被任何 POI 引用，可清理）")
    print("=" * 56)

    if args.strict and (missing or bad_meta or missing_files):
        sys.exit(1)


if __name__ == "__main__":
    main()
