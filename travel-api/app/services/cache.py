"""缓存层：默认进程内 TTL；配置 REDIS_URL 后自动切换 Redis（接口完全一致）。

设计目标：业务代码只依赖 get / set / invalidate_prefix，不感知后端实现。
Redis 不可用或未安装 redis 包时自动降级为进程内缓存，绝不影响主流程。
"""
import pickle
import time
from threading import Lock

from app.config import settings


class TTLCache:
    def __init__(self, ttl_seconds: int = 300, max_items: int = 512):
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._store: dict[str, tuple[float, object]] = {}
        self._lock = Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._store.get(key)
            if not hit:
                return None
            ts, val = hit
            if time.time() - ts > self.ttl:
                del self._store[key]
                return None
            return val

    def set(self, key: str, val) -> None:
        with self._lock:
            if len(self._store) >= self.max_items:
                # 淘汰最旧一批
                for k in sorted(self._store, key=lambda k: self._store[k][0])[: self.max_items // 4]:
                    del self._store[k]
            self._store[key] = (time.time(), val)

    def invalidate_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
            return len(keys)


class RedisCache:
    """Redis 实现：前缀隔离不同业务，值用 pickle 以兼容 dict / SimpleNamespace 快照。"""

    def __init__(self, prefix: str, ttl_seconds: int = 300):
        import redis  # 延迟导入：未安装 redis 包时不影响进程内缓存

        self.prefix = prefix
        self.ttl = ttl_seconds
        self.client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=False)

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get(self, key: str):
        try:
            raw = self.client.get(self._key(key))
        except Exception:  # noqa: BLE001
            return None
        if raw is None:
            return None
        try:
            return pickle.loads(raw)
        except Exception:  # noqa: BLE001
            return None

    def set(self, key: str, val) -> None:
        try:
            self.client.setex(self._key(key), self.ttl, pickle.dumps(val))
        except Exception:  # noqa: BLE001
            pass

    def invalidate_prefix(self, prefix: str) -> int:
        pattern = f"{self.prefix}{prefix}*"
        count = 0
        try:
            for k in self.client.scan_iter(match=pattern, count=200):
                count += int(self.client.delete(k) or 0)
        except Exception:  # noqa: BLE001
            return 0
        return count


def make_cache(prefix: str, ttl_seconds: int = 300, max_items: int = 512):
    """按配置选择缓存后端；Redis 初始化失败自动回退进程内。"""
    if settings.REDIS_URL.strip():
        try:
            return RedisCache(prefix, ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            print(f"[travel-api] Redis 不可用，回退进程内缓存：{exc}")
    return TTLCache(ttl_seconds=ttl_seconds, max_items=max_items)


poi_cache = make_cache("poi:", ttl_seconds=120)      # 资源列表/详情
mode_cache = make_cache("mode:", ttl_seconds=60)     # 模式配置

# 天气与预报缓存（amap_service / open_meteo 共用，便于管理端统一清空）
weather_cache = make_cache("weather:", ttl_seconds=1800, max_items=64)    # 高德实况与 4 天预报
location_cache = make_cache("loc:", ttl_seconds=1800, max_items=128)      # 逆地理编码结果
ip_cache = make_cache("ip:", ttl_seconds=1800, max_items=8)              # IP 城市级定位
forecast_cache = make_cache("forecast:", ttl_seconds=1800, max_items=64)  # 15 天逐日预报
