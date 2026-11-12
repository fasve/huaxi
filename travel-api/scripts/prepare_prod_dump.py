"""导出前清理测试数据：行程、问答会话、访客账号与联动表（保留资源/模式/路线/知识库）。

用法：
    python scripts/prepare_prod_dump.py --dry-run   # 只看会删多少
    python scripts/prepare_prod_dump.py --apply     # 真删
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

# 顺序：先子表后主表；这些表存的是"用户行为/会话"数据，生产库应从零开始
CLEAN = [
    ("trip_item", "行程项"),
    ("trip_day", "行程天"),
    ("trip_enrichment", "行程附加信息"),
    ("trip_reminder", "出行提醒"),
    ("trip_share_log", "分享记录"),
    ("trip", "行程"),
    ("qa_message", "问答消息"),
    ("qa_conversation", "问答会话"),
    ("user_trip_stat", "用户行程统计"),
    ("user_visit_log", "访问日志"),
    ("user_wechat_session", "微信会话密钥"),
    ("user_session", "游客会话"),
    ("user_account", "账号凭证"),
    ("user", "访客账号"),
    ("admin_session", "管理端会话"),
    ("audit_log", "审计日志"),
    ("token_denylist", "JWT 撤销名单"),
]

KEEP = ["poi", "poi_ext_*", "poi_tag", "tag", "tag_synonym", "preset_route",
        "preset_route_stop", "trip_mode_config", "trip_mode_config_version",
        "price_band_rule", "poi_effective_rule", "qa_knowledge", "admin_user"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with engine.begin() as conn:
        existing = {r[0] for r in conn.execute(text("SHOW TABLES"))}
        total = 0
        for table, label in CLEAN:
            if table not in existing:
                print(f"  - {table:22} 不存在，跳过")
                continue
            n = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
            total += n
            print(f"  {'删除' if args.apply else '将删除'} {table:22} {n:>6} 行  ({label})")
            if args.apply and n:
                conn.execute(text(f"DELETE FROM {table}"))

        print("\n保留：", "、".join(KEEP))
        print(f"{'已删除' if args.apply else '待删除'}合计 {total} 行")
        if not args.apply:
            print("这是 dry-run，加 --apply 才会真删")


if __name__ == "__main__":
    main()
