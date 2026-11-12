"""游客端账号认证（PC / 小程序通用）——统一 JWT Bearer。

G4 P0 改造后的实现口径：
- 账号主体复用 `user` 表，行程 user_id 不变；登录凭据单独放 `user_account`；
- 口令：PBKDF2-HMAC-SHA256 + 随机盐，仅存哈希；
- **登录态：标准 JWT（python-jose HS256，7 天，typ=account）**，与微信静默登录
  （typ=wechat）、PC 匿名游客（typ=anonymous）共用 `jwt_service` 校验；
  JWT 与 openid 绑定，退出登录按 jti 进 `token_denylist` 立即失效；
- 存量平滑：旧 `us_` 服务端会话继续校验至自然过期（**不再签发**）；
  旧 `{id}.{hmac}` 自签串默认拒绝，可由 ALLOW_LEGACY_HMAC_TOKEN 临时放开。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User, UserAccount, UserSession
from app.services import jwt_service
from app.services.admin_auth import hash_password, verify_password

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{2,32}$")
PHONE_RE = re.compile(r"^1\d{10}$")

# 账号不存在时也做一次等价哈希运算，避免账号枚举的时间差
_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("no-such-account")
    return _DUMMY_HASH


def init_user_auth() -> None:
    """启动时幂等建表（不动既有 user 表与数据）。

    `user_session` 仅为存量 `us_` token 的兼容通道保留，新登录不再写该表。
    """
    from app.database import Base, engine

    Base.metadata.create_all(
        engine, tables=[UserAccount.__table__, UserSession.__table__]
    )


def _session_payload(db: Session, user_id: int, password_hash: str = "") -> dict:
    """账号密码登录 / 注册成功后签发 7 天 JWT。"""
    user = db.get(User, user_id)
    token, expires_in, _ = jwt_service.issue(
        subject=user_id, typ="account",
        openid=(user.openid if user else ""),
        role=(user.role if user and user.role else "member"),
        pv=jwt_service.password_version(password_hash) if password_hash else "",
    )
    return dict(
        token=token, token_type="Bearer", expires_in=expires_in,
        user=account_out(db, user_id),
    )


def resolve_token(db: Session, token: str | None) -> int:
    """统一解析游客 token；失败抛 401/403，返回 user.id。

    - 三段式标准 JWT：签名 / exp / iss / aud / typ / jti 黑名单 / 账号 pv 全校验；
    - `us_...`：存量服务端会话（兼容，不再签发）；
    - `{id}.{sig}`：旧自签 HMAC 串，默认拒绝。
    """
    if not token or not token.strip():
        raise HTTPException(401, "请先登录")
    token = token.strip()

    # ---- 1) 标准 JWT（当前唯一签发口径）
    if token.count(".") == 2:
        claims = jwt_service.resolve(db, token, jwt_service.GUEST_TYPES)
        user_id = int(claims["sub"])
        user = db.get(User, user_id)
        if user is None or user.status != 1:
            raise HTTPException(403, "账号已被禁用")
        if claims.get("typ") == "account":
            account = db.query(UserAccount).filter(
                UserAccount.user_id == user_id
            ).first()
            if account is None or account.status != 1:
                raise HTTPException(403, "账号已被禁用")
            if claims.get("pv") and claims["pv"] != jwt_service.password_version(
                account.password_hash
            ):
                raise HTTPException(401, "密码已变更，请重新登录")
        return user_id

    # ---- 2) 存量服务端会话（平滑过渡，7 天后自然淘汰）
    if token.startswith("us_"):
        session = db.get(UserSession, token)
        if session is None:
            raise HTTPException(401, "登录已失效，请重新登录")
        if session.expires_at <= datetime.utcnow():
            db.delete(session)
            db.commit()
            raise HTTPException(401, "登录已过期，请重新登录")
        account = db.query(UserAccount).filter(
            UserAccount.user_id == session.user_id
        ).first()
        if account is not None and account.status != 1:
            raise HTTPException(403, "账号已被禁用")
        user = db.get(User, session.user_id)
        if user is None or user.status != 1:
            raise HTTPException(403, "账号已被禁用")
        return session.user_id

    # ---- 3) 旧版自签 HMAC 串：默认拒绝（前端 401 拦截器会自动重登）
    if settings.ALLOW_LEGACY_HMAC_TOKEN:
        from app.services.auth_service import verify_legacy_hmac_token

        user_id = verify_legacy_hmac_token(token)
        user = db.get(User, user_id)
        if user is None or user.status != 1:
            raise HTTPException(403, "账号已被禁用")
        return user_id

    raise HTTPException(401, "登录态已升级，请重新登录")


def account_out(db: Session, user_id: int) -> dict:
    """当前身份。匿名 / 微信游客返回 is_guest=True，便于前端区分引导。"""
    user = db.get(User, user_id)
    account = db.query(UserAccount).filter(
        UserAccount.user_id == user_id
    ).first()
    if account is None:
        return dict(
            user_id=user_id, username="", nickname=(user.nickname if user and user.nickname else "游客"),
            phone="", is_guest=True,
            created_at=user.created_at.isoformat(timespec="seconds") if user and user.created_at else "",
        )
    phone = account.phone or ""
    masked = phone[:3] + "****" + phone[-4:] if len(phone) == 11 else phone
    return dict(
        user_id=user_id,
        username=account.username,
        nickname=account.nickname or account.username,
        phone=masked,
        is_guest=False,
        created_at=account.created_at.isoformat(timespec="seconds") if account.created_at else "",
    )


def register(db: Session, username: str, password: str,
             nickname: str = "", phone: str | None = None) -> dict:
    """注册并直接登录；用户名唯一，手机号可选但唯一。"""
    username = username.strip()
    nickname = nickname.strip()
    phone = (phone or "").strip() or None

    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(400, "用户名需为 2~32 位中英文、数字或下划线")
    if len(password) < 6 or len(password) > 64:
        raise HTTPException(400, "密码长度需为 6~64 位")
    if phone and not PHONE_RE.fullmatch(phone):
        raise HTTPException(400, "手机号格式不正确（11 位数字）")
    if db.query(UserAccount).filter(UserAccount.username == username).first():
        raise HTTPException(400, "该用户名已被注册")
    if phone and db.query(UserAccount).filter(UserAccount.phone == phone).first():
        raise HTTPException(400, "该手机号已被注册")

    password_hash = hash_password(password)
    user = User(
        openid="acct_" + uuid.uuid4().hex[:24],
        nickname=nickname or username,
        role="member", status=1,
    )
    db.add(user)
    db.flush()  # 取得自增 id，供账号引用
    db.add(UserAccount(
        user_id=user.id,
        username=username,
        phone=phone,
        password_hash=password_hash,
        nickname=nickname or username,
        status=1,
        last_login_at=datetime.utcnow(),
    ))
    db.commit()
    return _session_payload(db, user.id, password_hash)


def login(db: Session, account: str, password: str) -> dict:
    """账号或手机号 + 密码登录；失败统一返回 401。"""
    key = account.strip()
    cond = [UserAccount.username == key]
    if PHONE_RE.fullmatch(key):
        cond.append(UserAccount.phone == key)
    row = db.query(UserAccount).filter(or_(*cond)).first()
    if row is None:
        verify_password(password, _dummy_hash())
        raise HTTPException(401, "账号或密码错误")
    if not verify_password(password, row.password_hash):
        raise HTTPException(401, "账号或密码错误")
    if row.status != 1:
        raise HTTPException(403, "账号已被禁用，请联系系统维护人员")
    user = db.get(User, row.user_id)
    if user is None or user.status != 1:
        raise HTTPException(403, "账号已被禁用，请联系系统维护人员")
    row.last_login_at = datetime.utcnow()
    db.commit()
    return _session_payload(db, row.user_id, row.password_hash)


def revoke_session(db: Session, token: str | None) -> None:
    """退出登录：JWT 的 jti 入黑名单；存量 us_ 会话删行。幂等，不抛错。"""
    if not token:
        return
    t = token.strip()
    if t.count(".") == 2:
        try:
            jwt_service.revoke(db, t)
        except HTTPException:
            pass  # token 已失效 / 过期：前端仍会清除本地状态
    elif t.startswith("us_"):
        session = db.get(UserSession, t)
        if session:
            db.delete(session)
            db.commit()
