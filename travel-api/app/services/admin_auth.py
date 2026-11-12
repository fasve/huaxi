"""管理端账号密码认证 —— 统一 JWT Bearer（设计方案「鉴权：JWT Bearer」）。

- 口令：PBKDF2-HMAC-SHA256 + 每账号随机盐，仅存哈希，不存明文；
- 登录态：标准 JWT（HS256，typ=admin，默认 12 小时），与游客端 JWT **类型隔离**，
  游客接口拒绝 admin token、管理接口拒绝游客 token；
- 撤销：退出登录把 jti 写入 `token_denylist`；修改密码后 JWT 中的 `pv`
  （口令哈希派生）失配，该账号历史 token 全部立即失效；
- `admin_session` 表仅保留作存量 token 的兼容通道，不再签发新会话。
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AdminSession, AdminUser
from app.services import jwt_service

PBKDF2_ITERATIONS = 200_000

# 账号不存在时也做一次等价哈希运算，避免用户名枚举的时间差
_DUMMY_HASH: str | None = None


def hash_password(password: str) -> str:
    """返回 `pbkdf2_sha256$迭代数$盐$哈希`，便于日后升级算法。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                             PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), int(iters),
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError, AttributeError):
        return False


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("no-such-user")
    return _DUMMY_HASH


def init_admin_auth() -> None:
    """启动时幂等建表 + 首次创建默认管理员（不覆盖既有账号与密码）。"""
    from app.database import Base, SessionLocal, engine

    Base.metadata.create_all(
        engine, tables=[AdminUser.__table__, AdminSession.__table__]
    )
    db = SessionLocal()
    try:
        if db.query(AdminUser).count() == 0:
            db.add(AdminUser(
                username=settings.ADMIN_BOOTSTRAP_USERNAME,
                password_hash=hash_password(settings.ADMIN_BOOTSTRAP_PASSWORD),
                display_name="系统管理员",
                status=1,
            ))
            db.commit()
    finally:
        db.close()


def authenticate(db: Session, username: str, password: str) -> AdminUser:
    """校验账号密码；失败统一返回 401「账号或密码错误」。"""
    user = db.query(AdminUser).filter(
        AdminUser.username == username.strip()
    ).first()
    if user is None:
        verify_password(password, _dummy_hash())
        raise HTTPException(401, "账号或密码错误")
    if not verify_password(password, user.password_hash):
        raise HTTPException(401, "账号或密码错误")
    if user.status != 1:
        raise HTTPException(403, "账号已停用，请联系系统维护人员")
    return user


def issue_session(db: Session, user: AdminUser) -> tuple[str, int]:
    """签发管理端 JWT，返回 (token, 有效秒数)。"""
    user.last_login_at = datetime.utcnow()
    db.commit()
    token, expires_in, _ = jwt_service.issue(
        subject=user.id, typ="admin", openid="", role="admin",
        pv=jwt_service.password_version(user.password_hash),
        hours=settings.ADMIN_SESSION_HOURS,
    )
    return token, expires_in


def verify_admin_session(db: Session, authorization: str | None) -> AdminUser:
    """FastAPI 依赖：解析 Bearer JWT（或存量会话）并校验账号状态 / 口令版本。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "请先登录管理后台")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "请先登录管理后台")

    if token.count(".") == 2:
        claims = jwt_service.resolve(db, token, jwt_service.ADMIN_TYPES)
        admin = db.get(AdminUser, int(claims["sub"]))
        if admin is None or admin.status != 1:
            raise HTTPException(403, "账号已停用")
        if claims.get("pv") != jwt_service.password_version(admin.password_hash):
            raise HTTPException(401, "密码已变更，请重新登录")
        return admin

    # 存量 admin_session 兼容（12 小时内自然淘汰）
    session = db.get(AdminSession, token)
    if session is None:
        raise HTTPException(401, "登录已失效，请重新登录")
    if session.expires_at <= datetime.utcnow():
        db.delete(session)
        db.commit()
        raise HTTPException(401, "登录已过期，请重新登录")

    admin = db.get(AdminUser, session.admin_id)
    if admin is None or admin.status != 1:
        raise HTTPException(403, "账号已停用")
    return admin


def require_admin(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> AdminUser:
    """FastAPI 依赖：所有管理端接口统一走 Bearer 会话校验。"""
    return verify_admin_session(db, authorization)


def revoke_session(db: Session, authorization: str | None) -> None:
    """退出登录：JWT 的 jti 入黑名单（存量会话则删行）。幂等。"""
    if not authorization or not authorization.startswith("Bearer "):
        return
    token = authorization[7:].strip()
    if token.count(".") == 2:
        try:
            jwt_service.revoke(db, token)
        except HTTPException:
            pass
    else:
        session = db.get(AdminSession, token)
        if session:
            db.delete(session)
            db.commit()


def revoke_all_sessions(db: Session, admin_id: int) -> None:
    """改密后强制该账号全部登录态重新登录。

    JWT 无需枚举：口令哈希变化使 `pv` 校验自动拒绝所有旧 token；
    此处只清理存量 admin_session 行。
    """
    db.query(AdminSession).filter(
        AdminSession.admin_id == admin_id
    ).delete()
    db.commit()
