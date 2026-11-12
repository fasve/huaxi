"""天气接口（游客端公开）：数据源为 Open-Meteo 免密钥公开 API。

- GET /weather?lng=&lat=&days=：按用户实时所在坐标返回**实况 + 未来 15 天逐日预报**（一次请求）；
- GET /weather/forecast?lng=&lat=&days=：只取逐日预报（兼容旧的独立调用）。

坐标系：Open-Meteo 使用 **WGS-84**，前端传入的必须是 WGS-84 坐标
（浏览器原生定位本身就是 WGS-84；地图底图用的 GCJ-02 仅用于高德渲染）。

服务端代理 + 30 分钟缓存，前端拿不到任何外部地址细节；网络失败时返回结构化降级提示，
不返回虚构数据。高德在本项目中只负责地名解析与底图，不再提供天气。
"""
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.services.amap_service import resolve_by_coords, resolve_by_ip
from app.services.open_meteo import get_forecast, get_weather

router = APIRouter(prefix="/api/v1", tags=["weather"])

# 花溪区中心（WGS-84）：定位不可用时的默认坐标
DEFAULT_LNG = 106.6619
DEFAULT_LAT = 26.4138


class LocationResolveIn(BaseModel):
    # GCJ-02 坐标系（与高德底图一致）；小数点后 6 位足够，超出范围直接判为无效
    lng: float | None = Field(None, ge=-180, le=180)
    lat: float | None = Field(None, ge=-90, le=90)


def _client_ip(request: Request) -> str | None:
    """优先取反向代理透传的公网 IP；本地 127.0.0.1 / 局域网地址由服务端过滤掉。"""
    forwarded = request.headers.get("x-forwarded-for") or ""
    candidates = [s.strip() for s in forwarded.split(",") if s.strip()]
    if request.client and request.client.host:
        candidates.append(request.client.host)
    return candidates[0] if candidates else None


@router.post("/location/resolve")
def location_resolve(payload: LocationResolveIn, request: Request):
    """实时位置解析：有坐标走逆地理，无坐标走 IP 定位（城市级兜底）。高德服务。"""
    if payload.lng is not None and payload.lat is not None:
        return resolve_by_coords(payload.lng, payload.lat)
    return resolve_by_ip(_client_ip(request))


@router.get("/weather")
def weather(
    lng: float | None = Query(None, ge=-180, le=180),
    lat: float | None = Query(None, ge=-90, le=90),
    days: int = Query(15, ge=1, le=16),
):
    """按坐标返回实时实况 + 未来 15 天逐日预报（Open-Meteo，服务端 30 分钟缓存）。

    不传坐标时使用花溪区中心。注意参数为 WGS-84 坐标。
    """
    use_lng = DEFAULT_LNG if lng is None else lng
    use_lat = DEFAULT_LAT if lat is None else lat
    try:
        return get_weather(use_lat, use_lng, days)
    except Exception as exc:
        return dict(
            configured=True,
            available=False,
            error=f"天气服务暂不可用：{exc}",
            message="Open-Meteo 天气服务暂时无法访问，请稍后重试",
        )


@router.get("/weather/forecast")
def weather_forecast(
    lng: float | None = Query(None, ge=-180, le=180),
    lat: float | None = Query(None, ge=-90, le=90),
    days: int = Query(15, ge=1, le=16),
):
    """未来 15 天逐日预报（仅预报部分）。失败时返回 available=false。"""
    use_lng = DEFAULT_LNG if lng is None else lng
    use_lat = DEFAULT_LAT if lat is None else lat
    try:
        data = get_forecast(use_lat, use_lng, days)
    except Exception as exc:
        return dict(available=False, message=f"15 天预报暂不可用：{exc}")
    return dict(available=True, **data)
