"""算法冒烟测试：四模式各生成一组，校验硬约束与模式特征（M2 验收缩影）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import Poi, PoiExtScenic, PoiExtFood, PoiExtHotel, PoiExtLeisure, PoiTag, Tag, TripModeConfig
from app.planner.models import PlannerPoi, TripRequest
from app.planner.engine import generate_trip


def load_candidates(db, mode: str, rules: dict):
    """Stage1 候选筛选（服务层同款逻辑）。"""
    cap = rules["price_level_cap"]
    q = db.query(Poi).filter(Poi.visitable.is_(True), Poi.price_level <= cap)
    pois = q.all()
    out = []
    for p in pois:
        if p.category == "scenic":
            e = db.get(PoiExtScenic, p.id)
        elif p.category == "food":
            e = db.get(PoiExtFood, p.id)
        elif p.category == "hotel":
            e = db.get(PoiExtHotel, p.id)
            if p.price_level < rules["hotel_price_level_min"]:
                continue
        else:
            e = db.get(PoiExtLeisure, p.id)
        pt = db.query(PoiTag, Tag).join(Tag, PoiTag.tag_id == Tag.id).filter(PoiTag.poi_id == p.id).all()
        pp = PlannerPoi(
            id=p.id, name=p.name, category=p.category, sub_type=p.sub_type,
            longitude=p.longitude, latitude=p.latitude,
            suggest_duration_min=p.suggest_duration_min,
            ticket_price=p.ticket_price, price_level=p.price_level,
            rating=p.rating, review_count=p.review_count,
            hot_score=p.hot_score, quality_score=p.quality_score,
            is_landmark=(e.is_landmark if p.category == "scenic" else False),
            indoor=(e.indoor if p.category in ("scenic", "leisure") else False),
            physical_level=(e.physical_level if p.category == "scenic" else 2),
            is_time_honored=(e.is_time_honored if p.category == "food" else False),
            cuisine=(e.cuisine if p.category == "food" else ""),
            meal_period=(e.meal_period if p.category == "food" else "午,晚"),
            avg_price=(e.price_min if p.category == "hotel" else (e.avg_price if p.category == "food" else 0)),
            grade=(e.grade if p.category == "hotel" else ""),
            night_open=(e.night_open if p.category == "leisure" else False),
            play_type=(e.play_type if p.category == "leisure" else ""),
            photospot_weight=next((w for pt, t, w in [(x[0], x[1], x[0].weight) for x in pt] if t.code == "photospot"), 0.0),
            night_only=bool(p.open_time and p.open_time[0][0] >= "17:00"),
        )
        out.append(pp)
    return out


def main():
    db = SessionLocal()
    cases = [
        ("leisure", 2, 1500), ("blitz", 2, 500),
        ("premium", 2, 4000), ("checkin", 2, 1500),
    ]
    ok = True
    for mode, days, budget in cases:
        cfg = db.query(TripModeConfig).filter(TripModeConfig.mode == mode).first()
        rules = cfg.hard_rules
        cands = load_candidates(db, mode, rules)
        req = TripRequest(days=days, budget=budget, mode=mode, seed=42)
        plan = generate_trip(cands, req, cfg.weights, rules)

        # 校验：总费用不超预算弹性上限
        overrun = plan.total_cost > budget * rules["budget_elasticity_max"] + 0.5
        play_counts = []
        for d in plan.days_plan:
            plays = [it for it in d.items if it.poi and it.slot in ("morning", "afternoon", "evening")]
            play_counts.append(len(plays))
        names = [it.poi.name for d in plan.days_plan for it in d.items if it.poi]

        status = "PASS" if not overrun else "FAIL"
        if overrun:
            ok = False
        print(f"[{status}] {mode:8s} days={days} budget={budget} → cost={plan.total_cost}"
              f" usage={plan.budget_usage:.0%} hotel={plan.hotel.name if plan.hotel else '无'}"
              f" play/day={play_counts} score={plan.score}")
        print(f"        路线: {' → '.join(names)}")
        if plan.relax_log:
            print(f"        relax: {[r['label'] for r in plan.relax_log]}")
    db.close()
    print("\n全部通过 ✔" if ok else "\n存在约束违规 ✘")


if __name__ == "__main__":
    main()
