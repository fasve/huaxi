"""游客端四模式对比（PC 专属增强）。

同一组需求一次算出四种模式的行程摘要，**不落库**（不产生草稿行程记录，
避免污染运营统计）。算法与 /trips/generate 完全同源：同一 Stage1 候选筛选、
同一权重配置、同一装箱引擎，只有模式不同，因此差异可直接归因于模式权重。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.planner.engine import generate_trip
from app.planner.models import MODE_NAMES, TripRequest
from app.services.poi_service import stage1_candidates
from app.services.trip_service import get_mode_cfg

router = APIRouter(prefix="/api/v1/trips", tags=["trips-compare"])

MODES = ("leisure", "blitz", "premium", "checkin")


class CompareIn(BaseModel):
    days: int = Field(2, ge=1, le=7)
    budget: float = Field(..., gt=0)
    preferences: list[str] = []
    party_type: str = ""
    seed: int | None = Field(None, ge=0)


@router.post("/compare")
def compare_modes(body: CompareIn, db: Session = Depends(get_db)):
    results = []
    for mode in MODES:
        cfg = get_mode_cfg(db, mode)
        rules = dict(cfg.hard_rules)
        weights = dict(cfg.weights)
        cands, _ = stage1_candidates(db, rules, body.preferences)
        if not cands:  # 候选为空时与生成接口保持一致的放宽策略
            rules["price_level_cap"] = 5
            cands, _ = stage1_candidates(db, rules, body.preferences)

        req = TripRequest(
            days=body.days, budget=body.budget, mode=mode,
            preferences=body.preferences, party_type=body.party_type,
            seed=body.seed if body.seed is not None else 0,
        )
        plan = generate_trip(cands, req, weights, rules)

        poi_count = sum(1 for d in plan.days_plan for it in d.items if it.poi is not None)
        results.append(dict(
            mode=mode,
            mode_name=MODE_NAMES.get(mode, mode),
            total_cost=plan.total_cost,
            budget_usage=plan.budget_usage,
            score=plan.score,
            poi_count=poi_count,
            poi_per_day=round(poi_count / max(1, len(plan.days_plan)), 1),
            hotel=plan.hotel.name if plan.hotel else "",
            hotel_nights=plan.hotel_nights,
            free_poi_ratio=round(
                sum(1 for d in plan.days_plan for it in d.items
                    if it.poi is not None and it.cost == 0) / max(1, poi_count), 2
            ),
            relax_count=len(plan.relax_log),
            days_plan=[dict(
                day_index=d.day_index, theme=d.theme,
                poi_names=[it.poi.name for it in d.items if it.poi is not None],
            ) for d in plan.days_plan],
        ))

    return dict(
        request=dict(days=body.days, budget=body.budget,
                     preferences=body.preferences, party_type=body.party_type,
                     seed=body.seed),
        results=results,
        note="对比结果不落库，仅用于展示模式差异；如需保存请在单模式页生成行程。",
    )
