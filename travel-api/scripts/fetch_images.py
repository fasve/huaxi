"""批量为全部 POI 联网抓取图片并写入 poi.images / poi.image_meta。

数据源按合规优先级自动降级（Wikimedia → Openverse → Pixabay → Pexels），
Web 搜索兜底默认关闭。每张图都会记录来源与授权元信息。

用法：
    python scripts/fetch_images.py             # 全量抓取（已有图片的跳过）
    python scripts/fetch_images.py --force     # 强制重抓
    python scripts/fetch_images.py --limit 5   # 只抓前 5 条（调试）
    python scripts/fetch_images.py --only 3,7  # 只抓指定 id
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Poi  # noqa: E402
from app.services.cache import poi_cache  # noqa: E402
from app.services.image_service import fetch_poi_images, provider_status  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已有图片也重新抓取")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条")
    ap.add_argument("--only", default="", help="逗号分隔的 poi id")
    ap.add_argument("--count", type=int, default=3, help="每个 POI 保存图片数")
    args = ap.parse_args()

    print("=== 可用图片源 ===")
    for p in provider_status():
        mark = "✔" if p["available"] else "✘"
        print(f"  {mark} {p['display_name']}（{p['license_type']}）— {p['reason']}")
    print()

    db = SessionLocal()
    q = db.query(Poi).order_by(Poi.id)
    only_ids = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
    if only_ids:
        q = q.filter(Poi.id.in_(only_ids))
    rows = q.all()
    if args.limit:
        rows = rows[: args.limit]

    ok_n = 0
    total_n = 0
    for i, p in enumerate(rows, 1):
        total_n += 1
        if p.images and not args.force:
            print(f"[{i}/{len(rows)}] {p.id} {p.name} 已有图片，跳过")
            continue
        try:
            results = fetch_poi_images(
                p.name, p.sub_type or "", p.category or "", key=f"{p.id}", max_count=args.count
            )
        except Exception as exc:  # 单条失败不影响整体
            print(f"[{i}/{len(rows)}] {p.id} {p.name} 抓取异常：{exc}")
            continue
        good = [r for r in results if r.ok]
        if not good:
            print(f"[{i}/{len(rows)}] {p.id} {p.name} 未获得图片")
            continue
        p.images = [r.url for r in good]
        p.image_meta = [r.to_meta() for r in good]
        ok_n += 1
        src = good[0].source_name or good[0].source
        print(f"[{i}/{len(rows)}] {p.id} {p.name} -> {len(good)} 张（{src}）")
        db.commit()
        time.sleep(0.6)   # 控制请求频率，避免被目标站点限流

    poi_cache.invalidate_prefix("pois:")
    db.commit()
    print(f"\n完成：处理 {total_n} 条，成功写入图片 {ok_n} 条")


if __name__ == "__main__":
    main()
