"""G4 P0 认证改造验证：真实 code2session + 标准 JWT。

运行：.venv/Scripts/python.exe scripts/verify_auth_jwt.py

覆盖：配置自检、JWT 标准 claims 与各类拒绝、jti 撤销与滑动续期、
微信 code2session 成功/错误码/重试/未配置、session_key 服务端留存、
四种登录方式（wechat / anonymous / account / admin）、类型隔离、
改密后旧 JWT 失效、旧版 HMAC 拒绝、存量 us_ 会话兼容、接口契约。
"""
from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException                       # noqa: E402
from jose import jwt                                   # noqa: E402

from app.config import settings                        # noqa: E402
from app.database import SessionLocal                  # noqa: E402
from app.main import app                               # noqa: E402
from app.models import (                               # noqa: E402
    AdminUser, TokenDenylist, User, UserAccount, UserSession, UserWechatSession,
)
from app.services import (                             # noqa: E402
    admin_auth as ADM, auth_service as A, jwt_service as J, user_auth as U,
)

PASS = 0
FAIL = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {label} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label} {extra}")


def raises(label: str, fn, status: int) -> None:
    try:
        fn()
        check(label, False, "未抛异常")
    except HTTPException as exc:
        check(label, exc.status_code == status, f"status={exc.status_code}")
    except Exception as exc:  # noqa: BLE001
        check(label, False, f"非预期异常 {type(exc).__name__}: {exc}")


def main() -> int:
    J.init_auth_tables()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    created_users: list[int] = []

    try:
        # ---------- 1) 配置与自检 ----------
        print("\n[1] 配置自检")
        cfg = J.assert_config()
        check("JWT 算法 HS256", cfg["jwt_alg"] == "HS256")
        check("有效期 7 天", settings.JWT_EXPIRE_HOURS == 168)
        check("JWT 密钥已配置（或 dev 兜底）", cfg["jwt_secret"])
        check("存量 HMAC 默认关闭", settings.ALLOW_LEGACY_HMAC_TOKEN is False)

        # ---------- 2) JWT 标准性 ----------
        print("\n[2] 标准 JWT 签发 / 校验")
        token, expires_in, claims = J.issue(
            subject=888001, typ="wechat", openid="o_verify", role="member", pv="pvA"
        )
        header = jwt.get_unverified_header(token)
        check("三段式结构", token.count(".") == 2)
        check("header alg/typ", header.get("alg") == "HS256" and header.get("typ") == "JWT", str(header))
        check("声明齐全", all(k in claims for k in
                            ("sub", "typ", "openid", "role", "iat", "nbf", "exp", "iss", "aud", "jti", "pv")))
        check("7 天 Bearer", expires_in == 604800)
        check("sub 为字符串", isinstance(J.decode(token)["sub"], str))
        check("openid 绑定", J.decode(token)["openid"] == "o_verify")

        secret = settings.JWT_SECRET.strip() or J._secret()
        raises("篡改签名被拒", lambda: J.decode(token[:-3] + "abc"), 401)
        raises("旧 HMAC 串被拒", lambda: J.decode("888001.deadbeef"), 401)
        expired = jwt.encode({**claims, "iat": int(time.time()) - 500,
                              "nbf": int(time.time()) - 500,
                              "exp": int(time.time()) - 120}, secret, algorithm="HS256")
        raises("过期被拒", lambda: J.decode(expired), 401)
        check("撤销场景允许宽松解码过期 token", J.decode(expired, allow_expired=True)["sub"] == "888001")
        for key, val in (("aud", "other-client"), ("iss", "other-api")):
            forged = jwt.encode({**claims, key: val}, secret, algorithm="HS256")
            raises(f"{key} 不匹配被拒", lambda t=forged: J.decode(t), 401)
        future = jwt.encode({**claims, "nbf": int(time.time()) + 3600}, secret, algorithm="HS256")
        raises("nbf 未生效被拒", lambda: J.decode(future), 401)

        # ---------- 3) 撤销与滑动续期 ----------
        print("\n[3] jti 黑名单 / 滑动续期")
        real, _, real_claims = J.issue(subject=888002, typ="wechat", openid="o_revoke")
        check("新 token 可解析", J.resolve(db, real, J.GUEST_TYPES)["sub"] == "888002")
        J.revoke(db, real, reason="logout")
        raises("登出后立即失效", lambda: J.resolve(db, real, J.GUEST_TYPES), 401)
        check("黑名单已落库", db.get(TokenDenylist, real_claims["jti"]) is not None)
        fresh, fresh_exp = J.refresh(db, token, J.GUEST_TYPES)
        check("续期换发新 jti", fresh != token and J.decode(fresh)["jti"] != claims["jti"])
        check("续期保留身份与 pv", J.decode(fresh)["sub"] == "888001" and J.decode(fresh)["pv"] == "pvA")
        check("续期有效期重置", fresh_exp == 604800)
        raises("续期后旧 token 失效", lambda: J.resolve(db, token, J.GUEST_TYPES), 401)
        raises("管理端 token 不能续期游客身份",
               lambda: J.refresh(db, fresh, J.ADMIN_TYPES), 403)

        # ---------- 4) 微信登录（dev mock 分支） ----------
        print("\n[4] 微信静默登录 / session_key 服务端留存")
        device = "verify_device_" + suffix
        res = A.wechat_login(db, "code_" + suffix, device)
        wtok = res["token"]
        wc = J.decode(wtok)
        created_users.append(res["user_id"])
        check("返回标准 JWT", wtok.count(".") == 2)
        check("Bearer + 7 天", res["token_type"] == "Bearer" and res["expires_in"] == 604800)
        check("claims typ=wechat", wc["typ"] == "wechat")
        check("JWT 与 openid 绑定", wc["openid"].startswith("mock_"))
        check("响应不下发 session_key", "session_key" not in res)
        check("JWT 不含 session_key", "session_key" not in wc)
        check("session_key 仅存服务端", db.get(UserWechatSession, wc["openid"]) is not None)
        check("同一设备身份稳定",
              A.wechat_login(db, "another_code_" + suffix, device)["user_id"] == res["user_id"])
        check("游客接口可解析", U.resolve_token(db, wtok) == res["user_id"])
        check("account_out 标记游客", U.account_out(db, res["user_id"])["is_guest"] is True)

        # ---------- 5) 真实 code2session（本地注入响应，不发外网） ----------
        print("\n[5] 真实 code2session 分支")
        original = (settings.MOCK_LOGIN, settings.WECHAT_APPID, settings.WECHAT_SECRET,
                    A._request_json)
        calls: list[dict] = []
        try:
            settings.MOCK_LOGIN = False
            settings.WECHAT_APPID = "wx_real_appid"
            settings.WECHAT_SECRET = "wx_real_secret"
            check("真实凭据判定", settings.wechat_configured is True)

            def ok_response(url, params):
                calls.append(params)
                return {"openid": "oREAL_" + suffix, "unionid": "uREAL_" + suffix,
                        "session_key": "sk_secret_value", "expires_in": 7200}

            A._request_json = ok_response
            ident = A.code2session("wx_code_123")
            check("换取 openid", ident.openid == "oREAL_" + suffix)
            check("换取 unionid", ident.unionid == "uREAL_" + suffix)
            check("换取 session_key", ident.session_key == "sk_secret_value")
            check("请求参数完整", calls[0]["grant_type"] == "authorization_code"
                  and calls[0]["js_code"] == "wx_code_123" and calls[0]["appid"] == "wx_real_appid")
            check("URL 指向 jscode2session", settings.WECHAT_API_BASE.rstrip("/").endswith("api.weixin.qq.com"))

            real_login = A.wechat_login(db, "wx_code_123")
            created_users.append(real_login["user_id"])
            rc = J.decode(real_login["token"])
            check("真实模式签发 JWT", rc["typ"] == "wechat" and rc["openid"] == ident.openid)
            check("session_key 落库", db.get(UserWechatSession, ident.openid).session_key == "sk_secret_value")
            check("unionid 写回 user", db.get(User, real_login["user_id"]).unionid == ident.unionid)
            check("真实模式忽略 device_id",
                  A.wechat_login(db, "wx_code_123", "some_device")["user_id"] == real_login["user_id"])

            for errcode, status in ((40029, 401), (40163, 401), (45011, 429), (40013, 502), (99999, 502)):
                A._request_json = lambda u, p, e=errcode: {"errcode": e, "errmsg": "mock error"}
                raises(f"errcode {errcode} → {status}", lambda: A.code2session("bad_code"), status)

            # errcode=-1 系统繁忙：重试后成功
            attempts = {"n": 0}

            def flaky(url, params):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    return {"errcode": -1, "errmsg": "system error"}
                return {"openid": "oRETRY_" + suffix, "session_key": "sk_retry"}

            A._request_json = flaky
            check("-1 自动重试后成功", A.code2session("retry_code").openid == "oRETRY_" + suffix
                  and attempts["n"] == 2)

            def net_error(url, params):
                raise OSError("network down")

            A._request_json = net_error
            raises("网络异常 → 502", lambda: A.code2session("net_code"), 502)

            # 未配置凭据：503（不发起外网请求）
            settings.WECHAT_APPID = "test_appid"
            settings.WECHAT_SECRET = "test_secret"
            A._request_json = lambda u, p: (_ for _ in ()).throw(AssertionError("不应发请求"))
            raises("生产缺凭据 → 503", lambda: A.code2session("x"), 503)
        finally:
            (settings.MOCK_LOGIN, settings.WECHAT_APPID, settings.WECHAT_SECRET,
             A._request_json) = original

        # ---------- 6) PC 匿名游客 ----------
        print("\n[6] PC 匿名游客")
        anon = A.anonymous_login(db, "anon_dev_" + suffix)
        created_users.append(anon["user_id"])
        check("typ=anonymous", J.decode(anon["token"])["typ"] == "anonymous")
        check("同设备身份稳定", A.anonymous_login(db, "anon_dev_" + suffix)["user_id"] == anon["user_id"])
        check("游客接口可解析", U.resolve_token(db, anon["token"]) == anon["user_id"])

        # ---------- 7) 账号密码登录 ----------
        print("\n[7] 账号密码登录")
        uname = "jwt_" + suffix
        reg = U.register(db, uname, "pass1234", "验证账号")
        created_users.append(reg["user"]["user_id"])
        rclaims = J.decode(reg["token"])
        check("注册签发 JWT", rclaims["typ"] == "account")
        check("账号 token 带 pv", bool(rclaims.get("pv")))
        lg = U.login(db, uname, "pass1234")
        check("登录签发 JWT", U.resolve_token(db, lg["token"]) == reg["user"]["user_id"])
        check("account_out 非游客", U.account_out(db, reg["user"]["user_id"])["is_guest"] is False)
        raises("错误密码 401", lambda: U.login(db, uname, "wrong_pwd"), 401)

        # ---------- 8) 管理端 JWT / 类型隔离 / 改密失效 ----------
        print("\n[8] 管理端 JWT 与隔离")
        admin = db.query(AdminUser).filter(AdminUser.username == "admin").first()
        adm_tok, adm_exp = ADM.issue_session(db, admin)
        check("管理端 JWT typ=admin", J.decode(adm_tok)["typ"] == "admin")
        check("管理端 12 小时", adm_exp == settings.ADMIN_SESSION_HOURS * 3600)
        check("管理端校验通过", ADM.verify_admin_session(db, "Bearer " + adm_tok).id == admin.id)
        raises("游客接口拒绝 admin JWT", lambda: U.resolve_token(db, adm_tok), 403)
        raises("管理接口拒绝游客 JWT", lambda: ADM.verify_admin_session(db, "Bearer " + lg["token"]), 403)

        old_hash = admin.password_hash
        try:
            admin.password_hash = ADM.hash_password("another_password")
            db.commit()
            raises("改密后旧管理 JWT 失效",
                   lambda: ADM.verify_admin_session(db, "Bearer " + adm_tok), 401)
        finally:
            admin.password_hash = old_hash
            db.commit()

        # ---------- 9) 存量兼容 ----------
        print("\n[9] 存量 token 兼容（默认拒绝旧 HMAC）")
        raises("旧 HMAC 串拒绝", lambda: U.resolve_token(db, "1.deadbeef"), 401)
        settings.ALLOW_LEGACY_HMAC_TOKEN = True
        try:
            import hashlib
            import hmac as _hmac
            sig = _hmac.new(settings.WECHAT_SECRET.encode(), b"u1", hashlib.sha256).hexdigest()[:16]
            legacy = f"1.{sig}"
            # 仅校验签名解析，不依赖 id=1 用户是否存在
            check("legacy 签名算法仍可校验", A.verify_legacy_hmac_token(legacy) == 1)
        finally:
            settings.ALLOW_LEGACY_HMAC_TOKEN = False

        us_token = "us_verify_" + suffix
        db.add(UserSession(token=us_token, user_id=reg["user"]["user_id"],
                           expires_at=datetime.utcnow() + timedelta(hours=1)))
        db.commit()
        check("存量 us_ 会话可用", U.resolve_token(db, us_token) == reg["user"]["user_id"])
        U.revoke_session(db, us_token)
        raises("存量会话登出后失效", lambda: U.resolve_token(db, us_token), 401)

        # ---------- 10) 接口契约 ----------
        print("\n[10] HTTP 接口契约")
        paths = app.openapi()["paths"]
        for p, method in (("/api/v1/auth/wechat/login", "post"),
                          ("/api/v1/auth/anonymous", "post"),
                          ("/api/v1/auth/refresh", "post"),
                          ("/api/v1/auth/logout", "post")):
            check(f"{method.upper()} {p} 已注册", method in paths.get(p, {}))
        token_schema = paths["/api/v1/auth/wechat/login"]["post"]["responses"]["200"]
        check("登录响应使用 TokenOut", "TokenOut" in str(token_schema))

        # ---------- 清理 ----------
        db.query(TokenDenylist).filter(
            TokenDenylist.subject.in_(["888001", "888002"])
        ).delete(synchronize_session=False)
        db.query(UserWechatSession).filter(
            UserWechatSession.openid.in_([wc["openid"], "oREAL_" + suffix])
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    print(f"\n{'=' * 46}\n结果：{PASS} 项通过 / {FAIL} 项失败\n{'=' * 46}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
