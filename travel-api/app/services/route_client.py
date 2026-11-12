"""#9 / 方案 8.1 路线分段：计算行程相邻站点间的距离与耗时。

- 开启 `FEATURE_ROUTE_API` 且配置腾讯位置服务 key 时，调用腾讯 WebService 路径规划；
- 否则（或调用失败）退化为球面直线距离 × 绕行系数 + 分模式速度估算，保证接口始终可用；
- 结果按坐标网格做进程内缓存，避免同一段路反复外呼。
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Poi, Trip
from app.services.cache import TTLCache

route_cache = TTLCache(ttl_seconds=3600, max_items=512)

# 出行方式 → 兜底速度（km/h）
SPEED_KMH = {
    "self_drive": 35.0, "taxi": 30.0, "transit": 20.0, "walk_bike": 8.0,
}
DETOUR_FACTOR = 1.35   # 直线距离 → 实际路程的经验绕行系数


def haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _fallback(lng1: float, lat1: float, lng2: float, lat2: float, transport: str) -> dict:
    straight = haversine_m(lng1, lat1, lng2, lat2)
    distance = straight * DETOUR_FACTOR
    speed = SPEED_KMH.get(transport, 25.0)
    duration = distance / 1000.0 / speed * 60.0
    return dict(
        distance_m=int(round(distance)),
        duration_min=max(1, int(round(duration))),
        source="estimate", mode=transport,
    )


def _tencent_direction(
    lng1: float, lat1: float, lng2: float, lat2: float, transport: str,
) -> dict:
    path = "walking" if transport == "walk_bike" else "driving"
    url = f"{settings.TENCENT_LBS_BASE.rstrip('/')}/ws/direction/v1/{path}/"
    params = {
        "from": f"{lat1:.6f},{lng1:.6f}",
        "to": f"{lat2:.6f},{lng2:.6f}",
        "key": settings.TENCENT_LBS_KEY.strip(),
        "output": "json",
    }
    req = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "huaxi-travel/1.0"},
    )
    with urllib.request.urlopen(req, timeout=settings.TENCENT_LBS_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if int(data.get("status", -1)) != 0:
        raise RuntimeError(data.get("message") or f"腾讯位置服务返回 status={data.get('status')}")
    routes = (data.get("result") or {}).get("routes") or []
    if not routes:
        raise RuntimeError("腾讯位置服务无可用路线")
    route = routes[0]
    # 腾讯 direction：distance 单位米，duration 单位分钟
    return dict(
        distance_m=int(route.get("distance") or 0),
        duration_min=max(1, int(route.get("duration") or 0)),
        source="tencent", mode=transport,
    )


def segment(
    lng1: float, lat1: float, lng2: float, lat2: float, transport: str = "taxi",
) -> dict:
    """单段路：优先真实路径规划，失败自动降级为估算。"""
    key = f"{transport}:{lng1:.4f},{lat1:.4f}->{lng2:.4f},{lat2:.4f}"
    hit = route_cache.get(key)
    if hit is not None:
        return hit
    result: dict
    if settings.FEATURE_ROUTE_API and settings.route_api_configured:
        try:
            result = _tencent_direction(lng1, lat1, lng2, lat2, transport)
        except Exception as exc:  # noqa: BLE001
            result = _fallback(lng1, lat1, lng2, lat2, transport)
            result["fallback_reason"] = str(exc)[:120]
    else:
        result = _fallback(lng1, lat1, lng2, lat2, transport)
    route_cache.set(key, result)
    return result


def _transport_of(trip: Trip) -> str:
    stored = dict(trip.pace_config or {})
    transport = (stored.get("cost_prefs") or {}).get("transport")
    return transport if transport in SPEED_KMH else "taxi"


def trip_segments(db: Session, trip: Trip) -> dict:
    """整程分段：按天输出相邻站点（含酒店 → 首站）的距离与耗时。"""
    transport = _transport_of(trip)
    used_api = bool(settings.FEATURE_ROUTE_API and settings.route_api_configured)
    # 一次性取 POI，避免逐条查库
    poi_ids = {
        it.poi_id for d in trip.days_plan for it in d.items if it.poi_id
    }
    hotel_id = trip.days_plan[0].hotel_id if trip.days_plan else None
    if hotel_id:
        poi_ids.add(hotel_id)
    poi_map = {p.id: p for p in db.query(Poi).filter(Poi.id.in_(poi_ids)).all()} if poi_ids else {}

    days_out = []
    total_distance = 0
    total_duration = 0
    for day in sorted(trip.days_plan, key=lambda x: x.day_index):
        items = sorted(day.items, key=lambda x: x.order_index)
        chain: list[tuple[int | None, str, float, float]] = []
        if hotel_id and hotel_id in poi_map:
            h = poi_map[hotel_id]
            chain.append((h.id, h.name, h.longitude, h.latitude))
        for it in items:
            p = poi_map.get(it.poi_id)
            if p is None:
                continue
            chain.append((p.id, p.name, p.longitude, p.latitude))

        segments = []
        for i in range(1, len(chain)):
            prev, cur = chain[i - 1], chain[i]
            seg = segment(prev[2], prev[3], cur[2], cur[3], transport)
            total_distance += seg["distance_m"]
            total_duration += seg["duration_min"]
            segments.append(dict(
                from_poi_id=prev[0], from_name=prev[1],
                to_poi_id=cur[0], to_name=cur[1],
                distance_m=seg["distance_m"], duration_min=seg["duration_min"],
                mode=seg["mode"], source=seg["source"],
                fallback_reason=seg.get("fallback_reason", ""),
            ))
        days_out.append(dict(
            day_index=day.day_index,
            segments=segments,
            distance_m=sum(s["distance_m"] for s in segments),
            duration_min=sum(s["duration_min"] for s in segments),
        ))

    return dict(
        trip_id=trip.id, transport=transport,
        provider="tencent" if used_api else "estimate",
        total_distance_m=total_distance,
        total_duration_min=total_duration,
        days=days_out,
    )
