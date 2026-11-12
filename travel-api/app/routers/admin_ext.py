"""管理端扩展接口（P1）：运营统计 / 行程管理 / 标签字典 / 用户 / 系统运维。

设计原则：
- 全部基于现有表做查询聚合，不新增表、不改既有接口；
- 复用 admin.require_admin 鉴权，独立 router 便于后期拆分权限；
- 统计均在 SQL 层聚合，避免 N+1 查询。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    Poi, PoiEffectiveRule, PoiTag, PriceBandRule, Tag,
    Trip, TripDay, TripItem, User, UserAccount,
)
from app.routers.admin import require_admin
from app.services.amap_service import key_configured
from app.services.cache import forecast_cache, mode_cache, poi_cache, weather_cache
from app.services.image_service import POI_IMG_DIR, STATIC_DIR, provider_status
from app.services.trip_service import MODE_NAMES, trip_to_out
from app.services import mode_version_service, notify_service, price_service, tag_service
from app.schemas import (
    EffectiveRuleIn, GrayReleaseIn, PriceBandApplyIn, PriceBandIn,
    TagMergeIn, TagSynonymIn,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-ext"])

CATEGORY_NAME = {
    "scenic": "景点", "food": "美食", "hotel": "住宿",
    "leisure": "休闲", "study": "游学",
}


# ---------- 请求模型 ----------

class TagWriteIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=32)


class UserStatusIn(BaseModel):
    status: int = Field(..., ge=0, le=1)


# ---------- ① 运营数据概览 ----------

@router.get("/stats/overview")
def stats_overview(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """Dashboard 聚合：资源、行程、趋势、预算分布、热门 POI。"""
    # 资源分布
    cat_rows = db.query(Poi.category, func.count(Poi.id)).group_by(Poi.category).all()
    poi_total = db.query(func.count(Poi.id)).scalar() or 0
    poi_online = db.query(func.count(Poi.id)).filter(Poi.visitable.is_(True)).scalar() or 0
    avg_rating = db.query(func.avg(Poi.rating)).scalar() or 0

    # 行程总览
    trip_total = db.query(func.count(Trip.id)).scalar() or 0
    status_rows = db.query(Trip.status, func.count(Trip.id)).group_by(Trip.status).all()
    status_map = {s: n for s, n in status_rows}
    mode_rows = db.query(Trip.mode, func.count(Trip.id)).group_by(Trip.mode).all()
    avg_cost = db.query(func.avg(Trip.total_cost)).scalar() or 0
    avg_budget = db.query(func.avg(Trip.budget)).scalar() or 0

    # 近 7 日生成趋势（按自然日，Python 侧补齐空日期）
    today = datetime.utcnow().date()
    since = today - timedelta(days=6)
    recent = db.query(Trip.created_at).filter(Trip.created_at >= since).all()
    buckets = {(since + timedelta(days=i)).isoformat(): 0 for i in range(7)}
    for (created,) in recent:
        if created:
            key = created.date().isoformat()
            if key in buckets:
                buckets[key] += 1
    trend = [dict(date=k, count=v) for k, v in sorted(buckets.items())]

    # 预算带分布
    bounds = [(0, 500, "0-500"), (500, 1000, "500-1000"),
              (1000, 2000, "1000-2000"), (2000, 5000, "2000-5000"),
              (5000, 10 ** 9, "5000+")]
    budgets = [b for (b,) in db.query(Trip.budget).all()]
    budget_dist = [
        dict(label=label, count=sum(1 for b in budgets if lo <= b < hi))
        for lo, hi, label in bounds
    ]

    # 排进行程次数最多的 POI（反映算法偏好）
    top_rows = (
        db.query(TripItem.poi_id, func.count(TripItem.id).label("cnt"))
        .filter(TripItem.poi_id.isnot(None))
        .group_by(TripItem.poi_id)
        .order_by(func.count(TripItem.id).desc())
        .limit(8)
        .all()
    )
    poi_names = {pid: name for pid, name in db.query(Poi.id, Poi.name).all()}
    top_pois = [
        dict(poi_id=pid, name=poi_names.get(pid, f"#{pid}"), count=cnt)
        for pid, cnt in top_rows
    ]

    return dict(
        poi=dict(
            total=poi_total, visitable=poi_online,
            offline=poi_total - poi_online,
            online_rate=round(poi_online / poi_total, 3) if poi_total else 0,
            avg_rating=round(float(avg_rating), 2),
            by_category=[
                dict(code=c, name=CATEGORY_NAME.get(c, c), count=n)
                for c, n in cat_rows
            ],
        ),
        trip=dict(
            total=trip_total,
            saved=status_map.get("saved", 0),
            draft=status_map.get("draft", 0),
            avg_cost=round(float(avg_cost), 1),
            avg_budget=round(float(avg_budget), 1),
            by_mode=[
                dict(mode=m, name=MODE_NAMES.get(m, m), count=n)
                for m, n in mode_rows
            ],
        ),
        tags=dict(total=db.query(func.count(Tag.id)).scalar() or 0),
        users=dict(total=db.query(func.count(User.id)).scalar() or 0),
        trend=trend,
        budget_distribution=budget_dist,
        top_pois=top_pois,
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )


# ---------- ② 行程管理 ----------

@router.get("/trips")
def admin_list_trips(
    page: int = 1, page_size: int = 20,
    mode: str | None = None, status: str | None = None, keyword: str | None = None,
    db: Session = Depends(get_db), _: None = Depends(require_admin),
):
    q = db.query(Trip)
    if mode:
        q = q.filter(Trip.mode == mode)
    if status:
        q = q.filter(Trip.status == status)
    if keyword:
        q = q.filter(Trip.id.like(f"%{keyword}%"))
    total = q.count()
    rows = (
        q.order_by(Trip.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    # 一次性聚合每日条目数，避免逐行查询
    item_counts = dict(
        db.query(TripDay.trip_id, func.count(TripItem.id))
        .join(TripItem, TripItem.trip_day_id == TripDay.id)
        .group_by(TripDay.trip_id).all()
    )
    return dict(
        total=total, page=page, page_size=page_size,
        items=[dict(
            trip_id=t.id, mode=t.mode, mode_name=MODE_NAMES.get(t.mode, t.mode),
            days=t.days, budget=t.budget, total_cost=t.total_cost,
            status=t.status, seed=t.seed,
            preferences=t.preferences or [],
            poi_count=item_counts.get(t.id, 0),
            created_at=t.created_at.isoformat(timespec="seconds") if t.created_at else "",
        ) for t in rows],
    )


@router.get("/trips/{trip_id}")
def admin_trip_detail(trip_id: str, db: Session = Depends(get_db),
                      _: None = Depends(require_admin)):
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    return trip_to_out(db, trip)


@router.delete("/trips/{trip_id}")
def admin_delete_trip(trip_id: str, db: Session = Depends(get_db),
                      _: None = Depends(require_admin)):
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    db.delete(trip)  # days_plan / items 由 ORM cascade 删除
    db.commit()
    return dict(message="已删除", trip_id=trip_id)


# ---------- ③ 标签字典 ----------

@router.get("/tags")
def admin_list_tags(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    counts = dict(
        db.query(PoiTag.tag_id, func.count(PoiTag.poi_id))
        .group_by(PoiTag.tag_id).all()
    )
    rows = db.query(Tag).order_by(Tag.id).all()
    return dict(
        total=len(rows),
        items=[dict(id=t.id, code=t.code, name=t.name,
                    poi_count=counts.get(t.id, 0)) for t in rows],
    )


@router.post("/tags")
def admin_create_tag(body: TagWriteIn, db: Session = Depends(get_db),
                     _: None = Depends(require_admin)):
    if db.query(Tag).filter(Tag.code == body.code).first():
        raise HTTPException(400, f"标签编码 {body.code} 已存在")
    t = Tag(code=body.code, name=body.name)
    db.add(t)
    db.commit()
    return dict(id=t.id, message="已创建")


@router.put("/tags/{tag_id}")
def admin_update_tag(tag_id: int, body: TagWriteIn,
                     db: Session = Depends(get_db), _: None = Depends(require_admin)):
    t = db.get(Tag, tag_id)
    if not t:
        raise HTTPException(404, "标签不存在")
    dup = db.query(Tag).filter(Tag.code == body.code, Tag.id != tag_id).first()
    if dup:
        raise HTTPException(400, f"标签编码 {body.code} 已被占用")
    t.code, t.name = body.code, body.name
    db.commit()
    return dict(id=t.id, message="已更新")


@router.delete("/tags/{tag_id}")
def admin_delete_tag(tag_id: int, db: Session = Depends(get_db),
                     _: None = Depends(require_admin)):
    t = db.get(Tag, tag_id)
    if not t:
        raise HTTPException(404, "标签不存在")
    linked = db.query(func.count(PoiTag.tag_id)).filter(PoiTag.tag_id == tag_id).scalar() or 0
    db.query(PoiTag).filter(PoiTag.tag_id == tag_id).delete()
    db.delete(t)
    db.commit()
    poi_cache.invalidate_prefix("pois:")
    return dict(message="已删除", unlinked_pois=linked)


# ---------- ④ 用户管理 ----------

@router.get("/users")
def admin_list_users(page: int = 1, page_size: int = 20,
                     db: Session = Depends(get_db), _: None = Depends(require_admin)):
    total = db.query(func.count(User.id)).scalar() or 0
    rows = (
        db.query(User).order_by(User.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    trip_counts = dict(
        db.query(Trip.user_id, func.count(Trip.id))
        .filter(Trip.user_id.isnot(None))
        .group_by(Trip.user_id).all()
    )
    account_names = dict(db.query(UserAccount.user_id, UserAccount.username).all())
    return dict(
        total=total, page=page, page_size=page_size,
        items=[dict(
            id=u.id,
            openid=u.openid[:8] + "***" if u.openid else "",
            account=account_names.get(u.id, ""),
            nickname=u.nickname or "微信用户",
            role=u.role, status=u.status,
            trip_count=trip_counts.get(u.id, 0),
            created_at=u.created_at.isoformat(timespec="seconds") if u.created_at else "",
        ) for u in rows],
    )


@router.patch("/users/{user_id}/status")
def admin_toggle_user(user_id: int, body: UserStatusIn,
                      db: Session = Depends(get_db), _: None = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    u.status = body.status
    db.commit()
    return dict(id=u.id, status=u.status,
                message="已启用" if body.status else "已禁用")


# ---------- ⑤ 系统运维 ----------

@router.get("/system/health")
def admin_system_health(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """健康检查：数据库连通、表数量、缓存条目、数据量。"""
    db_ok = db.execute(text("SELECT 1")).scalar() == 1
    table_count = db.execute(
        text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = :db"),
        {"db": settings.DB_NAME},
    ).scalar() or 0
    return dict(
        status="ok" if db_ok else "error",
        database=dict(
            host=settings.DB_HOST, port=settings.DB_PORT, name=settings.DB_NAME,
            connected=db_ok, tables=int(table_count),
            poi_count=db.query(func.count(Poi.id)).scalar() or 0,
            trip_count=db.query(func.count(Trip.id)).scalar() or 0,
        ),
        cache=dict(
            mode_entries=len(mode_cache._store),   # 运维观测用
            poi_entries=len(poi_cache._store),
            weather_entries=len(weather_cache._store),
            forecast_entries=len(forecast_cache._store),
        ),
        features=dict(
            route_api=settings.FEATURE_ROUTE_API,
            route_api_key=settings.route_api_configured,
            ai_polish=settings.FEATURE_AI_POLISH,
            ai_polish_configured=settings.ai_polish_configured,
            subscribe_msg=settings.FEATURE_SUBSCRIBE_MSG,
            subscribe_configured=settings.subscribe_configured,
            geo_locate=settings.FEATURE_GEO_LOCATE,
            preset_routes=settings.FEATURE_PRESET_ROUTES,
            # G4：真实 code2session + 自签 JWT 的运行态观测（不含任何密钥）
            mock_login=settings.MOCK_LOGIN,
            auth_mode="mock_code2session(dev)" if settings.MOCK_LOGIN else "real_code2session",
            jwt_alg=settings.JWT_ALG,
            jwt_expire_hours=settings.JWT_EXPIRE_HOURS,
            jwt_secret=settings.jwt_configured,
            wechat_credentials=settings.wechat_configured,
            legacy_hmac=settings.ALLOW_LEGACY_HMAC_TOKEN,
            weather_provider="open-meteo",   # 天气数据源：Open-Meteo 免密钥公开 API
            amap_geocode=key_configured(),   # 高德仅用于逆地理 / IP 地名解析
            forecast_15d=True,
        ),
        images=dict(
            total_pois=int(db.query(func.count(Poi.id)).scalar() or 0),
            # JSON 列在 SQL 层不好过滤，Python 侧统计更稳妥
            with_images=sum(1 for p in db.query(Poi.images).all() if (p.images or [])),
            with_meta=sum(1 for p in db.query(Poi.image_meta).all() if (p.image_meta or [])),
            static_dir=str(STATIC_DIR),
            files=len(os.listdir(POI_IMG_DIR)) if os.path.isdir(POI_IMG_DIR) else 0,
            providers=provider_status(),
        ),
    )


@router.post("/system/cache/clear")
def admin_clear_cache(_: None = Depends(require_admin)):
    n_mode = mode_cache.invalidate_prefix("")
    n_poi = poi_cache.invalidate_prefix("")
    n_weather = weather_cache.invalidate_prefix("")
    n_forecast = forecast_cache.invalidate_prefix("")
    return dict(
        message="缓存已清空",
        cleared_mode=n_mode,
        cleared_poi=n_poi,
        cleared_weather=n_weather,
        cleared_forecast=n_forecast,
    )


# ---------- ⑥ A2 标签同义词归并 ----------

@router.get("/tags/synonyms")
def list_tag_synonyms(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    return dict(items=tag_service.list_synonyms(db))


@router.post("/tags/synonyms")
def create_tag_synonym(body: TagSynonymIn, db: Session = Depends(get_db),
                       _: None = Depends(require_admin)):
    try:
        return tag_service.create_synonym(db, body.alias, body.canonical_code, body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/tags/synonyms/{synonym_id}")
def delete_tag_synonym(synonym_id: int, db: Session = Depends(get_db),
                       _: None = Depends(require_admin)):
    if not tag_service.delete_synonym(db, synonym_id):
        raise HTTPException(404, "同义词不存在")
    return dict(message="已删除")


@router.post("/tags/merge")
def merge_tags(body: TagMergeIn, db: Session = Depends(get_db),
               _: None = Depends(require_admin)):
    try:
        return tag_service.merge_tag(db, body.from_code, body.to_code)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------- ⑦ A3 价格分档 / 生效时间管理 ----------

def _band_out(r: PriceBandRule) -> dict:
    return dict(id=r.id, name=r.name or "", min_price=r.min_price, max_price=r.max_price,
                price_level=r.price_level, enabled=r.enabled,
                description=r.description or "")


@router.get("/price-bands")
def list_price_bands(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    rows = db.query(PriceBandRule).order_by(PriceBandRule.min_price.asc()).all()
    return dict(items=[_band_out(r) for r in rows])


@router.post("/price-bands")
def create_price_band(body: PriceBandIn, db: Session = Depends(get_db),
                      _: None = Depends(require_admin)):
    if body.min_price >= body.max_price:
        raise HTTPException(400, "min_price 必须小于 max_price")
    row = PriceBandRule(**body.model_dump())
    db.add(row)
    db.commit()
    price_service.invalidate()
    return _band_out(row)


@router.put("/price-bands/{band_id}")
def update_price_band(band_id: int, body: PriceBandIn,
                      db: Session = Depends(get_db), _: None = Depends(require_admin)):
    row = db.get(PriceBandRule, band_id)
    if row is None:
        raise HTTPException(404, "分档规则不存在")
    if body.min_price >= body.max_price:
        raise HTTPException(400, "min_price 必须小于 max_price")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    db.commit()
    price_service.invalidate()
    return _band_out(row)


@router.delete("/price-bands/{band_id}")
def delete_price_band(band_id: int, db: Session = Depends(get_db),
                      _: None = Depends(require_admin)):
    row = db.get(PriceBandRule, band_id)
    if row is None:
        raise HTTPException(404, "分档规则不存在")
    db.delete(row)
    db.commit()
    price_service.invalidate()
    return dict(message="已删除")


@router.post("/price-bands/apply")
def apply_price_bands(body: PriceBandApplyIn, db: Session = Depends(get_db),
                      _: None = Depends(require_admin)):
    return price_service.apply_bands(db, body.category)


@router.get("/pois/{poi_id}/effective-rules")
def list_effective_rules(poi_id: int, db: Session = Depends(get_db),
                         _: None = Depends(require_admin)):
    rows = (
        db.query(PoiEffectiveRule)
        .filter(PoiEffectiveRule.poi_id == poi_id)
        .order_by(PoiEffectiveRule.valid_from.desc(), PoiEffectiveRule.id.desc())
        .all()
    )
    return dict(items=[dict(
        id=r.id, poi_id=r.poi_id, kind=r.kind, value=r.value or {},
        valid_from=r.valid_from or "", valid_to=r.valid_to or "",
        note=r.note or "", enabled=r.enabled,
    ) for r in rows])


@router.post("/effective-rules")
def create_effective_rule(body: EffectiveRuleIn, db: Session = Depends(get_db),
                          _: None = Depends(require_admin)):
    if db.get(Poi, body.poi_id) is None:
        raise HTTPException(404, "POI 不存在")
    if body.kind == "price" and body.value.get("price") is None:
        raise HTTPException(400, "price 类型规则需提供 value.price")
    if body.kind == "hours" and not isinstance(body.value.get("open_time"), list):
        raise HTTPException(400, "hours 类型规则需提供 value.open_time 列表")
    row = PoiEffectiveRule(**body.model_dump())
    db.add(row)
    db.commit()
    price_service.invalidate()
    return dict(id=row.id, message="已创建，将在生效区间自动应用")


@router.delete("/effective-rules/{rule_id}")
def delete_effective_rule(rule_id: int, db: Session = Depends(get_db),
                          _: None = Depends(require_admin)):
    row = db.get(PoiEffectiveRule, rule_id)
    if row is None:
        raise HTTPException(404, "生效规则不存在")
    db.delete(row)
    db.commit()
    price_service.invalidate()
    return dict(message="已删除")


# ---------- ⑧ A4 权重版本 / 回滚 / 灰度 ----------

@router.get("/mode-configs/{mode}/versions")
def list_mode_versions(mode: str, db: Session = Depends(get_db),
                       _: None = Depends(require_admin)):
    return dict(mode=mode, items=mode_version_service.list_versions(db, mode))


@router.post("/mode-configs/{mode}/rollback/{version}")
def rollback_mode_config(mode: str, version: int, db: Session = Depends(get_db),
                         _: None = Depends(require_admin)):
    return mode_version_service.rollback(db, mode, version)


@router.post("/mode-configs/{mode}/gray")
def create_gray_release(mode: str, body: GrayReleaseIn,
                        db: Session = Depends(get_db), _: None = Depends(require_admin)):
    return mode_version_service.create_candidate(
        db, mode, weights=body.weights, hard_rules=body.hard_rules,
        description=body.description, slot_template=body.slot_template,
        traffic_pct=body.traffic_pct, note=body.note,
    )


@router.post("/mode-configs/{mode}/gray/{version}/promote")
def promote_gray_release(mode: str, version: int, db: Session = Depends(get_db),
                         _: None = Depends(require_admin)):
    return mode_version_service.promote_candidate(db, mode, version)


@router.delete("/mode-configs/{mode}/gray/{version}")
def delete_gray_release(mode: str, version: int, db: Session = Depends(get_db),
                        _: None = Depends(require_admin)):
    if not mode_version_service.delete_candidate(db, mode, version):
        raise HTTPException(404, "灰度候选不存在")
    return dict(message="已删除灰度候选")


# ---------- ⑨ T8 订阅提醒运维 ----------

@router.get("/reminders")
def admin_list_reminders(status: str | None = None, limit: int = 100,
                         db: Session = Depends(get_db),
                         _: None = Depends(require_admin)):
    return notify_service.list_reminders(db, status=status, limit=min(limit, 500))


@router.post("/reminders/run")
def admin_run_reminders(db: Session = Depends(get_db),
                        _: None = Depends(require_admin)):
    return notify_service.run_due(db)
