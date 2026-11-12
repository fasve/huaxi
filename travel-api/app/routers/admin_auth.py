"""管理端认证路由：账号密码登录 / 当前账号 / 退出 / 修改密码。

前缀与 admin.py 相同（/api/v1/admin），本文件的 /login 等为公开接口，
其余管理接口由 admin.require_admin 统一做 Bearer **JWT** 校验（typ=admin）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AdminUser
from app.services.admin_auth import (
    authenticate, hash_password, issue_session, revoke_all_sessions,
    revoke_session, require_admin, verify_password,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-auth"])


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class PasswordIn(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    """账号密码登录，成功后返回标准 JWT（typ=admin，默认 12 小时有效）。"""
    user = authenticate(db, body.username, body.password)
    token, expires_in = issue_session(db, user)
    return dict(
        token=token,
        token_type="Bearer",
        username=user.username,
        display_name=user.display_name,
        expires_in=expires_in,
    )


@router.get("/me")
def me(admin: AdminUser = Depends(require_admin)):
    """当前登录管理员（前端刷新页面时可用于校验会话）。"""
    return dict(
        username=admin.username,
        display_name=admin.display_name,
        status=admin.status,
        last_login_at=admin.last_login_at.isoformat() if admin.last_login_at else None,
    )


@router.post("/logout")
def logout(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_admin),
):
    revoke_session(db, authorization)
    return dict(message="已退出登录")


@router.post("/password")
def change_password(
    body: PasswordIn,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
):
    """修改当前管理员密码；修改后该账号所有会话失效，需重新登录。"""
    if not verify_password(body.old_password, admin.password_hash):
        raise HTTPException(400, "原密码不正确")
    if body.new_password == body.old_password:
        raise HTTPException(400, "新密码不能与原密码相同")
    admin.password_hash = hash_password(body.new_password)
    db.commit()
    revoke_all_sessions(db, admin.id)
    return dict(message="密码已修改，请重新登录")
