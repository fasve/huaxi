"""根据 cloud_images.json 推导 cloud:// 前缀，并写入小程序配置。

用法：
    python scripts/apply_cloud_images.py            # 写入 utils/config.js
    python scripts/apply_cloud_images.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent          # travel-api
ROOT = BASE.parent                                     # my-travel
MAP = BASE / "scripts" / "cloud_images.json"
CONFIG = ROOT / "travel-miniapp" / "utils" / "config.js"


def cloud_prefix(mapping: dict[str, str]) -> str:
    for fid in mapping.values():
        if fid.startswith("cloud://"):
            # cloud://env-id.bucket-id/static/poi/x.jpg
            m = re.match(r"cloud://([^/]+)/", fid)
            if m:
                return m.group(1)
    raise SystemExit("映射里没有 cloud:// 记录，先跑 upload_cloud_storage.py")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mapping = json.loads(MAP.read_text(encoding="utf-8"))
    prefix = cloud_prefix(mapping)
    print(f"cloud 前缀: {prefix}")
    print(f"图片数量: {len(mapping)}")

    t = CONFIG.read_text(encoding="utf-8")
    old = "const IMAGE_BASE = '';"
    if old not in t:
        raise SystemExit("config.js 里找不到 IMAGE_BASE 锚点")
    new = f"const CLOUD_FILE_PREFIX = '{prefix}';"
    if "CLOUD_FILE_PREFIX" not in t:
        t = t.replace(old, old + "\n" + new, 1)
    else:
        t = re.sub(r"const CLOUD_FILE_PREFIX = '[^']*';", new, t, count=1)

    # 导出
    t = re.sub(
        r"(getStaticBase, )([^,\n]*)",
        r"\1" + "CLOUD_FILE_PREFIX, \\2",
        t,
        count=1,
    )
    CONFIG.write_text(t, encoding="utf-8")
    print("config.js 已写入 CLOUD_FILE_PREFIX")
    if args.dry_run:
        return


if __name__ == "__main__":
    main()
