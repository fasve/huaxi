"""预设主题路线接口（方案 #14 游客端 / A7 管理端）。

游客端：GET /api/v1/preset-routes、GET /api/v1/preset-routes/{code}
管理端：GET/PATCH /api/v1/admin/preset-routes（A7 季节性开关与政策周更校验）
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import preset_route_service as svc
from app.services.admin_auth import require_admin

router = APIRouter(prefix="/api/v1", tags=["preset-routes"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin-preset-routes"])


# ---------------- #14 游客端：线路列表与详情（纯展示，零算法开销） ----------------

@router.get("/preset-routes")
def list_routes(
    theme: str | None = Query(None, description="study_tour / culture / eco / night"),
    target_group: str | None = Query(None, description="亲子 / 中学团体 / 家庭 / 游客"),
    visit_date: str | None = Query(None, description="出行日期 YYYY-MM-DD；为空按今天判定 date_gate"),
    db: Session = Depends(get_db),
):
    """返回线路摘要 + 按 visit_date 计算的日期概览（工作日 / 周末 / 花期 / 室内场馆可用性）。"""
    return dict(items=svc.list_routes(db, theme, target_group, visit_date))


@router.get("/preset-routes/{code}")
def get_route(
    code: str,
    visit_date: str | None = Query(None, description="出行日期 YYYY-MM-DD"),
    include_addon: bool = Query(False, description="是否把全天深度版加段并入主站点序列"),
    db: Session = Depends(get_db),
):
    """逐站讲解 + 研学任务卡 + date_gate 结论（开放日 / 花期 / 预约提醒 / 降级说明）。"""
    return svc.get_route(db, code, visit_date, include_addon=include_addon)


# ---------------- A7 管理端：线路清单、启停、政策校验 ----------------

@admin_router.get("/preset-routes")
def admin_list(db: Session = Depends(get_db), _: int = Depends(require_admin)):
    return dict(items=svc.admin_list_routes(db))


@admin_router.get("/preset-routes/{code}")
def admin_detail(code: str,
                 visit_date: str | None = Query(None, description="日期闸门预览用出行日期"),
                 db: Session = Depends(get_db),
                 _: int = Depends(require_admin)):
    return svc.get_route(db, code, visit_date,
                         include_addon=True, include_disabled=True)


class RoutePatchIn(BaseModel):
    enabled: bool | None = Field(None, description="季节性开关（如花期结束后停用）")
    policy_checked_at: str | None = Field(
        None, description="入校政策周更校验日期 YYYY-MM-DD；A7 任务完成标记")


@admin_router.patch("/preset-routes/{code}")
def admin_patch(code: str, body: RoutePatchIn,
                db: Session = Depends(get_db), _: int = Depends(require_admin)):
    r = db.query(svc.PresetRoute).filter(svc.PresetRoute.code == code).first()
    if r is None:
        from fastapi import HTTPException
        raise HTTPException(404, f"预设路线不存在: {code}")
    if body.enabled is not None:
        return svc.set_route_enabled(db, code, body.enabled, body.policy_checked_at)
    if body.policy_checked_at:
        r.policy_checked_at = body.policy_checked_at
        db.commit()
    return dict(code=r.code, enabled=r.enabled,
                policy_checked_at=r.policy_checked_at or "")
