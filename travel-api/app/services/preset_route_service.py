"""预设主题路线服务：列表 / 详情 / date_gate 判定 / 生成时的保底站点解析（G7 / T9 / A7）。

对应方案：
- 5.8(3) 纯展示模式：GET /preset-routes/{code} 直接渲染逐站讲解 + 研学任务卡，零算法开销
- 5.8(1) 注入方式：把 must_visit 站点按 seq 预占槽位，剩余槽位走正常贪心装箱
- 5.8(2) 日期感知闸门：不满足时自动降级 / 替换并写 relax_log，绝不报错
- 5.8(4) 拼接能力：days=1 + preset_route_code + mode → 半天游学 + 半天自由生成
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Poi, PoiExtStudy, PresetRoute, PresetRouteStop
from app.planner.models import PlannerPoi
from app.services.image_policy import split_visible_images
from app.planner.preset_routes import (
    InjectedStop, as_dict, evaluate_gates, parse_visit_date, route_day_summary,
)


THEME_NAMES = {
    "study_tour": "游学", "culture": "人文", "eco": "生态", "night": "夜游",
}


def _poi_brief(db: Session, poi_id: int | None) -> dict:
    if not poi_id:
        return {}
    p = db.get(Poi, poi_id)
    if not p:
        return {}
    ext = db.get(PoiExtStudy, p.id)
    return dict(
        poi_id=p.id, name=p.name, category=p.category, sub_type=p.sub_type,
        address=p.address, longitude=p.longitude, latitude=p.latitude,
        open_time=p.open_time or [], suggest_duration_min=p.suggest_duration_min,
        ticket_price=p.ticket_price, price_level=p.price_level, rating=p.rating,
        images=split_visible_images(p.images, p.image_meta)[0],
        visit_policy=(ext.visit_policy if ext else ""),
        reservation_channel=(ext.reservation_channel if ext else ""),
        study_theme=(ext.study_theme if ext else ""),
    )


def _route_query(db: Session, include_disabled: bool = False):
    q = db.query(PresetRoute)
    if not include_disabled:
        q = q.filter(PresetRoute.enabled.is_(True))
    return q


def _route_meta(route: PresetRoute, db: Session, visit_date: date) -> dict:
    stops_n = db.query(PresetRouteStop).filter(
        PresetRouteStop.route_id == route.id,
        PresetRouteStop.is_addon.is_(False),
    ).count()
    unverified = [s.get("item", "") for s in (route.sources or []) if not s.get("verified", True)]
    return dict(
        code=route.code, title=route.title, subtitle=route.subtitle,
        theme=route.theme, theme_name=THEME_NAMES.get(route.theme, route.theme),
        target_group=route.target_group,
        duration_hours=route.duration_hours,
        full_day_hours=round(route.duration_hours + 3.0, 1),
        season_window=route.season_window or {},
        difficulty=route.difficulty, enabled=route.enabled, version=route.version,
        summary=route.summary, cover_image=route.cover_image or "",
        reservation_note=route.reservation_note,
        transit_note=route.transit_note,
        mode_tips=route.mode_tips or {},
        sources=route.sources or [],
        policy_checked_at=route.policy_checked_at or "",
        unverified_sources=unverified,
        stop_count=stops_n,
        day=route_day_summary(visit_date),
        visit_date=visit_date.isoformat(),
        reservation_required=bool(route.reservation_note),
    )


def list_routes(
    db: Session,
    theme: str | None = None,
    target_group: str | None = None,
    visit_date: str | date | None = None,
    include_disabled: bool = False,
) -> list[dict]:
    """#14：线路列表（可按主题/人群过滤，带日期概览）。"""
    d = parse_visit_date(visit_date)
    q = _route_query(db, include_disabled)
    if theme:
        q = q.filter(PresetRoute.theme == theme)
    if target_group:
        q = q.filter(PresetRoute.target_group.like(f"%{target_group}%"))
    rows = q.order_by(PresetRoute.id.asc()).all()
    return [_route_meta(r, db, d) for r in rows]


def _resolve_stop(db: Session, stop: PresetRouteStop, visit_date) -> dict:
    """单站：date_gate 判定 + 组装展示 / 注入所需的全部字段。"""
    v = evaluate_gates(
        stop.date_gate, visit_date,
        stay_min=stop.stay_min, poi_id=stop.poi_id,
        fallback_poi_id=stop.fallback_poi_id,
        degrade_text=stop.degrade_text, degrade_stay_min=stop.degrade_stay_min,
        narration_text=stop.narration_text,
    )
    eff_id = v.effective_poi_id or stop.poi_id
    brief = _poi_brief(db, eff_id)
    original = _poi_brief(db, stop.poi_id)
    gate = as_dict(v)
    gate["effective_name"] = brief.get("name", "")
    gate["original_name"] = original.get("name", "")
    gate["replaced"] = eff_id != stop.poi_id

    tasks = [dict(stop.task_card)] if stop.task_card else []
    for action in v.actions:
        tasks.append(dict(title="出行前必办", type="提醒", content=action))

    return dict(
        seq=stop.seq, poi_id=stop.poi_id, effective_poi_id=eff_id,
        name=brief.get("name", original.get("name", "")),
        original_name=original.get("name", ""),
        sub_type=brief.get("sub_type", ""),
        address=brief.get("address", ""),
        longitude=brief.get("longitude"), latitude=brief.get("latitude"),
        image=(brief.get("images") or [None])[0],
        visit_policy=brief.get("visit_policy", ""),
        stay_min=stop.stay_min, effective_stay_min=v.effective_stay_min or stop.stay_min,
        walk_in_min=stop.walk_in_min,
        slot=stop.slot, must_visit=stop.must_visit, is_addon=stop.is_addon,
        narration_title=stop.narration_title,
        narration_text=v.effective_narration or stop.narration_text,
        original_narration=stop.narration_text,
        task_cards=tasks, photo_tip=stop.photo_tip,
        date_gate=stop.date_gate or [], gate=gate,
    )


def get_route(
    db: Session, code: str,
    visit_date: str | date | None = None,
    include_addon: bool = False,
    include_disabled: bool = False,
) -> dict:
    """#14：线路详情（逐站讲解 / 任务卡 / date_gate 结论）。"""
    q = _route_query(db, include_disabled).filter(PresetRoute.code == code)
    route = q.first()
    if route is None:
        raise HTTPException(404, f"预设路线不存在或已停用: {code}")
    d = parse_visit_date(visit_date)
    meta = _route_meta(route, db, d)
    sq = db.query(PresetRouteStop).filter(PresetRouteStop.route_id == route.id)
    if not include_addon:
        sq = sq.filter(PresetRouteStop.is_addon.is_(False))
    stops = [_resolve_stop(db, s, d) for s in sq.order_by(PresetRouteStop.seq).all()]

    # 线路级汇总：总时长、步行衔接、预约提醒、降级站点数
    active = [s for s in stops if s["must_visit"]]
    total_walk = sum(s["walk_in_min"] for s in active)
    total_stay = sum(s["effective_stay_min"] for s in active)
    degraded = [s for s in stops if s["gate"]["status"] in ("degraded", "replaced")]
    notes: list[str] = []
    for s in stops:
        notes.extend(s["gate"]["notes"])
    reservations = [s["gate"]["reservation"] for s in stops if s["gate"]["reservation"]]

    meta.update(dict(
        stops=stops,
        total_stay_min=total_stay,
        total_walk_min=total_walk,
        estimated_minutes=total_stay + total_walk,
        degraded_count=len(degraded),
        gate_notes=list(dict.fromkeys(notes)),  # 去重保持顺序
        reservation=reservations[0] if reservations else None,
        addon_stops=[] if include_addon else [
            _resolve_stop(db, s, d) for s in
            db.query(PresetRouteStop).filter(
                PresetRouteStop.route_id == route.id,
                PresetRouteStop.is_addon.is_(True),
            ).order_by(PresetRouteStop.seq).all()
        ],
    ))
    return meta


@dataclass
class ResolvedRoute:
    """生成接口用：解析后的线路 + 注入站点 + 降级提示。"""
    brief: dict
    stops: list[InjectedStop] = field(default_factory=list)
    relax_notes: list[str] = field(default_factory=list)


def resolve_for_generation(
    db: Session, code: str, visit_date: str | date | None,
    include_addon: bool = False,
) -> ResolvedRoute:
    """把线路翻译成引擎可注入的保底站点序列（方案 5.8 第 1/2/5 条）。

    - 只取 must_visit 站点作为保底（可选站仍可被贪心自由选到）
    - date_gate 降级 → 缩短停留 / 换站点 / 追加预约任务，并写 relax_notes
    - 全程步行：walk_in_min 直接用于通勤，不套 speed_kmh
    """
    detail = get_route(db, code, visit_date, include_addon=include_addon)
    stops: list[InjectedStop] = []
    notes: list[str] = []

    for s in detail["stops"]:
        # 勾选全天深度版时，加段站点也升级为保底站；弹性站仍留给贪心自由选点
        if not s["must_visit"] and not (include_addon and s["is_addon"]):
            continue
        p = db.get(Poi, s["effective_poi_id"])
        if p is None:
            continue
        stay = s["effective_stay_min"] or s["stay_min"]
        poi = PlannerPoi(
            id=p.id, name=p.name, category="scenic",  # 3.2：study 装箱时按 scenic 入池
            sub_type=p.sub_type or "游学点",
            longitude=p.longitude, latitude=p.latitude,
            suggest_duration_min=stay,
            ticket_price=float(p.ticket_price or 0),
            price_level=int(p.price_level or 1),
            rating=float(p.rating or 4.5),
            review_count=int(p.review_count or 0),
            hot_score=float(p.hot_score or 0.55),
            quality_score=float(p.quality_score or 0.85),
            physical_level=1, indoor=False,
            images=split_visible_images(p.images, p.image_meta)[0],
        )
        stops.append(InjectedStop(
            poi=poi, seq=s["seq"], stay_min=stay,
            walk_in_min=s["walk_in_min"], slot=s["slot"],
            narration_title=s["narration_title"],
            narration_text=s["narration_text"],
            task_card=(s["task_cards"][0] if s["task_cards"] else {}),
            photo_tip=s["photo_tip"],
            gate_status=s["gate"]["status"],
            gate_notes=s["gate"]["notes"],
            must_visit=s["must_visit"], is_addon=s["is_addon"],
        ))
        for n in s["gate"]["notes"]:
            if n not in notes:
                notes.append(n)

    brief = {k: v for k, v in detail.items() if k not in ("stops", "addon_stops")}
    brief["stops"] = detail["stops"]          # 逐站讲解/任务卡，原样回给前端
    brief["addon_stops"] = detail["addon_stops"]
    return ResolvedRoute(brief=brief, stops=stops, relax_notes=notes)


# ---------------- A7 管理端 ----------------

def admin_list_routes(db: Session) -> list[dict]:
    rows = _route_query(db, include_disabled=True).order_by(PresetRoute.id).all()
    out = []
    for r in rows:
        all_stops = db.query(PresetRouteStop).filter(
            PresetRouteStop.route_id == r.id).count()
        out.append(dict(
            id=r.id, code=r.code, title=r.title, theme=r.theme,
            target_group=r.target_group, enabled=r.enabled,
            duration_hours=r.duration_hours, version=r.version,
            stop_count=all_stops,
            policy_checked_at=r.policy_checked_at or "",
            unverified_count=len([s for s in (r.sources or []) if not s.get("verified", True)]),
        ))
    return out


def set_route_enabled(db: Session, code: str, enabled: bool,
                      policy_checked_at: str | None = None) -> dict:
    """A7 季节性开关 + 政策周更校验日期。"""
    r = db.query(PresetRoute).filter(PresetRoute.code == code).first()
    if r is None:
        raise HTTPException(404, f"预设路线不存在: {code}")
    r.enabled = bool(enabled)
    if policy_checked_at:
        r.policy_checked_at = policy_checked_at
    db.commit()
    return dict(code=r.code, enabled=r.enabled,
                policy_checked_at=r.policy_checked_at or "")
