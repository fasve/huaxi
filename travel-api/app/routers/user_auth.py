"""游客端认证路由：注册 / 登录 / 当前身份 / 退出 / JWT 滑动续期。

公开接口：register、login；me、logout、refresh 需 `Authorization: Bearer <JWT>`。
微信静默登录 / PC 匿名游客在 guest.router（/auth/wechat/login、/auth/anonymous），
四种登录方式共用 `jwt_service` 签发与校验，token 类型互相隔离。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import TokenOut
from app.services.auth_service import refresh_token as do_refresh
from app.services.user_auth import (
    account_out, login as do_login, register as do_register,
    resolve_token, revoke_session,
)

router = APIRouter(prefix="/api/v1/auth", tags=["user-auth"])


class RegisterIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=6, max_length=64)
    nickname: str = Field("", max_length=32)
    phone: str | None = Field(None, max_length=20)


class LoginIn(BaseModel):
    account: str = Field(..., min_length=1, max_length=64, description="用户名或手机号")
    password: str = Field(..., min_length=1, max_length=128)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "请先登录")
    return authorization[7:].strip()


def _current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> int:
    return resolve_token(db, _bearer(authorization))


@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """注册成功后直接返回会话 token，前端无需二次登录。"""
    return do_register(db, body.username, body.password, body.nickname, body.phone)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    """支持用户名或手机号登录。"""
    return do_login(db, body.account, body.password)


@router.get("/me")
def me(user_id: int = Depends(_current_user), db: Session = Depends(get_db)):
    """刷新页面时校验 JWT 并取回身份（微信 / 匿名游客返回 is_guest）。"""
    return account_out(db, user_id)


@router.post("/refresh", response_model=TokenOut)
def refresh(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """滑动续期（设计方案 7.5）：旧 jti 作废，换发 7 天新 JWT。"""
    token = _bearer(authorization)
    return do_refresh(db, token)


@router.post("/logout")
def logout(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    """撤销当前 JWT（jti 入黑名单），幂等；过期 token 也返回成功。"""
    token = _bearer(authorization)
    try:
        user_id = resolve_token(db, token)
    except HTTPException:
        user_id = None
    revoke_session(db, token)
    return dict(message="已退出登录", user_id=user_id)
