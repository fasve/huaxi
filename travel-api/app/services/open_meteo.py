"""Open-Meteo 天气服务（免密钥公开 API）：实时实况 + 未来 15 天逐日预报。

为什么用它：高德天气 API 只提供「今天 + 未来 3 天」共 4 天，且需要单独申请 Web 服务 key；
Open-Meteo 一次请求即可同时返回当前实况与 16 天逐日数据，无需注册与密钥，因此作为本项目
**唯一的天气数据源**（高德仅保留逆地理编码 / IP 定位与前端地图底图，不再提供天气）。

设计要点：
- 服务端代理，前端拿不到任何外部地址细节；按坐标网格缓存 30 分钟，控制调用量；
- WMO 天气代码统一翻译成中文文案 + 图标类型，前后端口径一致；
- 逐时数据聚合出白天 / 夜间两段天气，日夜图标不同；
- 风速（km/h）换算蒲福风级、风向（度）换算中文方位，字段口径与原高德返回保持一致，
  前端展示逻辑无需改动；
- 坐标系：Open-Meteo 使用 **WGS-84**，调用方必须传 WGS-84 坐标（传 GCJ-02 会偏移约 500 米）；
- 网络失败 / 返回异常时抛出，由路由层降级为结构化提示，绝不编造数据。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime

from app.services.cache import forecast_cache, weather_cache

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather code → (中文文案, 图标类型)
WMO_MAP: dict[int, tuple[str, str]] = {
    0: ("晴", "sun"),
    1: ("大部晴朗", "sun"),
    2: ("局部多云", "partly"),
    3: ("阴", "overcast"),
    45: ("雾", "fog"),
    48: ("霜雾", "fog"),
    51: ("毛毛雨", "rain"),
    53: ("毛毛雨", "rain"),
    55: ("浓毛毛雨", "rain"),
    56: ("冻毛毛雨", "rain"),
    57: ("浓冻毛毛雨", "rain"),
    61: ("小雨", "rain"),
    63: ("中雨", "rain"),
    65: ("大雨", "heavyrain"),
    66: ("冻雨", "rain"),
    67: ("强冻雨", "rain"),
    71: ("小雪", "snow"),
    73: ("中雪", "snow"),
    75: ("大雪", "snow"),
    77: ("米雪", "snow"),
    80: ("阵雨", "rain"),
    81: ("强阵雨", "rain"),
    82: ("暴雨", "heavyrain"),
    85: ("阵雪", "snow"),
    86: ("强阵雪", "snow"),
    95: ("雷阵雨", "thunder"),
    96: ("雷阵雨伴冰雹", "thunder"),
    99: ("强雷暴伴冰雹", "thunder"),
}

WEEK_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 16 方位中文（不含「风」字，前端会拼接）
DIRECTIONS_CN = [
    "北", "东北", "东", "东南", "南", "西南", "西", "西北",
]

# 蒲福风级上限（km/h），用于把风速换算成「级」
BEAUFORT_LIMITS = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]


def _describe(code: int) -> tuple[str, str]:
    return WMO_MAP.get(int(code), ("多云", "partly"))


def _wind_direction_cn(degree: float | None) -> str:
    """角度 → 中文方位（气象风向：0° 为北风来向）。"""
    if degree is None:
        return ""
    try:
        d = float(degree) % 360
    except (TypeError, ValueError):
        return ""
    idx = int((d + 22.5) // 45) % 8
    return DIRECTIONS_CN[idx]


def _beaufort(kmh: float | None) -> int:
    """风速（km/h）→ 蒲福风级（0~12）。"""
    if kmh is None:
        return 0
    try:
        v = float(kmh)
    except (TypeError, ValueError):
        return 0
    if v < 0:
        v = 0.0
    level = 0
    for limit in BEAUFORT_LIMITS:
        if v >= limit:
            level += 1
        else:
            break
    return level


def _fetch(lat: float, lng: float, days: int) -> dict:
    """一次请求取回：当前实况 + 逐日预报 + 逐时天气代码。"""
    params = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}",
        "longitude": f"{lng:.4f}",
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
            "precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m"
        ),
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "hourly": "weather_code",
        "timezone": "Asia/Shanghai",
        "forecast_days": days,
    })
    req = urllib.request.Request(
        FORECAST_URL + "?" + params,
        headers={"User-Agent": "huaxi-travel/1.0"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _aggregate_day_night(hourly: dict, day: str) -> tuple[str, str]:
    """把逐时天气代码聚合成白天 / 夜间两段主导天气（12~18 视为白天）。"""
    times = hourly.get("time") or []
    codes = hourly.get("weather_code") or []
    day_codes: list[int] = []
    night_codes: list[int] = []
    for t, c in zip(times, codes):
        if not isinstance(t, str) or not t.startswith(day):
            continue
        hour = int(t[11:13]) if len(t) >= 13 else 0
        (day_codes if 6 <= hour < 19 else night_codes).append(int(c))
    if not day_codes and not night_codes:
        return "", ""
    if not day_codes:
        day_codes = night_codes
    if not night_codes:
        night_codes = day_codes
    return _describe(max(set(day_codes), key=day_codes.count))[0], \
           _describe(max(set(night_codes), key=night_codes.count))[0]


def _build_live(current: dict) -> dict:
    """把 Open-Meteo 的 current 字段整理成前端统一的实况结构。"""
    text, _icon = _describe(current.get("weather_code") or 0)
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    wind_kmh = current.get("wind_speed_10m")
    is_day = current.get("is_day")
    return dict(
        weather=text,
        temperature="" if temp is None else str(round(float(temp))),
        feels_like="" if feels is None else str(round(float(feels))),
        humidity="" if humidity is None else str(int(humidity)),
        winddirection=_wind_direction_cn(current.get("wind_direction_10m")),
        windpower=str(_beaufort(wind_kmh)),
        wind_speed="" if wind_kmh is None else str(round(float(wind_kmh), 1)),
        precipitation="" if current.get("precipitation") is None else str(current.get("precipitation")),
        cloud_cover="" if current.get("cloud_cover") is None else str(int(current.get("cloud_cover"))),
        is_day=bool(is_day) if is_day is not None else True,
    )


def _build_items(daily: dict, hourly: dict, days: int) -> list[dict]:
    times = daily.get("time") or []
    codes = daily.get("weather_code") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    pop = daily.get("precipitation_probability_max") or []

    items: list[dict] = []
    for i, day in enumerate(times[:days]):
        try:
            code = int(codes[i])
        except (IndexError, TypeError, ValueError):
            continue
        text, icon = _describe(code)
        day_text, night_text = _aggregate_day_night(hourly, day)
        if not day_text:
            day_text, night_text = text, text
        try:
            week = WEEK_CN[datetime.strptime(day, "%Y-%m-%d").weekday()]
        except ValueError:
            week = ""
        hi = tmax[i] if i < len(tmax) else None
        lo = tmin[i] if i < len(tmin) else None
        items.append(dict(
            date=day,
            week=week,
            dayweather=day_text,
            nightweather=night_text,
            icon=icon,
            daytemp="" if hi is None else str(round(float(hi))),
            nighttemp="" if lo is None else str(round(float(lo))),
            precip=int(pop[i]) if i < len(pop) and pop[i] is not None else None,
        ))
    return items


def get_forecast(lat: float = 26.42, lng: float = 106.67, days: int = 15) -> dict:
    """未来 15 天逐日预报（失败时抛异常，由调用方降级）。"""
    days = max(1, min(days, 16))
    cache_key = f"om15:{lat:.2f},{lng:.2f}:{days}"
    hit = forecast_cache.get(cache_key)
    if hit:
        return hit

    data = _fetch(lat, lng, days)
    items = _build_items(data.get("daily") or {}, data.get("hourly") or {}, days)
    if not items:
        raise RuntimeError("预报数据为空")

    out = dict(
        source="Open-Meteo · 免密钥公开天气 API",
        days=len(items),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        elevation=data.get("elevation"),
        items=items,
    )
    forecast_cache.set(cache_key, out)
    return out


def get_weather(lat: float = 26.42, lng: float = 106.67, days: int = 15) -> dict:
    """实时实况 + 未来 15 天预报（一次请求，服务端 30 分钟缓存）。

    坐标口径：WGS-84（Open-Meteo 使用该坐标系）。
    """
    days = max(1, min(days, 16))
    cache_key = f"omwx:{lat:.2f},{lng:.2f}:{days}"
    hit = weather_cache.get(cache_key)
    if hit:
        return hit

    data = _fetch(lat, lng, days)
    current = data.get("current") or {}
    items = _build_items(data.get("daily") or {}, data.get("hourly") or {}, days)
    if not items:
        raise RuntimeError("天气数据为空")

    out = dict(
        configured=True,
        source="Open-Meteo · 免密钥公开天气 API",
        provider="open-meteo",
        reporttime=str(current.get("time") or ""),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        elevation=data.get("elevation"),
        live=_build_live(current) if current else None,
        casts=items,
        forecast_days=len(items),
    )
    weather_cache.set(cache_key, out)
    return out
