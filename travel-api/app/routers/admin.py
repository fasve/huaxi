"""管理端路由：#11 资源 CRUD/导入导出 + #12 模式权重配置。

鉴权：账号密码登录取得会话 token，后续接口统一 `Authorization: Bearer <token>`。
生产侧仍应由网关/独立子域保证小程序与游客端不可达管理接口。
"""
import csv
import io
import os

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Poi, PoiExtFood, PoiExtHotel, PoiExtLeisure, PoiExtScenic,
    PoiTag, Tag, TripModeConfig,
)
from app.schemas import (
    ImportResultOut, MessageOut, ModeConfigIn, ModeConfigOut, PoiWriteIn,
    ProviderKeyIn,
)
from app.services.poi_service import poi_to_out, query_pois
from app.services.cache import mode_cache, poi_cache
from app.services import mode_version_service
from app.services.image_service import save_local
from app.services.image_policy import policy_payload
from app.services.provider_keys import (
    clear_key as clear_provider_key, set_key as set_provider_key,
)
from app.services.provider_keys import status as provider_key_status
# 统一鉴权依赖；admin_ext.py 也从本模块引用它，保持单一实现
from app.services.admin_auth import require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ---------- #11 资源 CRUD ----------

@router.get("/pois")
def admin_list_pois(
    category: str | None = None, keyword: str | None = None,
    visitable: bool | None = None, page: int = 1, page_size: int = 20,
    db: Session = Depends(get_db), _: None = Depends(require_admin),
):
    total, rows = query_pois(
        db, category=category, keyword=keyword,
        visitable_only=visitable, page=page, page_size=page_size,
    )
    return dict(total=total, page=page, page_size=page_size,
                items=[poi_to_out(p, db) for p in rows])


@router.post("/pois")
def admin_create_poi(body: PoiWriteIn, db: Session = Depends(get_db),
                     _: None = Depends(require_admin)):
    # 数据质量红线：坐标/时长缺失不得上架
    if not body.longitude or not body.latitude:
        raise HTTPException(400, "坐标缺失的 POI 不得上架")
    if body.suggest_duration_min <= 0:
        raise HTTPException(400, "建议游玩时长缺失的 POI 不得上架")

    p = Poi(
        name=body.name, category=body.category, sub_type=body.sub_type,
        address=body.address, longitude=body.longitude, latitude=body.latitude,
        suggest_duration_min=body.suggest_duration_min,
        ticket_price=body.ticket_price, price_level=body.price_level,
        rating=body.rating, review_count=body.review_count,
        visitable=body.visitable, open_time=body.open_time,
        images=list(body.images or []),
        image_meta=list(body.image_meta or []),
        hot_score=body.rating / 5 * 0.7, quality_score=body.rating / 5 * 0.85,
    )
    db.add(p)
    db.flush()
    _write_ext(db, p, body)
    _write_tags(db, p.id, body.tags)
    db.commit()
    poi_cache.invalidate_prefix("pois:")
    return dict(poi_id=p.id, message="已创建")


@router.put("/pois/{poi_id}")
def admin_update_poi(poi_id: int, body: PoiWriteIn,
                     db: Session = Depends(get_db), _: None = Depends(require_admin)):
    p = db.get(Poi, poi_id)
    if not p:
        raise HTTPException(404, "POI 不存在")
    if not body.longitude or not body.latitude or body.suggest_duration_min <= 0:
        raise HTTPException(400, "坐标/时长缺失的 POI 不得上架")
    p.name, p.category, p.sub_type = body.name, body.category, body.sub_type
    p.address, p.longitude, p.latitude = body.address, body.longitude, body.latitude
    p.suggest_duration_min = body.suggest_duration_min
    p.ticket_price, p.price_level = body.ticket_price, body.price_level
    p.rating, p.review_count, p.visitable = body.rating, body.review_count, body.visitable
    p.open_time = body.open_time
    p.images = list(body.images or [])
    p.image_meta = list(body.image_meta or [])
    _write_ext(db, p, body, update=True)
    _rewrite_tags(db, poi_id, body.tags)
    db.commit()
    poi_cache.invalidate_prefix("pois:")
    return dict(poi_id=poi_id, message="已更新")


@router.patch("/pois/{poi_id}/visitable")
def admin_toggle(poi_id: int, visitable: bool = True,
                 db: Session = Depends(get_db), _: None = Depends(require_admin)):
    p = db.get(Poi, poi_id)
    if not p:
        raise HTTPException(404, "POI 不存在")
    if visitable and (not p.longitude or p.suggest_duration_min <= 0):
        raise HTTPException(400, "坐标/时长缺失的 POI 不得上架")
    p.visitable = visitable
    db.commit()
    poi_cache.invalidate_prefix("pois:")
    return dict(poi_id=poi_id, visitable=visitable)


@router.delete("/pois/{poi_id}", response_model=MessageOut)
def admin_delete_poi(poi_id: int, db: Session = Depends(get_db),
                     _: None = Depends(require_admin)):
    p = db.get(Poi, poi_id)
    if not p:
        raise HTTPException(404, "POI 不存在")
    for tbl in (PoiExtScenic, PoiExtFood, PoiExtHotel, PoiExtLeisure):
        e = db.get(tbl, poi_id)
        if e:
            db.delete(e)
    db.query(PoiTag).filter(PoiTag.poi_id == poi_id).delete()
    db.delete(p)
    db.commit()
    poi_cache.invalidate_prefix("pois:")
    return MessageOut(message="已删除")


# ---------- #11 CSV 批量导入 ----------

@router.post("/pois/import", response_model=ImportResultOut)
def admin_import(file: UploadFile, db: Session = Depends(get_db),
                 _: None = Depends(require_admin)):
    """CSV 模板列：name,category,sub_type,address,longitude,latitude,
    suggest_duration_min,ticket_price,price_level,rating,review_count,tags"""
    raw = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    failed: list[dict] = []
    n_ok = 0
    total = 0
    for i, row in enumerate(reader, start=2):  # 第 1 行是表头
        total += 1
        try:
            lon = float(row.get("longitude") or 0)
            lat = float(row.get("latitude") or 0)
            dur = int(row.get("suggest_duration_min") or 0)
            if not (104 < lon < 110 and 24 < lat < 29):
                raise ValueError("坐标超出花溪区合法范围")
            if dur <= 0:
                raise ValueError("建议时长缺失")
            p = Poi(
                name=row["name"].strip(), category=row["category"].strip(),
                sub_type=(row.get("sub_type") or "").strip(),
                address=(row.get("address") or "").strip(),
                longitude=lon, latitude=lat, suggest_duration_min=dur,
                ticket_price=float(row.get("ticket_price") or 0),
                price_level=int(row.get("price_level") or 1),
                rating=float(row.get("rating") or 4.0),
                review_count=int(row.get("review_count") or 0),
                hot_score=float(row.get("rating") or 4.0) / 5 * 0.7,
                quality_score=float(row.get("rating") or 4.0) / 5 * 0.85,
                visitable=True,
            )
            db.add(p)
            db.flush()
            tags = [t.strip() for t in (row.get("tags") or "").split("|") if t.strip()]
            _write_tags(db, p.id, tags)
            n_ok += 1
        except Exception as ex:  # noqa: BLE001
            failed.append(dict(line=i, name=row.get("name") or "", error=str(ex)))
    db.commit()
    poi_cache.invalidate_prefix("pois:")
    return ImportResultOut(total=total, success=n_ok, failed=failed)


# ---------- #11 导出 ----------

@router.get("/pois/export")
def admin_export(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "name", "category", "sub_type", "address", "longitude",
                     "latitude", "suggest_duration_min", "ticket_price", "price_level",
                     "rating", "review_count", "hot_score", "visitable"])
    for p in db.query(Poi).order_by(Poi.id).all():
        writer.writerow([p.id, p.name, p.category, p.sub_type, p.address, p.longitude,
                         p.latitude, p.suggest_duration_min, p.ticket_price,
                         p.price_level, p.rating, p.review_count, p.hot_score, p.visitable])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pois.csv"},
    )


# ---------- #12 模式权重配置 ----------

@router.get("/mode-configs", response_model=list[ModeConfigOut])
def list_mode_configs(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    rows = db.query(TripModeConfig).all()
    return [ModeConfigOut(
        mode=r.mode, mode_name=r.mode_name, weights=r.weights,
        hard_rules=r.hard_rules, slot_template=r.slot_template,
        description=r.description, version=r.version,
    ) for r in rows]


@router.get("/mode-configs/{mode}", response_model=ModeConfigOut)
def get_mode_config(mode: str, db: Session = Depends(get_db),
                    _: None = Depends(require_admin)):
    r = db.query(TripModeConfig).filter(TripModeConfig.mode == mode).first()
    if not r:
        raise HTTPException(404, "模式不存在")
    return ModeConfigOut(
        mode=r.mode, mode_name=r.mode_name, weights=r.weights,
        hard_rules=r.hard_rules, slot_template=r.slot_template,
        description=r.description, version=r.version,
    )


@router.put("/mode-configs/{mode}")
def update_mode_config(mode: str, body: ModeConfigIn,
                       db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """部分更新模式配置；权重校验：9 维静态权重和 = 1.0（±0.01 容差）。"""
    r = db.query(TripModeConfig).filter(TripModeConfig.mode == mode).first()
    if not r:
        raise HTTPException(404, "模式不存在")
    # A4：更新前留历史快照，支持随时回滚
    mode_version_service.snapshot(db, r, status="history", note="管理端更新前快照")
    if body.weights is not None:
        mode_version_service.validate_weights(body.weights)
        r.weights = body.weights
    if body.hard_rules is not None:
        r.hard_rules = body.hard_rules
    if body.description is not None:
        r.description = body.description
    if body.slot_template is not None:
        r.slot_template = body.slot_template
    r.version += 1
    db.commit()
    mode_cache.invalidate_prefix("mode:")
    return dict(mode=mode, version=r.version, message="已更新并生效")


# ---------- 辅助 ----------

def _write_ext(db: Session, p: Poi, body: PoiWriteIn, update: bool = False) -> None:
    ext = body.ext or {}
    if p.category == "scenic":
        e = db.get(PoiExtScenic, p.id)
        if e is None:
            e = PoiExtScenic(poi_id=p.id)
            db.add(e)
        e.level = ext.get("level", "")
        e.best_season = ext.get("best_season", "全季")
        e.indoor = bool(ext.get("indoor", False))
        e.physical_level = int(ext.get("physical_level", 2))
        e.is_landmark = bool(ext.get("is_landmark", False))
    elif p.category == "food":
        e = db.get(PoiExtFood, p.id)
        if e is None:
            e = PoiExtFood(poi_id=p.id)
            db.add(e)
        e.cuisine = ext.get("cuisine", "黔菜")
        e.signature = ext.get("signature", [])
        e.avg_price = float(ext.get("avg_price", body.ticket_price))
        e.meal_period = ext.get("meal_period", "午,晚")
        e.is_time_honored = bool(ext.get("is_time_honored", False))
    elif p.category == "hotel":
        e = db.get(PoiExtHotel, p.id)
        if e is None:
            e = PoiExtHotel(poi_id=p.id)
            db.add(e)
        e.grade = ext.get("grade", "经济")
        e.star = int(ext.get("star", 0))
        e.facility_tags = ext.get("facility_tags", [])
        e.price_min = float(ext.get("price_min", body.ticket_price))
        e.with_breakfast = bool(ext.get("with_breakfast", False))
    else:
        e = db.get(PoiExtLeisure, p.id)
        if e is None:
            e = PoiExtLeisure(poi_id=p.id)
            db.add(e)
        e.play_type = ext.get("play_type", "")
        e.night_open = bool(ext.get("night_open", False))
        e.indoor = bool(ext.get("indoor", False))


def _write_tags(db: Session, poi_id: int, codes: list[str]) -> None:
    for code in codes:
        tag = db.query(Tag).filter(Tag.code == code).first()
        if tag:
            db.add(PoiTag(poi_id=poi_id, tag_id=tag.id, weight=1.0))


def _rewrite_tags(db: Session, poi_id: int, codes: list[str]) -> None:
    db.query(PoiTag).filter(PoiTag.poi_id == poi_id).delete()
    db.flush()
    _write_tags(db, poi_id, codes)


# ---------- #11 图片资源：上传 / 联网抓图 / 批量补图 ----------

_ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg"}
_MAX_IMG_BYTES = 8 * 1024 * 1024


@router.post("/pois/images/upload")
def admin_upload_image(
    file: UploadFile,
    source_name: str = Form("管理员上传"),
    author: str = Form(""),
    license: str = Form("自有/已获授权"),
    license_url: str = Form(""),
    note: str = Form(""),
    _: None = Depends(require_admin),
):
    """管理端上传本地图片：落盘到 /static/poi，返回可直接使用的相对地址。

    `source_name / author / license / license_url` 用于登记真实来源与授权：
    从免费商用图库挑的图必须如实填写（例如 Pexels / 摄影者 / Pexels License / 链接），
    不再一律写成「自有/已获授权」。`note` 可记录检索词、是否同一品类示意等。
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_IMG_EXT:
        raise HTTPException(400, f"不支持的图片格式：{ext or '未知'}")
    data = file.file.read()
    if not data:
        raise HTTPException(400, "图片内容为空")
    if len(data) > _MAX_IMG_BYTES:
        raise HTTPException(400, "图片超过 8MB 上限")
    url = save_local(data, ext, f"upload_{file.filename or 'img'}")
    meta = dict(source="upload", source_name=source_name or "管理员上传",
                author=author, license=license or "自有/已获授权",
                license_url=license_url, note=note)
    return dict(url=url, filename=file.filename, size=len(data), meta=meta)


@router.post("/pois/{poi_id}/images/upload")
def admin_upload_poi_image(
    poi_id: int,
    file: UploadFile,
    source_name: str = Form("管理员上传"),
    author: str = Form(""),
    license: str = Form("自有/已获授权"),
    license_url: str = Form(""),
    note: str = Form(""),
    set_cover: bool = Form(False),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """上传并直接挂到某个 POI 上（批量补图脚本用，一次请求完成落盘 + 入库）。"""
    p = db.get(Poi, poi_id)
    if not p:
        raise HTTPException(404, "POI 不存在")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_IMG_EXT:
        raise HTTPException(400, f"不支持的图片格式：{ext or '未知'}")
    data = file.file.read()
    if not data:
        raise HTTPException(400, "图片内容为空")
    if len(data) > _MAX_IMG_BYTES:
        raise HTTPException(400, "图片超过 8MB 上限")
    url = save_local(data, ext, f"poi{poi_id}_{file.filename or 'img'}")
    meta = dict(source="upload", source_name=source_name or "管理员上传",
                author=author, license=license or "自有/已获授权",
                license_url=license_url, note=note)
    images = list(p.images or [])
    metas = list(p.image_meta or [])
    if set_cover:
        images.insert(0, url)
        metas.insert(0, meta)
    else:
        images.append(url)
        metas.append(meta)
    p.images = images
    p.image_meta = metas
    db.commit()
    poi_cache.invalidate_prefix("pois:")
    return dict(poi_id=poi_id, url=url, count=len(images),
                images=images, meta=meta)


@router.post("/pois/images/localize")
def admin_localize_image(url: str = "", _: None = Depends(require_admin)):
    """已停用：图片只允许管理员本地上传。"""
    raise HTTPException(410, "图片仅支持管理员本地上传；外部直链本地化已停用")


@router.get("/pois/images/providers")
def admin_image_providers(_: None = Depends(require_admin)):
    """图片策略（系统设置页展示）：只允许管理员上传。"""
    policy = policy_payload()
    return dict(items=[], usable=[], keys=provider_key_status(), policy=policy)


@router.post("/pois/images/keys")
def admin_set_provider_key(body: ProviderKeyIn, _: None = Depends(require_admin)):
    """已停用：不再接入任何第三方图片源。"""
    raise HTTPException(410, "图片仅支持管理员本地上传；第三方图片源已停用")


@router.get("/pois/images/fetch")
def admin_fetch_images(
    name: str = "", sub_type: str = "", category: str = "",
    count: int = 3, _: None = Depends(require_admin),
):
    """已停用：图片只允许管理员本地上传。"""
    raise HTTPException(410, "图片仅支持管理员本地上传；联网抓取已停用")


@router.post("/pois/{poi_id}/images/fetch")
def admin_poi_fetch_images(poi_id: int, count: int = 3,
                           db: Session = Depends(get_db), _: None = Depends(require_admin)):
    """已停用：图片只允许管理员本地上传。"""
    raise HTTPException(410, "图片仅支持管理员本地上传；联网补图已停用")