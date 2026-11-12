"""A6 管理员操作审计：统一记录入口 + 幂等建表 + 查询。

记录口径：
- 只记管理端动作（登录/登出/改密/POI/标签/模式配置/行程/用户/预设路线）；
- detail 存 {before, after, message} 摘要，由调用方裁剪，不整包塞大对象；
- 记录失败不阻断业务（审计是旁路能力，不能把主流程打挂）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditLog

# 常用动作名（避免各路由随手拼字符串）
ACTIONS = {
    "login": "登录",
    "logout": "登出",
    "password_change": "修改密码",
    "poi_create": "新增 POI",
    "poi_update": "编辑 POI",
    "poi_toggle": "上下架 POI",
    "poi_delete": "删除 POI",
    "poi_import": "批量导入 POI",
    "mode_update": "修改模式配置",
    "tag_create": "新增标签",
    "tag_update": "编辑标签",
    "tag_delete": "删除标签",
    "trip_delete": "删除行程",
    "user_toggle": "启用/禁用用户",
    "preset_route_patch": "预设路线启停/校验",
    "preset_route_update": "预设路线文案编辑",
    "preset_stop_update": "预设站点在线编辑",
    "cache_clear": "清空缓存",
    "provider_key_set": "配置图片源密钥",
}


def ensure_tables() -> None:
    """幂等建表（启动时调用；audit_log 不在既有 create_all 列表内）。"""
    from app.database import Base, engine

    Base.metadata.create_all(engine, tables=[AuditLog.__table__])


def record(
    db: Session,
    *,
    admin_id: int = 0,
    username: str = "",
    action: str,
    resource_type: str = "",
    resource_id: str | int = "",
    detail: dict | None = None,
    ip: str = "",
) -> None:
    """写一条审计。异常吞掉只打日志，绝不阻断业务。"""
    try:
        db.add(AuditLog(
            admin_id=int(admin_id or 0),
            username=username or "",
            action=action,
            resource_type=resource_type or "",
            resource_id=str(resource_id or ""),
            detail=detail or {},
            ip=(ip or "")[:64],
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        print(f"[travel-api][AUDIT] 记录失败（不影响业务）：{exc}")


def _client_ip(request) -> str:
    """取客户端 IP；反代场景优先 X-Forwarded-For 第一段。"""
    try:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else ""
    except Exception:  # noqa: BLE001
        return ""


def record_request(
    db: Session,
    request,
    *,
    admin,
    action: str,
    resource_type: str = "",
    resource_id: str | int = "",
    detail: dict | None = None,
) -> None:
    """路由层便捷入口：自动带 admin_id / username / ip。"""
    record(
        db,
        admin_id=(admin.id if admin is not None and hasattr(admin, "id") else 0),
        username=(admin.username if admin is not None and hasattr(admin, "username") else ""),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        ip=_client_ip(request),
    )


def _row_out(row: AuditLog) -> dict:
    return dict(
        id=row.id,
        admin_id=row.admin_id,
        username=row.username,
        action=row.action,
        action_name=ACTIONS.get(row.action, row.action),
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        detail=row.detail or {},
        ip=row.ip,
        created_at=row.created_at.isoformat(timespec="seconds") + "Z" if row.created_at else "",
    )


def query_logs(
    db: Session,
    *,
    action: str | None = None,
    admin_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """审计日志分页查询（A6 页面数据源）。"""
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if admin_id:
        q = q.filter(AuditLog.admin_id == admin_id)
    if keyword:
        q = q.filter(AuditLog.resource_id.like(f"%{keyword}%"))
    total = q.count()
    rows = (
        q.order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return dict(
        total=total, page=page, page_size=page_size,
        items=[_row_out(r) for r in rows],
    )


def actions_index() -> list[dict]:
    """动作字典（前端筛选下拉）。"""
    return [dict(action=k, name=v) for k, v in ACTIONS.items()]


def recent_days(db: Session, days: int = 7) -> list[dict]:
    """近 N 日审计条数（Dashboard 小卡）。"""
    from datetime import timedelta

    today = datetime.utcnow().date()
    since = today - timedelta(days=days - 1)
    rows = (
        db.query(
            func.date(AuditLog.created_at).label("d"),
            func.count(AuditLog.id),
        )
        .filter(AuditLog.created_at >= since)
        .group_by("d").all()
    )
    counts = {str(d): n for d, n in rows}
    return [
        dict(date=(since + timedelta(days=i)).isoformat(),
             count=counts.get((since + timedelta(days=i)).isoformat(), 0))
        for i in range(days)
    ]


def diff(before: dict[str, Any], after: dict[str, Any],
         keys: list[str] | None = None) -> dict:
    """生成 before/after 差异摘要：只保留变化字段。"""
    keys = keys or sorted(set(before) | set(after))
    changed_b, changed_a = {}, {}
    for k in keys:
        b, a = before.get(k), after.get(k)
        if b != a:
            changed_b[k] = b
            changed_a[k] = a
    return dict(before=changed_b, after=changed_a)
