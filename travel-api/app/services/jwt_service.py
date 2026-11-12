"""统一 JWT 服务（设计方案 7.5 与「登录鉴权」技术选型）。

技术口径：
- `python-jose` 自签 **标准 JWT**（RFC 7519，HS256），不再是 `{user_id}.{hmac}` 简化串；
- claims：`sub / typ / openid / role / iat / nbf / exp / iss / aud / jti / pv`；
- 校验：签名 + `exp` + `nbf` + `iss` + `aud` + `typ` 白名单，带 30s 时钟容差；
- `typ` 隔离：游客端只接受 `wechat/anonymous/account`，管理端只接受 `admin`，
  防止管理端 token 越权访问游客接口（反之亦然）；
- 撤销：`token_denylist` 按 `jti` 记录，退出登录 / 续期旧 token 立即失效；
- 滑动续期：`/auth/refresh` 在有效期内换新 token，旧 jti 入黑名单；
- `pv`（password version）：由口令哈希派生，改密后历史 JWT 自动失效。

AppSecret 与 JWT_SECRET 均只存在于服务端 .env，不下发前端、不写入小程序代码。
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import TokenDenylist, UserWechatSession

# 游客端 token 类型（微信静默登录 / PC 匿名游客 / 账号密码登录）
GUEST_TYPES = frozenset({"wechat", "anonymous", "account"})
# 管理端 token 类型
ADMIN_TYPES = frozenset({"admin"})
ALL_TYPES = GUEST_TYPES | ADMIN_TYPES

# dev 未配置 JWT_SECRET 时的进程级临时密钥（重启即失效，生产禁用）
_DEV_SECRET: str | None = None


def _secret() -> str:
    configured = settings.JWT_SECRET.strip()
    if configured:
        return configured
    if settings.MOCK_LOGIN:
        global _DEV_SECRET
        if _DEV_SECRET is None:
            _DEV_SECRET = secrets.token_urlsafe(48)
            print(
                "[travel-api][WARN] JWT_SECRET 未配置：已生成进程级临时密钥，"
                "仅开发可用，重启后旧 token 全部失效"
            )
        return _DEV_SECRET
    raise HTTPException(503, "服务端未完成 JWT 配置（JWT_SECRET 为空），请联系管理员")


def assert_config() -> dict:
    """启动自检：把认证模式与缺失配置打到日志，避免带病上线。"""
    if settings.JWT_ALG != "HS256":
        raise RuntimeError(f"当前仅支持 JWT_ALG=HS256，收到 {settings.JWT_ALG}")

    if settings.MOCK_LOGIN:
        mode = "mock_code2session(dev)"
        print("[travel-api][AUTH] 微信登录：MOCK_LOGIN=true，走开发 mock 分支（禁止用于生产）")
    elif settings.wechat_configured:
        mode = "real_code2session"
        print("[travel-api][AUTH] 微信登录：真实 code2session 已启用")
    else:
        mode = "real_code2session(missing_credentials)"
        print(
            "[travel-api][AUTH][ERROR] MOCK_LOGIN=false 但 WECHAT_APPID/WECHAT_SECRET "
            "仍为占位值，微信登录将返回 503；请填入真实凭据"
        )

    if not settings.jwt_configured and not settings.MOCK_LOGIN:
        print("[travel-api][AUTH][ERROR] JWT_SECRET 为空，登录接口将返回 503")

    return dict(
        mode=mode,
        jwt_alg=settings.JWT_ALG,
        jwt_expire_hours=settings.JWT_EXPIRE_HOURS,
        jwt_secret=settings.jwt_configured or bool(_DEV_SECRET),
        wechat_configured=settings.wechat_configured,
        legacy_hmac=settings.ALLOW_LEGACY_HMAC_TOKEN,
    )


def init_auth_tables() -> None:
    """幂等建表：微信 session_key 与 JWT 撤销名单（不动任何既有表数据）。"""
    from app.database import Base, engine

    Base.metadata.create_all(
        engine, tables=[UserWechatSession.__table__, TokenDenylist.__table__]
    )


def password_version(password_hash: str) -> str:
    """口令哈希派生版本号：改密后旧 JWT 的 pv 失配即被拒绝。"""
    return hashlib.sha256((password_hash or "").encode("utf-8")).hexdigest()[:16]


def issue(
    *, subject: int, typ: str, openid: str = "", role: str = "member",
    pv: str = "", hours: int | None = None,
) -> tuple[str, int, dict]:
    """签发标准 JWT，返回 (token, 有效秒数, claims)。"""
    if typ not in ALL_TYPES:
        raise ValueError(f"未知 token 类型：{typ}")
    now = datetime.now(timezone.utc)
    ttl_hours = hours if hours is not None else settings.JWT_EXPIRE_HOURS
    exp = now + timedelta(hours=ttl_hours)
    claims: dict = {
        "sub": str(subject),
        "typ": typ,
        "openid": openid,
        "role": role,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "jti": uuid.uuid4().hex,
    }
    if pv:
        claims["pv"] = pv
    token = jwt.encode(claims, _secret(), algorithm=settings.JWT_ALG)
    return token, int(ttl_hours * 3600), claims


def decode(token: str, *, allow_expired: bool = False) -> dict:
    """校验签名与全部标准 claims；失败统一抛 401。"""
    if not token or token.count(".") != 2:
        raise HTTPException(401, "无效 token")
    try:
        return jwt.decode(
            token,
            _secret(),
            algorithms=[settings.JWT_ALG],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={
                "leeway": settings.JWT_LEEWAY_SECONDS,
                "verify_signature": True,
                "verify_exp": not allow_expired,
                "verify_nbf": not allow_expired,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except ExpiredSignatureError:
        raise HTTPException(401, "登录已过期，请重新登录")
    except JWTError:
        raise HTTPException(401, "token 校验失败，请重新登录")


def resolve(db: Session, token: str, allowed_types: frozenset[str] | set[str],
            *, pv: str | None = None) -> dict:
    """请求鉴权入口：类型白名单 + 黑名单 + 口令版本。"""
    claims = decode(token)
    if claims.get("typ") not in allowed_types:
        raise HTTPException(403, "token 类型与当前端不匹配")
    if not str(claims.get("sub", "")).isdigit():
        raise HTTPException(401, "无效 token")
    if db.get(TokenDenylist, str(claims.get("jti", ""))) is not None:
        raise HTTPException(401, "登录已失效，请重新登录")
    if pv is not None and claims.get("pv") != pv:
        raise HTTPException(401, "凭据已变更，请重新登录")
    return claims


def _cleanup(db: Session) -> None:
    db.query(TokenDenylist).filter(
        TokenDenylist.expires_at < datetime.utcnow()
    ).delete()


def revoke(db: Session, token: str, reason: str = "logout") -> dict:
    """把 jti 加入黑名单；已过期 token 也允许撤销（不校验 exp）。"""
    claims = decode(token, allow_expired=True)
    jti = str(claims.get("jti", ""))
    if not jti or db.get(TokenDenylist, jti) is not None:
        return claims
    exp = int(claims.get("exp", 0))
    _cleanup(db)
    db.add(TokenDenylist(
        jti=jti,
        subject=str(claims.get("sub", "")),
        kind=str(claims.get("typ", "")),
        reason=reason,
        expires_at=datetime.utcfromtimestamp(exp) if exp else datetime.utcnow(),
    ))
    db.commit()
    return claims


def refresh(db: Session, token: str, allowed_types: frozenset[str] | set[str],
            *, hours: int | None = None) -> tuple[str, int]:
    """滑动续期：旧 jti 作废，用同一身份签发新 token。"""
    claims = decode(token)
    if claims.get("typ") not in allowed_types:
        raise HTTPException(403, "token 类型与当前端不匹配")
    revoke(db, token, reason="refresh")
    new_token, expires_in, _ = issue(
        subject=int(claims["sub"]),
        typ=str(claims["typ"]),
        openid=str(claims.get("openid", "")),
        role=str(claims.get("role", "member")),
        pv=str(claims.get("pv", "")),
        hours=hours,
    )
    return new_token, expires_in
