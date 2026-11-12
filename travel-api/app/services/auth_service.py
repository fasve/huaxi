"""微信静默登录：真实 code2session + 自签 JWT（设计方案 7.5 / 接口 #0）。

与旧实现的差别（G4 P0 改造）：
- 旧：`MOCK_LOGIN` 下用 code 派生 mock openid，签发 `{user_id}.{hmac}` 简化串；
- 新：调用微信 `sns/jscode2session` 换取 openid/unionid/session_key，签发标准 JWT；
  `MOCK_LOGIN` 仅作**本地开发显式开启**的兜底分支，生产默认关闭；
- `session_key` 只落服务端 `user_wechat_session` 表（二期解密手机号用），
  绝不进入 JWT claims、接口响应或前端；
- AppID / AppSecret / JWT_SECRET 均只存服务端 .env。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User, UserWechatSession
from app.services import jwt_service

CODE2SESSION_PATH = "/sns/jscode2session"

# 微信常见 errcode：https://developers.weixin.qq.com/miniprogram/dev/OpenApiDoc/
ERRCODE_HINT = {
    40013: "AppID 无效，请检查服务端 WECHAT_APPID 配置",
    40125: "AppSecret 无效，请检查服务端 WECHAT_SECRET 配置",
    40029: "微信登录凭证无效或已过期，请重新获取 code",
    40163: "微信登录凭证已被使用，请重新获取 code",
    40226: "该微信账号被风控拦截，请稍后再试",
    45011: "微信接口调用过于频繁，请稍后再试",
}
RETRYABLE_ERRCODES = frozenset({-1})  # 系统繁忙；40029/45011 重试无意义


@dataclass(frozen=True)
class WechatIdentity:
    openid: str
    unionid: str = ""
    session_key: str = ""


def _mock_identity(code: str, device_id: str = "") -> WechatIdentity:
    """本地 dev 兜底：无真实凭据时仍能联调登录链路。

    device_id 由小程序 / PC 端提供稳定值，避免每次 wx.login 的 code 变化
    导致 mock 身份漂移（游客行程丢失）。生产模式完全忽略 device_id。
    """
    seed = device_id.strip() if device_id and device_id.strip() else code
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return WechatIdentity(
        openid="mock_" + digest,
        unionid="",
        session_key="mock_session_key_" + digest,
    )


def _request_json(url: str, params: dict) -> dict:
    """标准库 HTTP GET（零额外依赖），超时由 WECHAT_TIMEOUT_SECONDS 控制。"""
    req = Request(
        f"{url}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": "travel-api/1.0"},
        method="GET",
    )
    with urlopen(req, timeout=settings.WECHAT_TIMEOUT_SECONDS) as resp:
        payload = resp.read().decode("utf-8")
    return json.loads(payload)


def code2session(code: str, device_id: str = "") -> WechatIdentity:
    """换取微信身份。失败抛 HTTPException，绝不把原始错误体下发给前端。"""
    if settings.MOCK_LOGIN:
        return _mock_identity(code, device_id)
    if not settings.wechat_configured:
        raise HTTPException(
            503,
            "微信登录未就绪：请在服务端 .env 配置 WECHAT_APPID / WECHAT_SECRET，"
            "或仅用于本地开发时把 MOCK_LOGIN 设为 true",
        )

    url = settings.WECHAT_API_BASE.rstrip("/") + CODE2SESSION_PATH
    params = {
        "appid": settings.WECHAT_APPID.strip(),
        "secret": settings.WECHAT_SECRET.strip(),
        "js_code": code,
        "grant_type": "authorization_code",
    }
    retries = max(0, settings.WECHAT_MAX_RETRIES)
    for attempt in range(retries + 1):
        try:
            data = _request_json(url, params)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            if attempt < retries:
                continue
            raise HTTPException(502, "微信登录服务暂时不可达，请稍后重试") from exc

        try:
            errcode = int(data.get("errcode") or 0)
        except (TypeError, ValueError):
            errcode = -2
        if errcode == 0 and data.get("openid"):
            return WechatIdentity(
                openid=str(data["openid"]),
                unionid=str(data.get("unionid") or ""),
                session_key=str(data.get("session_key") or ""),
            )
        if errcode in RETRYABLE_ERRCODES and attempt < retries:
            continue
        hint = ERRCODE_HINT.get(errcode, "微信登录失败，请稍后重试")
        status = 429 if errcode == 45011 else (401 if errcode in (40029, 40163, 40226) else 502)
        raise HTTPException(status, f"{hint}（errcode={errcode}）")

    raise HTTPException(502, "微信登录服务暂时不可达，请稍后重试")


def _upsert_user(db: Session, ident: WechatIdentity) -> tuple[User, bool]:
    """按 openid 建档；有 unionid 时尝试合并同一微信开放平台主体。"""
    user = db.query(User).filter(User.openid == ident.openid).first()
    is_new = user is None
    if is_new and ident.unionid:
        same = db.query(User).filter(User.unionid == ident.unionid).first()
        if same is not None:
            same.openid = ident.openid
            user, is_new = same, False
    if user is None:
        user = User(
            openid=ident.openid,
            unionid=ident.unionid or None,
            role="member", status=1,
        )
        db.add(user)
    elif ident.unionid and not user.unionid:
        user.unionid = ident.unionid
    db.commit()
    return user, is_new


def _save_session_key(db: Session, ident: WechatIdentity) -> None:
    """session_key 仅存服务端，按 openid 覆盖更新；接口不返回。"""
    if not ident.session_key:
        return
    row = db.get(UserWechatSession, ident.openid)
    if row is None:
        db.add(UserWechatSession(
            openid=ident.openid,
            unionid=ident.unionid or None,
            session_key=ident.session_key,
            updated_at=datetime.utcnow(),
        ))
    else:
        row.session_key = ident.session_key
        row.unionid = ident.unionid or row.unionid
        row.updated_at = datetime.utcnow()
    db.commit()


def _token_out(user: User, token: str, expires_in: int, is_new: bool,
               **extra) -> dict:
    return dict(
        token=token,
        token_type="Bearer",
        expires_in=expires_in,
        user_id=user.id,
        is_new=is_new,
        **extra,
    )


def wechat_login(db: Session, code: str, device_id: str = "") -> dict:
    """接口 #0：wx.login(code) → code2session → upsert user → 签发 7 天 JWT。"""
    code = (code or "").strip()
    if not code:
        raise HTTPException(400, "code 不能为空")
    ident = code2session(code, device_id)
    user, is_new = _upsert_user(db, ident)
    if user.status != 1:
        raise HTTPException(403, "账号已被禁用")
    _save_session_key(db, ident)
    token, expires_in, _ = jwt_service.issue(
        subject=user.id, typ="wechat",
        openid=ident.openid, role=user.role or "member",
    )
    return _token_out(user, token, expires_in, is_new)


def anonymous_login(db: Session, device_id: str = "") -> dict:
    """PC 端游客模式：非微信场景签发 typ=anonymous 的 JWT。

    device_id 稳定映射同一游客身份，刷新 / 重登不会丢失已保存行程；
    与微信身份完全隔离（openid 前缀 anon_）。
    """
    if not settings.ALLOW_ANONYMOUS_GUEST:
        raise HTTPException(403, "匿名游客模式已关闭，请注册登录")
    did = (device_id or "").strip()
    if not did:
        did = uuid.uuid4().hex
    elif len(did) > 128:
        did = hashlib.sha256(did.encode("utf-8")).hexdigest()

    openid = "anon_" + hashlib.sha256(did.encode("utf-8")).hexdigest()[:24]
    user = db.query(User).filter(User.openid == openid).first()
    is_new = user is None
    if user is None:
        user = User(openid=openid, nickname="游客", role="member", status=1)
        db.add(user)
        db.commit()
    if user.status != 1:
        raise HTTPException(403, "账号已被禁用")
    token, expires_in, _ = jwt_service.issue(
        subject=user.id, typ="anonymous", openid=openid, role="member",
    )
    return _token_out(user, token, expires_in, is_new, device_id=did)


def refresh_token(db: Session, token: str) -> dict:
    """滑动续期：旧 jti 作废，返回新 JWT（设计方案 7.5）。"""
    new_token, expires_in = jwt_service.refresh(db, token, jwt_service.GUEST_TYPES)
    claims = jwt_service.decode(new_token)
    return dict(
        token=new_token, token_type="Bearer", expires_in=expires_in,
        user_id=int(claims["sub"]), is_new=False,
    )


def verify_legacy_hmac_token(token: str) -> int:
    """存量 `{id}.{sig}` 自签串的兼容校验，默认关闭且**不再签发**。

    仅在 ALLOW_LEGACY_HMAC_TOKEN=true 时由 resolve_token 调用。
    """
    import hmac

    user_id_s, _, sig = token.partition(".")
    if not user_id_s.isdigit() or not sig:
        raise HTTPException(401, "无效 token")
    expect = hmac.new(
        settings.WECHAT_SECRET.encode(), f"u{user_id_s}".encode(), hashlib.sha256
    ).hexdigest()[:16]
    if not hmac.compare_digest(sig, expect):
        raise HTTPException(401, "token 校验失败")
    return int(user_id_s)
