"""行程路由：#3 生成 / #4 重排替换 / #5 我的行程 / #10 保存 / #7 海报 / 个性化权重。"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    ChatEditIn, EnrichmentIn, ItemAddIn, ItemCopyIn, ItemMoveIn, ItemReplaceIn,
    MessageOut, ParseGuideIn, RebalanceIn, ReweightIn, SaveIn, SubscribeIn,
    TripGenerateIn, TripReplanIn, WeightPreviewIn,
)
from app.services import trip_edit, trip_service
from app.services.user_auth import resolve_token

router = APIRouter(prefix="/api/v1/trips", tags=["trips"])


def _require_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> int:
    """保存 / 我的行程 / 删除：同时接受账号会话 token 与微信 mock token。"""
    if not authorization:
        raise HTTPException(401, "请先登录")
    token = authorization.removeprefix("Bearer ").strip()
    return resolve_token(db, token)


def _optional_identity(
    authorization: str | None, db: Session,
) -> tuple[int | None, str]:
    """可选登录态：解析出 user_id 与微信 openid，未登录返回 (None, "")。"""
    if not authorization:
        return None, ""
    try:
        user_id = resolve_token(db, authorization.removeprefix("Bearer ").strip())
    except HTTPException:
        return None, ""
    from app.models import User
    user = db.get(User, user_id)
    return user_id, (user.openid if user else "")


# ---------- #3 行程生成（核心，匿名可用） ----------

@router.post("/generate")
def generate(body: TripGenerateIn, db: Session = Depends(get_db)):
    out = trip_service.create_trip(
        db, days=body.days, budget=body.budget, mode=body.mode,
        preferences=body.preferences, party_type=body.party_type,
        seed=body.seed, user_id=None,
        custom_weights=body.weights, pace=body.pace,
        cost_prefs=body.cost_prefs,
        preset_route_code=body.preset_route_code,
        visit_date=body.visit_date,
        include_addon=body.include_addon,
    )
    return out


# ---------- 个性化：权重预览（不落库） ----------

@router.post("/preview")
def preview(body: WeightPreviewIn, db: Session = Depends(get_db)):
    return trip_service.preview_weights(
        db, mode=body.mode, slider_raw=body.weights,
        preferences=body.preferences, pace=body.pace, top_k=body.top_k,
    )


# ---------- 个性化：按权重重排既有行程 ----------

@router.post("/{trip_id}/reweight")
def reweight(trip_id: str, body: ReweightIn, db: Session = Depends(get_db)):
    return trip_service.reweight_trip(
        db, trip_id, slider_raw=body.weights, pace=body.pace,
    )


# ---------- #4 单日重排 / 槽位替换 ----------

@router.post("/{trip_id}/rebalance")
def rebalance(trip_id: str, body: RebalanceIn, db: Session = Depends(get_db)):
    return trip_service.rebalance(
        db, trip_id, body.day_index, body.action, body.slot, body.poi_id,
    )


# ---------- #4 前置数据：槽位替换候选（半屏弹层） ----------

@router.get("/{trip_id}/days/{day_index}/slots/{slot}/candidates")
def candidates(trip_id: str, day_index: int, slot: str, db: Session = Depends(get_db)):
    return dict(items=trip_service.slot_candidates(db, trip_id, day_index, slot))


# ---------- #7 分享海报素材（canvas 端绘制，匿名可用） ----------

@router.post("/{trip_id}/poster")
def poster(trip_id: str, request: Request, db: Session = Depends(get_db)):
    """海报排版数据 + 小程序码/二维码 + 分享参数；并记分享流水（A5 可统计）。"""
    from app.services.poster_service import get_poster

    user_id: int | None = None
    if request.headers.get("authorization"):
        try:
            user_id = resolve_token(
                db, request.headers["authorization"].removeprefix("Bearer ").strip())
        except HTTPException:
            user_id = None
    return get_poster(db, trip_id, user_id=user_id)


# ---------- T4 增量重算（改天数 / 预算，不整单重生成） ----------

@router.post("/{trip_id}/replan")
def replan(trip_id: str, body: TripReplanIn, db: Session = Depends(get_db)):
    from app.services.incremental_service import incremental_replan

    try:
        return incremental_replan(
            db, trip_id, days=body.days, budget=body.budget,
            weights=body.weights, pace=body.pace,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------- T7 AI 润色与小贴士 ----------

@router.get("/{trip_id}/enrichment")
def get_enrichment(trip_id: str, db: Session = Depends(get_db)):
    from app.models import Trip
    from app.services import enrichment_service

    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    cached = enrichment_service.get_cached(db, trip_id)
    return cached or enrichment_service.get_or_build(db, trip, force=False)


@router.post("/{trip_id}/enrichment")
def build_enrichment(trip_id: str, body: EnrichmentIn,
                     db: Session = Depends(get_db)):
    from app.models import Trip
    from app.services import enrichment_service

    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    return enrichment_service.get_or_build(db, trip, force=body.force)


# ---------- T8 出行前一日订阅消息提醒 ----------

@router.post("/{trip_id}/subscribe")
def subscribe(trip_id: str, body: SubscribeIn,
              authorization: str | None = Header(None),
              db: Session = Depends(get_db)):
    from app.models import Trip
    from app.services import notify_service

    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    user_id, openid = _optional_identity(authorization, db)
    if body.openid:
        openid = body.openid
    if not (openid or "").strip():
        raise HTTPException(401, "请先登录后再设置出行提醒")
    try:
        return notify_service.create_reminder(
            db, trip, user_id=user_id, openid=openid,
            visit_date=body.visit_date, template_id=body.template_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------- #9 / 8.1 路线分段（距离 / 耗时） ----------

@router.get("/{trip_id}/route-segments")
def route_segments(trip_id: str, db: Session = Depends(get_db)):
    from app.models import Trip
    from app.services import route_client

    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    return route_client.trip_segments(db, trip)


# ---------- #10 保存行程（需登录） ----------

@router.post("/{trip_id}/save")
def save(trip_id: str, body: SaveIn, db: Session = Depends(get_db),
         user_id: int = Depends(_require_user)):
    return trip_service.save_trip(db, trip_id, user_id)


# ---------- #5 我的行程 ----------

@router.get("")
def my_trips(page: int = 1, page_size: int = 20,
             db: Session = Depends(get_db), user_id: int = Depends(_require_user)):
    total, items = trip_service.my_trips(db, user_id, page, page_size)
    return dict(total=total, page=page, page_size=page_size, items=items)


@router.get("/{trip_id}")
def trip_detail(trip_id: str, db: Session = Depends(get_db)):
    from app.models import Trip
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    return trip_service.trip_to_out(db, trip)


@router.delete("/{trip_id}")
def delete_trip(trip_id: str, db: Session = Depends(get_db),
                user_id: int = Depends(_require_user)):
    from app.models import Trip
    trip = db.get(Trip, trip_id)
    if not trip or trip.user_id != user_id:
        raise HTTPException(404, "行程不存在")
    db.delete(trip)
    db.commit()
    return dict(message="已删除")


# ---------- 行程编辑（删除 / 移动 / 复制 / 替换）与体检 ----------

@router.delete("/{trip_id}/items/{item_id}")
def delete_trip_item(trip_id: str, item_id: int, db: Session = Depends(get_db)):
    """删除某个行程项并重算当天时间轴与费用。"""
    return trip_edit.delete_item(db, trip_id, item_id)


@router.post("/{trip_id}/items/{item_id}/move")
def move_trip_item(
    trip_id: str, item_id: int, body: ItemMoveIn, db: Session = Depends(get_db),
):
    """把行程项移动到另一天（可指定插入位置），并重算时间轴。"""
    return trip_edit.move_item(db, trip_id, item_id, body.target_day, body.target_index)


@router.post("/{trip_id}/items/{item_id}/copy")
def copy_trip_item(
    trip_id: str, item_id: int, body: ItemCopyIn, db: Session = Depends(get_db),
):
    """复制行程项到另一天。"""
    return trip_edit.copy_item(db, trip_id, item_id, body.target_day)


@router.post("/{trip_id}/items/{item_id}/replace")
def replace_trip_item(
    trip_id: str, item_id: int, body: ItemReplaceIn, db: Session = Depends(get_db),
):
    """把行程项替换为另一个点位。"""
    return trip_edit.replace_item(db, trip_id, item_id, body.poi_id)


@router.post("/{trip_id}/items/add")
def add_trip_item(trip_id: str, body: ItemAddIn, db: Session = Depends(get_db)):
    """把收藏 / 待计划里的点位排入指定天（重算时间轴与费用）。"""
    return trip_edit.add_item(db, trip_id, body.poi_id, body.day)


@router.get("/{trip_id}/diagnose")
def diagnose_trip(trip_id: str, db: Session = Depends(get_db)):
    """行程判官：检查点位密度、折返、开放时间冲突、重复点位与预算。"""
    return trip_edit.diagnose(db, trip_id)


@router.post("/{trip_id}/optimize")
def optimize_trip_route(trip_id: str, db: Session = Depends(get_db)):
    """按相邻点位距离做同日重排（2-opt / 全排列），并重算时间轴。"""
    return trip_edit.optimize_route(db, trip_id)


@router.post("/{trip_id}/redistribute")
def redistribute_trip_days(trip_id: str, db: Session = Depends(get_db)):
    """按地理区域把所有点位重新分配到各天（KMeans + 均衡数量 + 同日排序）。"""
    return trip_edit.redistribute_days(db, trip_id)


# ---------- 对话式行程编辑（自然语言 → 结构化 ops → 确定性重算） ----------

@router.post("/{trip_id}/chat-edit")
def chat_edit_trip(trip_id: str, body: ChatEditIn, db: Session = Depends(get_db)):
    """用一句话改行程：换交通方式 / 改出发时间 / 增删点位 / 移动 / 重排当天。

    模型不可用时回退本地规则，覆盖高频表达；两种路径都会重算时间轴与费用。
    """
    from app.services import trip_chat_edit

    return trip_chat_edit.chat_edit(db, trip_id, body.text)


# ---------- 智能解析（合规版）：粘贴攻略文本 → 地点 → 行程 ----------

@router.post("/parse-guide")
def parse_guide_trip(
    body: ParseGuideIn,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    """只解析用户主动粘贴的攻略文本，不抓取任何外部链接。"""
    from app.services import guide_parse

    user_id = None
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if token:
            try:
                user_id = resolve_token(db, token)
            except HTTPException:
                user_id = None
    return guide_parse.parse_guide(
        db, body.text, start_date=body.start_date, mode=body.mode,
        budget=body.budget, user_id=user_id,
    )
