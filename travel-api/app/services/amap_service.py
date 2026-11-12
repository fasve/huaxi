"""高德开放平台服务端代理：**仅用于位置解析**（逆地理编码 / IP 城市级定位）。

职责边界（重要）：
- 天气数据**不再**由高德提供，项目统一使用 Open-Meteo（见 `app/services/open_meteo.py`）；
- 高德 Web 服务 key 只在服务端 `.env` 保存，绝不下发浏览器；
- 浏览器精定位得到的坐标经 `POST /location/resolve` 传入（放在 body，不落在访问日志 URL 上），
  服务端做逆地理编码拿到所在区县 adcode / 地名；浏览器拒绝授权时退化为高德 IP 定位（城市级）；
- 坐标 / 逆地理结果只在进程内存做短时缓存，不写入数据库、不关联账号；
- 未配置 / 占位符 / 网络失败 / 高德报错均返回 200 + 结构化提示，由前端优雅降级；
- 仅使用高德开放平台合规服务，坐标系统一 GCJ-02（供前端高德底图使用）。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from app.config import settings
from app.services.cache import ip_cache, location_cache

REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
IP_URL = "https://restapi.amap.com/v3/ip"

ADCODE_RE = re.compile(r"^\d{6}$")
PRIVATE_IP_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|::1$|fc|fd|fe80)",
    re.I,
)


def key_configured() -> bool:
    """高德 key 为 32 位十六进制串；占位符、空值均视为未配置。"""
    return bool(re.fullmatch(r"[0-9a-fA-F]{32}", (settings.amap_key or "").strip()))


def default_adcode() -> str:
    code = str(settings.AMAP_CITY_ADCODE or "").strip()
    return code if ADCODE_RE.fullmatch(code) else "520111"


def _text(v) -> str:
    """高德在无数据时返回空数组而非空字符串，统一成字符串。"""
    return v.strip() if isinstance(v, str) else ""


def _amap_get(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode({**params, "output": "JSON"})
    req = urllib.request.Request(
        url + "?" + query,
        headers={"User-Agent": "huaxi-travel/1.0"},
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if str(data.get("status")) != "1":
        info = data.get("info") or "高德服务返回失败"
        code = data.get("infocode") or ""
        raise RuntimeError(f"{info}{(' (' + str(code) + ')') if code else ''}")
    return data


def _location_payload(**kwargs) -> dict:
    base = dict(
        configured=True,
        lng=106.6700,
        lat=26.4200,
        accuracy="none",
        adcode=default_adcode(),
        province="贵州",
        city="贵阳市",
        district="花溪区",
        formatted="贵州省贵阳市花溪区（默认位置）",
    )
    base.update(kwargs)
    return base


def _unconfigured() -> dict:
    return dict(
        configured=False,
        message="尚未配置高德 Web 服务 key：请在 travel-api/.env 填写 AMAP_KEY 并重启后端"
                "（仅影响地名解析，不影响天气查询与地图底图）",
    )


def resolve_by_coords(lng: float, lat: float) -> dict:
    """逆地理编码：GCJ-02 经纬度 → 所在区县 adcode / 地名（结果按 4 位小数网格缓存）。"""
    if not key_configured():
        return _unconfigured()
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return dict(configured=False, message="坐标超出有效范围")

    cache_key = f"regeo:{lng:.4f},{lat:.4f}"
    hit = location_cache.get(cache_key)
    if hit:
        return hit

    try:
        data = _amap_get(REGEO_URL, {
            "key": settings.amap_key.strip(),
            "location": f"{lng:.6f},{lat:.6f}",
            "extensions": "base",
            "radius": "1000",
        })
    except Exception as exc:
        # 错误不进缓存，恢复后可立即重试
        return dict(configured=False, message=f"位置解析失败：{exc}")

    geo = data.get("regeocode") or {}
    if not isinstance(geo, dict):
        geo = {}
    ac = geo.get("addressComponent") or {}
    if not isinstance(ac, dict):
        ac = {}
    adcode = _text(ac.get("adcode")) or default_adcode()
    province = _text(ac.get("province"))
    city = _text(ac.get("city")) or province
    district = _text(ac.get("district"))
    formatted = _text(geo.get("formatted_address")) or "".join(
        p for p in (province, city, district) if p
    )
    out = _location_payload(
        source="browser",
        lng=round(lng, 6),
        lat=round(lat, 6),
        accuracy="precise",
        adcode=adcode,
        province=province,
        city=city,
        district=district,
        formatted=formatted or "我的位置",
    )
    location_cache.set(cache_key, out)
    return out


def resolve_by_ip(ip: str | None = None) -> dict:
    """IP 定位（城市级兜底）：局域网/私有 IP 不传给高德，让其按出口 IP 判断。"""
    if not key_configured():
        return _unconfigured()
    hit = ip_cache.get("ip")
    if hit:
        return hit

    params = {"key": settings.amap_key.strip()}
    if ip and not PRIVATE_IP_RE.match(ip):
        params["ip"] = ip
    try:
        data = _amap_get(IP_URL, params)
    except Exception as exc:
        return dict(configured=False, message=f"IP 定位失败：{exc}")

    province = _text(data.get("province"))
    city = _text(data.get("city")) or province
    adcode = _text(data.get("adcode")) or default_adcode()
    if not ADCODE_RE.fullmatch(adcode):
        adcode = default_adcode()

    # rectangle 形如 "lng1,lat1;lng2,lat2"，取矩形中心作为城市级坐标
    lng, lat = 106.6700, 26.4200
    rect = _text(data.get("rectangle"))
    try:
        p1, p2 = rect.split(";")
        x1, y1 = (float(v) for v in p1.split(","))
        x2, y2 = (float(v) for v in p2.split(","))
        lng, lat = round((x1 + x2) / 2, 6), round((y1 + y2) / 2, 6)
    except (ValueError, TypeError):
        pass

    if province in ("局域网", "") and city == "":
        return dict(configured=False, message="IP 定位仅支持国内公网 IPv4，已回退到默认位置")

    out = _location_payload(
        source="ip",
        lng=lng,
        lat=lat,
        accuracy="city",
        adcode=adcode,
        province=province,
        city=city,
        district="",
        formatted=f"{province}{city}（IP 城市级定位）",
    )
    ip_cache.set("ip", out)
    return out
