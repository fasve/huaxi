"""预设主题路线（游学线）验证脚本：date_gate 四类闸门 + 一键成程注入。

用法：python scripts/verify_preset_routes.py
覆盖：工作日 / 周末 / 寒暑假 / 法定节假日 / 花期 / 错季替换 / 预约提醒 /
      纯展示接口 / 生成注入顺序 / relax_log 降级提示 / 拼接能力 / 重排不丢动线。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import Trip
from app.planner.preset_routes import (
    evaluate_gates, in_season_window, is_business_day, parse_visit_date,
    route_day_summary,
)
from app.services.preset_seed import ensure_preset_routes
from app.services import preset_route_service as svc
from app.services import trip_service

PASS, FAIL = 0, 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✔ {label}")
    else:
        FAIL += 1
        print(f"  ✘ {label}  {detail}")


def main() -> None:
    print("== 0. 幂等建表 + 种子 ==")
    boot = ensure_preset_routes()
    check("启动幂等执行不抛异常", isinstance(boot, dict), str(boot))
    check("线路已就绪", boot.get("code") == "gzu_campus_study_tour", str(boot))

    print("== 1. 日期闸门纯逻辑 ==")
    check("工作日 2026-11-11 可进馆", is_business_day(date(2026, 11, 11)))
    check("周六 2026-11-14 不可进馆", not is_business_day(date(2026, 11, 14)))
    check("寒暑假 2026-01-15 不可进馆", not is_business_day(date(2026, 1, 15)))
    check("国庆 2026-10-01 不可进馆", not is_business_day(date(2026, 10, 1)))
    check("花期窗口 03-25 命中", in_season_window(date(2026, 3, 25), "03-15", "04-05"))
    check("非花期 11-11 未命中", not in_season_window(date(2026, 11, 11), "03-15", "04-05"))
    check("跨年窗口 12-25 命中", in_season_window(date(2026, 12, 25), "12-20", "01-10"))
    check("非法日期回落到今天", parse_visit_date("bad").year >= 2026)

    wk = evaluate_gates([{"type": "weekday_only", "name": "校史馆"}],
                        "2026-11-11", stay_min=60, poi_id=1,
                        degrade_stay_min=20, degrade_text="馆外讲解")
    check("工作日校史馆原样通过", wk.status == "open" and wk.effective_stay_min == 60)
    we = evaluate_gates([{"type": "weekday_only", "name": "校史馆"}],
                        "2026-11-14", stay_min=60, poi_id=1,
                        degrade_stay_min=20, degrade_text="馆外讲解")
    check("周末校史馆降级 + 时长压缩", we.status == "degraded" and we.effective_stay_min == 20)
    check("降级给出原因文案", bool(we.notes) and "周末" in we.notes[0])
    sw = evaluate_gates([{"type": "season_window", "start": "03-15", "end": "04-05"}],
                        "2026-11-11", stay_min=40, poi_id=2, fallback_poi_id=99)
    check("错季替换为常绿站点", sw.status == "replaced" and sw.effective_poi_id == 99)
    rs = evaluate_gates([{"type": "reservation_required", "channel": "iGZU", "task": "提前预约"}],
                        "2026-11-11", stay_min=20, poi_id=3)
    check("预约闸门只挂任务不阻断", rs.status == "reminder" and len(rs.actions) == 1)
    check("预约渠道信息完整", (rs.reservation or {}).get("channel") == "iGZU")
    oh = evaluate_gates([{"type": "open_hours", "windows": [["08:30", "11:30"]]}],
                        "2026-11-11", stay_min=60, poi_id=4)
    check("开放时段给出到站建议", oh.suggest_arrival == "08:30")
    check("日期概览含日型与室内可用性",
          route_day_summary(date(2026, 11, 14))["day_type"] == "周末"
          and not route_day_summary(date(2026, 11, 14))["indoor_venues_open"])

    db = SessionLocal()
    try:
        print("== 2. 纯展示接口（#14）==")
        routes = svc.list_routes(db, visit_date="2026-11-11")
        check("线路列表非空", len(routes) >= 1)
        check("列表带日期概览", bool(routes[0].get("day")))
        work = svc.get_route(db, "gzu_campus_study_tour", "2026-11-11")
        check("半日线站点数 ≥5", len(work["stops"]) >= 5, str(len(work["stops"])))
        check("逐站讲解齐全", all(s["narration_text"] for s in work["stops"]))
        check("研学任务卡齐全", all(s["task_cards"] for s in work["stops"]))
        check("线路级预约提醒", work["reservation"] is not None)
        check("错季触发站点替换", work["degraded_count"] >= 1,
              str(work["gate_notes"]))
        check("relax 文案含花期说明",
              any("花期" in n for n in work["gate_notes"]))
        weekend = svc.get_route(db, "gzu_campus_study_tour", "2026-11-14")
        check("周末校史馆降级",
              any(s["gate"]["status"] == "degraded" and s["seq"] == 4
                  for s in weekend["stops"]))
        check("周末降级后停留压缩为 20min",
              next((s["effective_stay_min"] for s in weekend["stops"] if s["seq"] == 4), 0) == 20)
        spring = svc.get_route(db, "gzu_campus_study_tour", "2026-03-25")
        check("花期站点不再被替换",
              not any(s["seq"] == 3 and s["gate"]["replaced"] for s in spring["stops"]))
        addon = svc.get_route(db, "gzu_campus_study_tour", "2026-11-11",
                              include_addon=True)
        check("全天深度版加段可并入", any(s["is_addon"] for s in addon["stops"]))
        check("默认不并入加段", not any(s["is_addon"] for s in work["stops"]))
        check("线路标注未核实来源", len(work["unverified_sources"]) >= 1)

        print("== 3. 一键成程（#15）：保底注入 + 拼接 ==")
        common = dict(days=1, budget=800, preferences=[], party_type="family", seed=42,
                      user_id=None)
        out = trip_service.create_trip(
            db, mode="leisure", visit_date="2026-11-11",
            preset_route_code="gzu_campus_study_tour", **common
        )
        d1 = out["days_plan"][0]
        marked = [i for i in d1["items"] if i.get("preset")]
        seqs = [i["preset"]["seq"] for i in marked]
        check("第 1 天含游学保底站", len(marked) >= 4, str(len(marked)))
        check("站点按 seq 顺序排列", seqs == sorted(seqs), str(seqs))
        check("保底站带逐站讲解", all(i["preset"]["narration_text"] for i in marked))
        check("保底站带任务卡", all(i["preset"]["task_card"] for i in marked))
        check("响应带线路详情", bool(out.get("preset_route")))
        check("响应带出行日期", out.get("visit_date") == "2026-11-11")
        check("主题为游学线", "游学" in d1["theme"], d1["theme"])
        check("relax_log 含 date_gate 降级说明",
              any("花期" in r.get("detail", "") for r in out["relax_log"]))
        check("说明卡含预约提示",
              any("预约" in e for e in out["explanation"]))
        free_items = [i for i in d1["items"] if not i.get("preset")]
        check("剩余槽位仍有自由生成点位（拼接能力）", len(free_items) >= 2,
              str(len(free_items)))
        check("预算未失控", out["budget_usage"] <= 1.3, str(out["budget_usage"]))

        plain = trip_service.create_trip(db, mode="leisure", **common)
        check("不带线路时无游学站点",
              not any(i.get("preset") for i in plain["days_plan"][0]["items"]))

        full = trip_service.create_trip(
            db, mode="blitz", visit_date="2026-11-11",
            preset_route_code="gzu_campus_study_tour", include_addon=True,
            **{**common, "budget": 1000},
        )
        full_marked = [i for i in full["days_plan"][0]["items"] if i.get("preset")]
        check("全天深度版加段注入生效", len(full_marked) >= 6, str(len(full_marked)))
        check("加段站点为南校区文保建筑群",
              any("南校区" in i["name"] for i in full_marked),
              str([i["name"] for i in full_marked]))
        check("出校衔接站不与错季替换站重复",
              len({i["poi_id"] for i in full_marked}) == len(full_marked))

        print("== 4. 重新读取行程 / 按权重重排 / 单日重排 ==")
        reopened = trip_service.trip_to_out(db, db.get(Trip, out["trip_id"]))
        check("重新打开仍带逐站讲解",
              any(i.get("preset") for i in reopened["days_plan"][0]["items"]))
        check("重新打开仍带线路详情", bool(reopened.get("preset_route")))
        rw = trip_service.reweight_trip(db, out["trip_id"], {"quality": 50})
        check("按权重重排后游学动线仍在",
              len([i for i in rw["days_plan"][0]["items"] if i.get("preset")]) >= 4)
        rb = trip_service.rebalance(db, out["trip_id"], 1, "redrop", None, None)
        check("单日换一批后游学动线仍在",
              len([i for i in rb["days_plan"][0]["items"] if i.get("preset")]) >= 4)

        print("== 5. A7 管理端开关 ==")
        svc.set_route_enabled(db, "gzu_campus_study_tour", False, "2026-11-11")
        check("停用后游客端列表为空",
              len(svc.list_routes(db)) == 0)
        check("管理端仍可见停用线路",
              any(r["code"] == "gzu_campus_study_tour"
                  for r in svc.admin_list_routes(db)))
        svc.set_route_enabled(db, "gzu_campus_study_tour", True)
        check("重新启用后游客端可见",
              len(svc.list_routes(db)) >= 1)
    finally:
        db.close()

    print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
