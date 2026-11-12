"""游客端路由：认证 / POI / 模式说明。"""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tag
from app.schemas import (
    AnonymousLoginIn, MessageOut, ModeOut, PoiPageOut, TokenOut,
    WechatLoginIn, WeightMetaOut,
)
from app.services.auth_service import anonymous_login, wechat_login
from app.services.poi_service import poi_to_out, query_pois
from app.services.trip_service import get_mode_cfg
from app.services.user_auth import resolve_token

router = APIRouter(prefix="/api/v1", tags=["guest"])
modes_router = APIRouter(prefix="/api/v1", tags=["guest"])


def current_user_id(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> int | None:
    """可选鉴权：浏览/生成免登录；保存行程等动作要求 token。"""
    if authorization is None:
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    try:
        return resolve_token(db, token)
    except HTTPException:
        return None


# ---------- #0 静默登录（真实 code2session + 自签 JWT） ----------

@router.post("/auth/wechat/login", response_model=TokenOut)
def login(body: WechatLoginIn, db: Session = Depends(get_db)):
    """wx.login 的 code 交给服务端换 openid；AppSecret 不出服务端。"""
    return wechat_login(db, body.code, body.device_id or "")


@router.post("/auth/anonymous", response_model=TokenOut)
def anonymous(body: AnonymousLoginIn, db: Session = Depends(get_db)):
    """PC 游客模式：非微信场景签发 typ=anonymous 的 JWT（不冒充微信登录）。"""
    return anonymous_login(db, body.device_id or "")


# ---------- #1 资源列表 ----------

@router.get("/pois", response_model=PoiPageOut)
def list_pois(
    category: str | None = None,
    tags: str | None = None,          # 逗号分隔
    price_level: int | None = None,
    min_rating: float | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    if page_size > 50:
        page_size = 50
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    total, rows = query_pois(
        db, category=category, tag_codes=tag_list,
        max_price_level=price_level, min_rating=min_rating,
        keyword=keyword, page=page, page_size=page_size,
    )
    return dict(
        total=total, page=page, page_size=page_size,
        items=[poi_to_out(p, db) for p in rows],
    )


# ---------- #2 资源详情 ----------

@router.get("/pois/{poi_id}")
def poi_detail(poi_id: int, db: Session = Depends(get_db)):
    from app.models import Poi
    p = db.get(Poi, poi_id)
    if not p or not p.visitable:
        raise HTTPException(404, "资源不存在或已下架")
    return poi_to_out(p, db)


# ---------- 标签字典（T1 筛选器） ----------

@router.get("/tags")
def list_tags(db: Session = Depends(get_db)):
    rows = db.query(Tag).all()
    return [dict(code=t.code, name=t.name) for t in rows]


# ---------- #6 模式说明（T2 选择卡） ----------

@modes_router.get("/trip-modes", response_model=list[ModeOut])
def trip_modes(db: Session = Depends(get_db)):
    budget_hints = {
        "leisure": "人均日预算参考 300–600 元",
        "blitz": "人均日预算参考 100–250 元",
        "premium": "人均日预算参考 1000–2000 元",
        "checkin": "人均日预算参考 300–700 元",
    }
    out = []
    for mode in ("leisure", "blitz", "premium", "checkin"):
        cfg = get_mode_cfg(db, mode)
        out.append(ModeOut(
            mode=mode, mode_name=cfg.mode_name, description=cfg.description,
            weights=cfg.weights,
            hard_rules_brief=dict(
                daily_poi=f"{cfg.hard_rules['daily_poi_min']}~{cfg.hard_rules['daily_poi_max']} 个/天",
                max_hours=f"{cfg.hard_rules['daily_play_hours_max']} 小时/天",
                hotel_floor=cfg.hard_rules["hotel_price_level_min"],
                evening=cfg.hard_rules.get("evening_slot", "none"),
                transit=cfg.hard_rules["transit_desc"],
            ),
            budget_hint=budget_hints.get(mode, ""),
        ))
    return out


# ---------- 个性化：权重维度元数据（前端滑块由该接口驱动） ----------

@modes_router.get("/weight-metadata", response_model=WeightMetaOut)
def weight_metadata(db: Session = Depends(get_db)):
    from app.planner.weights import (
        EVENING_PREFERENCES, WEIGHT_DIMENSIONS, WEIGHT_PRESETS, slider_defaults,
    )

    modes = {}
    for mode in ("leisure", "blitz", "premium", "checkin"):
        cfg = get_mode_cfg(db, mode)
        modes[mode] = dict(
            mode_name=cfg.mode_name,
            weights=cfg.weights,
            slider_defaults=slider_defaults(cfg.weights),
            daily_poi_max=cfg.hard_rules.get("daily_poi_max", 3),
            play_hours_max=cfg.hard_rules.get("daily_play_hours_max", 6),
            evening_slot=cfg.hard_rules.get("evening_slot", "none"),
        )

    return dict(
        dimensions=WEIGHT_DIMENSIONS,
        presets=WEIGHT_PRESETS,
        evening_preferences=EVENING_PREFERENCES,
        modes=modes,
    )
