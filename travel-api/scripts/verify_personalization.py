"""个性化权重能力验证：归一化 / 节奏改写 / 预览 / 重排。

用法：python scripts/verify_personalization.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.planner.weights import (
    EVENING_PREFERENCES, WEIGHT_KEYS, WEIGHT_PRESETS, apply_pace,
    normalize_weights, slider_defaults, weight_profile,
)
from app.services.trip_service import (
    create_trip, get_mode_cfg, preview_weights, reweight_trip,
)

OK = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"

_PASSED = 0
_TOTAL = 0


def check(cond: bool, label: str) -> bool:
    """记录一项检查结果（每调用一次计一项）。"""
    global _PASSED, _TOTAL
    _TOTAL += 1
    if cond:
        _PASSED += 1
    print((OK if cond else FAIL) + f" {label}")
    return cond


def main() -> None:
    db: Session = SessionLocal()

    # 1. 归一化：和为 1
    base = {k: 0.25 for k in WEIGHT_KEYS}
    w = normalize_weights({k: 50 for k in WEIGHT_KEYS}, base)
    check(abs(sum(w.values()) - 1.0) < 1e-6, f"归一化后权重和为 1（实际 {sum(w.values()):.6f}）")

    # 2. 归一化：空输入返回默认
    check(normalize_weights({}, base) == base, "空权重输入返回模式默认权重")

    # 3. 归一化：非法键被忽略
    w2 = normalize_weights({"quality": 60, "hacker_key": 999, "popularity": 40}, base)
    check("hacker_key" not in w2 and set(w2) <= set(WEIGHT_KEYS), "非法维度键被忽略")

    # 4. 归一化：全 0 返回默认
    w3 = normalize_weights({k: 0 for k in WEIGHT_KEYS}, base)
    check(w3 == base, "全 0 权重回落到模式默认")

    # 5. 滑块初值与模式默认一致
    sd = slider_defaults(base)
    check(all(0 <= v <= 100 for v in sd.values()), "滑块初值落在 0~100 区间")

    # 6. 节奏改写：点数上限与小时上限生效
    rules = {"daily_poi_min": 2, "daily_poi_max": 3, "daily_play_hours_max": 6,
             "day_start": "09:30", "day_end": "21:00", "lunch_window": ["11:30", "13:30"]}
    r2 = apply_pace(rules, {"daily_poi_max": 5, "play_hours_max": 10}, "leisure")
    check(r2["daily_poi_max"] == 5 and r2["daily_play_hours_max"] == 10,
                    "节奏微调改写点数与小时上限")
    check(rules["daily_poi_max"] == 3, "节奏微调不污染原始 rules")

    # 7. 晚间偏好映射
    r3 = apply_pace(rules, {"evening": "night_scene"}, "leisure")
    check(r3["evening_slot"] == "landmark_night" and r3["day_end"] == "21:30",
                    "晚间偏好 night_scene 映射为夜市灯光 + 21:30 收工")
    r4 = apply_pace(rules, {"evening": "fine_dining"}, "leisure")
    check(r4["dinner_start"] == "18:30" and r4["dinner_duration_min"] == 90,
                    "晚间偏好 fine_dining 延后晚餐至 18:30 / 90 分钟")

    # 8. 权重档数校验
    check(len(WEIGHT_PRESETS) >= 6 and len(EVENING_PREFERENCES) == 3,
                    f"权重预设 {len(WEIGHT_PRESETS)} 套 / 晚间偏好 {len(EVENING_PREFERENCES)} 套")

    # 9. 预览接口（不落库）
    prev = preview_weights(db, "leisure", {"quality": 90, "popularity": 80,
                                           "landmark": 70, "cost_efficiency": 10,
                                           "budget_fit": 10, "time_density": 10,
                                           "rest_comfort": 10, "local_flavor": 5},
                            preferences=[], pace=None, top_k=10)
    check(len(prev["items"]) > 0, f"权重预览返回 {len(prev['items'])} 个候选点")
    check(abs(sum(prev["weights"].values()) - 1.0) < 1e-6, "预览返回的权重已归一化")
    check(prev["is_personalized"] is True, "预览标记为已个性化")
    check(len(prev["profile"]) == len(WEIGHT_KEYS), "预览返回完整 8 维画像")

    # 10. 生成带自定义权重的行程
    trip = create_trip(db, days=2, budget=1200, mode="checkin",
                       preferences=[], party_type="couple", seed=42, user_id=None,
                       custom_weights={"quality": 20, "popularity": 30, "landmark": 40,
                                       "cost_efficiency": 5, "budget_fit": 5,
                                       "time_density": 10, "rest_comfort": 0,
                                       "local_flavor": 0})
    check(trip["is_personalized"] is True, "生成行程标记为个性化")
    check(abs(sum(trip["custom_weights"].values()) - 1.0) < 1e-6,
                    "行程持久化的权重和为 1")
    check(len(trip["days_plan"]) == 2, "个性化行程天数正确")
    poi_names = [it["name"] for d in trip["days_plan"] for it in d["items"]]
    check(len(poi_names) > 0, f"个性化行程排入 {len(poi_names)} 个点位")

    # 11. 默认权重行程标记为非个性化
    trip2 = create_trip(db, days=1, budget=600, mode="leisure",
                        preferences=[], party_type="solo", seed=7, user_id=None)
    check(trip2["is_personalized"] is False, "未传权重时标记为非个性化（沿用模式默认）")

    # 12. 按权重重排既有行程
    re = reweight_trip(db, trip["trip_id"],
                       slider_raw={"quality": 5, "popularity": 5, "landmark": 5,
                                   "cost_efficiency": 40, "budget_fit": 30,
                                   "time_density": 10, "rest_comfort": 3, "local_flavor": 2},
                       pace={"daily_poi_max": 4, "play_hours_max": 8, "evening": "relax"})
    check(re["trip_id"] == trip["trip_id"], "重排后行程 ID 不变")
    check(re["is_personalized"] is True, "重排后仍为个性化行程")
    check(re["pace_config"].get("evening") == "relax", "重排后节奏微调已保存")
    check(abs(sum(re["custom_weights"].values()) - 1.0) < 1e-6, "重排后权重和为 1")

    # 13. 权重档位确实改变了选点排序
    prev_high_qual = preview_weights(db, "leisure",
                                     {"quality": 95, "popularity": 2, "landmark": 1,
                                      "cost_efficiency": 1, "budget_fit": 1,
                                      "time_density": 0, "rest_comfort": 0,
                                      "local_flavor": 0}, [], None, 10)
    prev_popular = preview_weights(db, "leisure",
                                   {"quality": 2, "popularity": 95, "landmark": 1,
                                    "cost_efficiency": 1, "budget_fit": 1,
                                    "time_density": 0, "rest_comfort": 0,
                                    "local_flavor": 0}, [], None, 10)
    n1 = [i["poi_id"] for i in prev_high_qual["items"]]
    n2 = [i["poi_id"] for i in prev_popular["items"]]
    check(n1 != n2, "品质优先与热度优先给出不同的选点排序")

    # 14. 画像百分比
    prof = weight_profile(prev["weights"])
    check(abs(sum(p["percent"] for p in prof) - 100) <= 2, "权重画像百分比合计约 100%")

    # 15. 回归：收紧收工时间后晚餐仍应被排入（下午不得挤占晚餐窗口）
    from app.planner.engine import generate_trip
    from app.planner.models import TripRequest
    from app.services.poi_service import stage1_candidates

    cfg = get_mode_cfg(db, "checkin")
    r_relax = apply_pace(dict(cfg.hard_rules),
                          {"daily_poi_max": 4, "play_hours_max": 9, "evening": "relax"},
                          "checkin")
    cands_relax, _ = stage1_candidates(db, r_relax, [])
    plan_relax = generate_trip(
        cands_relax,
        TripRequest(days=2, budget=1200, mode="checkin", seed=99),
        normalize_weights({"quality": 10, "popularity": 8, "landmark": 5,
                           "cost_efficiency": 40, "budget_fit": 28,
                           "time_density": 6, "rest_comfort": 2, "local_flavor": 1},
                          cfg.weights),
        r_relax,
    )
    dinners = [
        it for d in plan_relax.days_plan for it in d.items
        if it.slot == "dinner" and it.poi is not None
    ]
    check(len(dinners) == len(plan_relax.days_plan),
          f"提前收工模式下每个工作日仍排入晚餐（实际 {len(dinners)}/{len(plan_relax.days_plan)}）")
    ok_lunch = all(
        it.start_time >= "11:30" for d in plan_relax.days_plan
        for it in d.items if it.slot == "lunch" and it.poi
    )
    check(ok_lunch, "午餐不早于 11:30")

    # 16. 回归：三种晚间偏好都能生成完整日程
    for ev in ("relax", "night_scene", "fine_dining"):
        r = apply_pace(dict(cfg.hard_rules),
                       {"daily_poi_max": 4, "play_hours_max": 9, "evening": ev},
                       "checkin")
        c, _ = stage1_candidates(db, r, [])
        pl = generate_trip(
            c, TripRequest(days=1, budget=1500, mode="checkin", seed=5),
            normalize_weights({"quality": 15, "popularity": 30, "landmark": 30,
                               "cost_efficiency": 10, "budget_fit": 10,
                               "time_density": 10, "rest_comfort": 0, "local_flavor": 0},
                              cfg.weights),
            r,
        )
        n_items = sum(1 for d in pl.days_plan for it in d.items if it.poi is not None)
        check(n_items >= 4, f"晚间偏好 {ev} 生成 {n_items} 个点位（≥4）")

    print(f"\n{'=' * 46}")
    print(f"通过 {_PASSED}/{_TOTAL} 项检查")
    print("=" * 46)
    db.close()
    sys.exit(0 if _PASSED == _TOTAL else 1)


if __name__ == "__main__":
    main()
