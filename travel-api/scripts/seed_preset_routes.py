"""预设主题路线：手动建表补列 + 重建贵大校园游学线种子。

服务启动时已幂等自动执行（app/main.py lifespan → ensure_preset_routes），
本脚本用于：① 手动迁移存量库 ② 改了线路文案后强制刷新。

用法：
    python scripts/seed_preset_routes.py            # 幂等，已有线路则跳过
    python scripts/seed_preset_routes.py --force   # 删除并重建线路（保留 study POI）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.preset_seed import ensure_schema, seed_if_empty

if __name__ == "__main__":
    force = "--force" in sys.argv
    added = ensure_schema()
    result = seed_if_empty(force=force)
    print(f"trip 新增列：{added or '无（已存在）'}")
    print(f"线路种子：{result}")
    print("完成 ✔")
