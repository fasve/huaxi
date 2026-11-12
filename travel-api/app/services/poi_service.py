"""资源服务：列表/详情查询、Stage1 候选筛选、POI→PlannerPoi 转换、管理端 CRUD。"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Poi, PoiExtScenic, PoiExtFood, PoiExtHotel, PoiExtLeisure, PoiExtStudy,
    PoiTag, Tag,
)
from app.planner.models import PlannerPoi
from app.services import price_service, tag_service
from app.services.image_policy import split_visible_images


# ---------- 查询 ----------

def query_pois(
    db: Session,
    category: str | None = None,
    tag_codes: list[str] | None = None,
    max_price_level: int | None = None,
    min_rating: float | None = None,
    keyword: str | None = None,
    visitable_only: bool | None = True,
    page: int = 1,
    page_size: int = 20,
):
    """visitable_only 三态：True 只看上架 / False 只看下架 / None 全部。"""
    q = db.query(Poi)
    if visitable_only is True:
        q = q.filter(Poi.visitable.is_(True))
    elif visitable_only is False:
        q = q.filter(Poi.visitable.is_(False))
    if category:
        q = q.filter(Poi.category == category)
    if max_price_level:
        q = q.filter(Poi.price_level <= max_price_level)
    if min_rating:
        q = q.filter(Poi.rating >= min_rating)
    if keyword:
        q = q.filter(Poi.name.like(f"%{keyword}%") | Poi.address.like(f"%{keyword}%"))
    if tag_codes:
        # A2：别名归并为标准标签后再筛选
        resolved = tag_service.resolve_codes(db, tag_codes)
        if resolved:
            q = q.join(PoiTag, PoiTag.poi_id == Poi.id).join(Tag, Tag.id == PoiTag.tag_id) \
                 .filter(Tag.code.in_(resolved)).distinct()
        else:
            q = q.filter(Poi.id < 0)   # 别名全部无效：返回空集而非全量
    total = q.count()
    rows = (
        q.order_by(Poi.hot_score.desc(), Poi.rating.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return total, rows


def poi_to_out(p: Poi, db: Session) -> dict:
    """主表 + 扩展 + 标签 → 响应 dict（含 A3 生效价格 / 开放时间）。"""
    tags = (
        db.query(Tag.code).join(PoiTag, PoiTag.tag_id == Tag.id)
        .filter(PoiTag.poi_id == p.id).all()
    )
    eff_price, eff_level = price_service.effective_price(db, p)
    eff_open = price_service.effective_open_time(db, p)
    ext: dict = {}
    if p.category == "scenic":
        e = db.get(PoiExtScenic, p.id)
        if e:
            ext = dict(level=e.level, need_reservation=e.need_reservation,
                       best_season=e.best_season, indoor=e.indoor,
                       physical_level=e.physical_level, is_landmark=e.is_landmark)
    elif p.category == "food":
        e = db.get(PoiExtFood, p.id)
        if e:
            ext = dict(cuisine=e.cuisine, signature=e.signature, avg_price=e.avg_price,
                       meal_period=e.meal_period, is_time_honored=e.is_time_honored)
    elif p.category == "hotel":
        e = db.get(PoiExtHotel, p.id)
        if e:
            ext = dict(grade=e.grade, star=e.star, facility_tags=e.facility_tags,
                       price_min=e.price_min, with_breakfast=e.with_breakfast)
    elif p.category == "leisure":
        e = db.get(PoiExtLeisure, p.id)
        if e:
            ext = dict(play_type=e.play_type, night_open=e.night_open, indoor=e.indoor)
    elif p.category == "study":
        # 游学点（G7）：所属单位、预约渠道、入校政策与研学主题
        e = db.get(PoiExtStudy, p.id)
        if e:
            ext = dict(org=e.org, reservation_channel=e.reservation_channel,
                       visit_policy=e.visit_policy, season_window=e.season_window,
                       study_theme=e.study_theme)
    # 图片策略：只保留管理员上传的图（其余来源一律不对外）
    _imgs, _metas = split_visible_images(p.images, p.image_meta)
    return dict(
        id=p.id, poi_id=p.id, name=p.name, category=p.category, sub_type=p.sub_type,
        address=p.address, longitude=p.longitude, latitude=p.latitude,
        district=p.district, open_time=eff_open,
        suggest_duration_min=p.suggest_duration_min, ticket_price=eff_price,
        price_level=(eff_level or p.price_level), rating=p.rating, review_count=p.review_count,
        hot_score=p.hot_score, quality_score=p.quality_score, visitable=p.visitable,
        images=_imgs,
        image_meta=_metas,
        tags=[t[0] for t in tags], ext=ext,
    )


# ---------- Stage1 候选筛选 + 转换（方案 5.2） ----------

def stage1_candidates(
    db: Session,
    rules: dict,
    preferences: list[str] | None = None,
) -> tuple[list[PlannerPoi], list[str]]:
    """SQL 粗筛 + 偏好/保底过滤；返回 (候选, relax_notes)。"""
    notes: list[str] = []
    cap = rules.get("price_level_cap", 5)

    q = db.query(Poi).filter(Poi.visitable.is_(True), Poi.price_level <= cap)
    rows = q.all()

    # 预取标签命中
    tag_rows = (
        db.query(PoiTag.poi_id, Tag.code, PoiTag.weight)
        .join(Tag, Tag.id == PoiTag.tag_id).all()
    )
    tags_by_poi: dict[int, dict[str, float]] = {}
    for poi_id, code, w in tag_rows:
        tags_by_poi.setdefault(poi_id, {})[code] = w

    pref = set(tag_service.resolve_codes(db, preferences or []))
    hotel_min = rules.get("hotel_price_level_min", 0)
    hotel_max = rules.get("hotel_price_level_max", 5)
    # 保底集：checkin 模式 Top 地标由保底注入负责，此处不做剔除，交给权重
    landmark_ids: set[int] = set()
    if rules.get("landmark_must_cover_topn"):
        lm = (
            db.query(Poi.id).join(PoiExtScenic, PoiExtScenic.poi_id == Poi.id)
            .filter(PoiExtScenic.is_landmark.is_(True))
            .order_by(Poi.hot_score.desc()).limit(20).all()
        )
        landmark_ids = {x[0] for x in lm}

    cands: list[PlannerPoi] = []
    for p in rows:
        if p.category == "study":
            # 游学点不进普通候选池：仅作为预设主题路线的保底站注入（方案 3.2 / 5.8），
            # 否则校园站点会污染四模式的自由选点结果。
            continue
        if p.category == "hotel":
            if not (hotel_min <= p.price_level <= hotel_max):
                continue
        ptags = tags_by_poi.get(p.id, {})
        # 偏好命中筛选（方案 5.2）：仅作用于景点/休闲候选池；
        # 餐厅为用餐锚点（地理就近驱动）、酒店由档次约束驱动，不做偏好剔除
        if pref and p.category in ("scenic", "leisure"):
            hit = sum(w for code, w in ptags.items() if code in pref)
            if hit < 0.2 and p.id not in landmark_ids and not (set(ptags) & pref):
                continue

        ext_sc = ext_fd = ext_ht = ext_ls = None
        if p.category == "scenic":
            ext_sc = db.get(PoiExtScenic, p.id)
        elif p.category == "food":
            ext_fd = db.get(PoiExtFood, p.id)
        elif p.category == "hotel":
            ext_ht = db.get(PoiExtHotel, p.id)
        else:
            ext_ls = db.get(PoiExtLeisure, p.id)

        # A3：开放时间也走生效规则（例如临时改为夜场）
        eff_open = price_service.effective_open_time(db, p)
        night_only = bool(eff_open and eff_open[0][0] >= "17:00")
        # A3：按生效日期解析票价 / 价格档，保证调价到点即生效
        eff_price, eff_level = price_service.effective_price(db, p)
        # 图片策略：行程里也只带管理员上传的图
        _imgs, _ = split_visible_images(p.images, p.image_meta)
        cands.append(PlannerPoi(
            id=p.id, name=p.name, category=p.category, sub_type=p.sub_type,
            longitude=p.longitude, latitude=p.latitude,
            suggest_duration_min=p.suggest_duration_min,
            ticket_price=eff_price, price_level=(eff_level or p.price_level),
            rating=p.rating, review_count=p.review_count,
            hot_score=p.hot_score, quality_score=p.quality_score,
            is_landmark=(ext_sc.is_landmark if ext_sc else False),
            indoor=(ext_sc.indoor if ext_sc else (ext_ls.indoor if ext_ls else False)),
            physical_level=(ext_sc.physical_level if ext_sc else 2),
            is_time_honored=(ext_fd.is_time_honored if ext_fd else False),
            cuisine=(ext_fd.cuisine if ext_fd else ""),
            meal_period=(ext_fd.meal_period if ext_fd else "午,晚"),
            avg_price=(ext_ht.price_min if ext_ht else (ext_fd.avg_price if ext_fd else 0)),
            grade=(ext_ht.grade if ext_ht else ""),
            night_open=(ext_ls.night_open if ext_ls else False),
            night_only=night_only,
            play_type=(ext_ls.play_type if ext_ls else ""),
            photospot_weight=ptags.get("photospot", 0.0),
            pref_tags=(set(ptags) & pref) if pref else set(),
            images=_imgs,
        ))

    if not cands:
        notes.append("候选为空：已逐级放宽筛选条件")
    return cands, notes
