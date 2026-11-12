"""T5 分享海报服务：排版数据 + 小程序码（接口 #7：POST /trips/{id}/poster）。

海报绘制在**客户端 canvas** 完成（小程序 canvas 2d），服务端只提供：
- 排版数据（模式徽标 / 逐日 POI 摘要 / 住宿 / 品牌）；
- 右下角二维码：
  * 生产（配置了 WECHAT_APPID/SECRET 且非 mock）：调用微信
    `wxa/getwxacodeunlimit` 生成**小程序码**，按 trip 落盘缓存；
  * 兜底（本地 dev / 凭据未配）：`qrcode` 库生成普通二维码，
    内容为 PC 游客端行程页地址（未配置域名时为文案占位）；
- 分享流水（guest_stats_service.log_share，供 A5 统计分享次数）。

小程序码 scene 上限 32 字符，行程短码 t_xxxx 满足要求。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.models import Trip
from app.services import guest_stats_service as stats
from app.services.trip_service import MODE_NAMES, trip_to_out

POSTER_DIR = BASE_DIR / "static" / "poster"
CST = timezone(timedelta(hours=8))  # 中国标准时间，无夏令时
QR_SIZE_BOX = 430            # 输出 PNG 尺寸（px）
BRAND_NAME = "花溪智游"
BRAND_SLOGAN = "花溪区个性化旅游路线规划"

# access_token 进程内缓存（7200s 有效，提前 5 分钟刷新）
_token_cache: dict[str, object] = {"value": "", "expires_at": 0.0}


def _wx_get(path: str, params: dict) -> dict:
    from app.services.auth_service import _request_json  # 复用超时/UA 口径

    url = settings.WECHAT_API_BASE.rstrip("/") + path
    return _request_json(url, params)


def _get_access_token() -> str:
    """stable 接口取普通 access_token（不占用定时刷新，失败直接抛）。"""
    now = datetime.utcnow().timestamp()
    if _token_cache["value"] and now < float(_token_cache["expires_at"]):
        return str(_token_cache["value"])
    data = _wx_get("/cgi-bin/stable_token", {
        "grant_type": "client_credential",
        "appid": settings.WECHAT_APPID.strip(),
        "secret": settings.WECHAT_SECRET.strip(),
    })
    if not data.get("access_token"):
        errcode = data.get("errcode", -1)
        raise RuntimeError(f"获取 access_token 失败（errcode={errcode}）")
    _token_cache["value"] = data["access_token"]
    _token_cache["expires_at"] = now + min(int(data.get("expires_in", 7200)) - 300, 7200)
    return str(_token_cache["value"])


def _fetch_wxacode(trip_id: str) -> bytes:
    """真实小程序码（getwxacodeunlimit，scene 带 trip 短码）。"""
    token = _get_access_token()
    payload = json.dumps({
        "scene": f"t={trip_id}",
        "page": "pages/trip/trip",
        "check_path": False,        # 未发布版本也可生成
        "env_version": "release",
        "width": QR_SIZE_BOX,
    }).encode("utf-8")
    req = Request(
        f"{settings.WECHAT_API_BASE.rstrip('/')}/wxa/getwxacodeunlimit"
        f"?access_token={token}",
        data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "travel-api/1.0"},
    )
    with urlopen(req, timeout=settings.WECHAT_TIMEOUT_SECONDS) as resp:
        body = resp.read()
    # 失败时微信返回 JSON（errcode），成功是 image bytes
    if body[:1] == b"{":
        data = json.loads(body.decode("utf-8"))
        raise RuntimeError(
            f"小程序码生成失败（errcode={data.get('errcode')}）")
    if not body:
        raise RuntimeError("小程序码返回空内容")
    return body


def _fallback_qrcode(content: str) -> bytes:
    """无微信凭据时的普通二维码（qrcode + Pillow）。"""
    import io

    import qrcode
    from PIL import Image

    qr = qrcode.QRCode(
        version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10, border=2,
    )
    qr.add_data(content)
    qr.make(fit=True)
    img: Image.Image = qr.make_image(fill_color="#1d3a2c", back_color="white")
    img = img.resize((QR_SIZE_BOX, QR_SIZE_BOX))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _qr_file(trip_id: str, kind: str) -> Path:
    return POSTER_DIR / f"qr_{kind}_{trip_id}.png"


def _share_url(trip_id: str) -> str:
    origin = settings.PORTAL_ORIGIN.strip().rstrip("/")
    if origin:
        return f"{origin}/trip/{trip_id}"
    return f"{BRAND_NAME} · 行程 {trip_id}（PC 端地址部署后生效）"


def _build_qr(trip_id: str) -> dict:
    """优先真实小程序码；凭据未配 / 调用失败时降级普通二维码。"""
    POSTER_DIR.mkdir(parents=True, exist_ok=True)

    can_wxacode = (
        settings.wechat_configured and not settings.MOCK_LOGIN
    )
    if can_wxacode:
        cached = _qr_file(trip_id, "wxacode")
        if cached.exists() and cached.stat().st_size > 0:
            return dict(kind="wxacode", url=f"/static/poster/{cached.name}",
                        scene=f"t={trip_id}", note="官方小程序码（已缓存）")
        try:
            data = _fetch_wxacode(trip_id)
            cached.write_bytes(data)
            return dict(kind="wxacode", url=f"/static/poster/{cached.name}",
                        scene=f"t={trip_id}", note="官方小程序码")
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
            print(f"[travel-api][POSTER] 小程序码生成降级为普通二维码：{exc}")

    digest = hashlib.sha1(f"poster|{trip_id}".encode()).hexdigest()[:8]
    fp = _qr_file(f"{digest}", "fallback")
    if not fp.exists():
        fp.write_bytes(_fallback_qrcode(_share_url(trip_id)))
    return dict(
        kind="qrcode", url=f"/static/poster/{fp.name}", scene=f"t={trip_id}",
        note="本地/演示二维码：配置 WECHAT_APPID/SECRET 且 MOCK_LOGIN=false 后自动切换为官方小程序码",
    )


def get_poster(db: Session, trip_id: str,
               user_id: int | None = None, channel: str = "poster") -> dict:
    """接口 #7：海报排版数据 + 二维码 + 分享参数（canvas 端绘制）。"""
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在或已过期")

    full = trip_to_out(db, trip)
    days_brief = [
        dict(
            day_index=d["day_index"], theme=d["theme"],
            day_cost=d["day_cost"],
            items=[dict(slot=it["slot"], slot_name=it["slot_name"],
                        name=it["name"], cost=it["cost"])
                   for it in d["items"] if it["poi_id"]],
        )
        for d in full["days_plan"]
    ]

    qr = _build_qr(trip_id)
    title = f"{full['mode_name']} · {trip.days}天花溪之旅"
    share_title = f"我在花溪排了份{trip.days}天{full['mode_name']}行程，快来看"
    stats.log_share(db, trip_id=trip_id, channel=channel, user_id=user_id)

    return dict(
        trip_id=trip_id,
        title=title,
        mode=trip.mode, mode_name=full["mode_name"],
        days=trip.days,
        budget=trip.budget,
        total_cost=full["total_cost"],
        budget_usage=full["budget_usage"],
        score=full["score"],
        hotel=(dict(name=full["hotel"]["name"], nights=full["hotel_nights"])
               if full.get("hotel") else None),
        days_plan=days_brief,
        brand=dict(name=BRAND_NAME, slogan=BRAND_SLOGAN),
        qr=qr,
        share=dict(
            title=share_title,
            path=f"/pages/trip/trip?id={trip_id}",
            url=_share_url(trip_id),
        ),
        generated_at=datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
    )
