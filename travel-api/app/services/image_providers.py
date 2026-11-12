"""图片源 Provider 抽象层：多源合规链路。

原实现只依赖 Bing 图片搜索结果页。核查目标站 robots.txt 后确认
`/images/search?` 属于被 Disallow 的机器抓取路径，因此这里把数据源
重构为**可插拔 Provider 链**，按合规性从高到低自动降级：

| 优先级 | Provider        | 授权            | 需要 key | 说明 |
|--------|-----------------|-----------------|----------|------|
| 1      | Wikimedia       | CC BY-SA 等     | 否       | 维基共享资源，正规 API |
| 2      | Openverse       | CC / PDM        | 否       | 开放许可图片聚合 API |
| 3      | Pixabay         | Pixabay License | 是       | 官方 API，商用友好 |
| 4      | Pexels          | Pexels License  | 是       | 官方 API，商用友好 |
| 5      | 站内素材库       | 自有/已授权     | 否       | 本地已落盘的既有图片 |
| 6      | Web 搜索兜底     | 未知            | 否       | **默认关闭**，需显式开启 |

每个 Provider 返回统一的 `ImageAsset`，其中 `source` / `author` / `license`
会被写入 `poi.image_meta`，保证每一张对外展示的图都能追溯到来源与授权。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import quote

import requests

from app.services.robots import RobotsGate, polite_user_agent
from app.services.provider_keys import get_key

# 诚实 UA：标识 bot 与联系方式，不伪装浏览器
_USER_AGENT = polite_user_agent(os.getenv("IMAGE_BOT_CONTACT", ""))

# 可用性探测超时：只判断"通不通"，不值得等太久
# （管理端「图片来源」列表会同步调用每个源的探测）
_PROBE_TIMEOUT = 4.0

# 全局 robots 闸门：所有 Provider 共用
ROBOTS = RobotsGate(_USER_AGENT)


@dataclass
class ImageAsset:
    """一张图片的元信息（下载前的抽象）。"""
    url: str                    # 远程直链
    source: str                 # 来源标识：wikimedia / openverse / pixabay / pexels / web
    source_name: str            # 来源中文名，用于展示
    author: str = ""            # 作者 / 拍摄者
    license: str = ""           # 授权名称
    license_url: str = ""       # 授权协议链接
    title: str = ""
    width: int = 0
    height: int = 0
    # True 表示该图的使用权已由图库自身的授权协议（CC / Pixabay / Pexels License）
    # 覆盖，下载图片直链不再受 CDN robots.txt 二次否决；
    # False 表示来源不明（如 Web 搜索兜底），必须严格遵守 robots.txt。
    license_covered: bool = True
    extra: dict = field(default_factory=dict)


class ImageProvider:
    """图片源基类。子类实现 `search`。"""

    name = "base"
    display_name = "基础图片源"
    license_type = "unknown"
    requires_key = False

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": _USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def available(self) -> tuple[bool, str]:
        """该源当前是否可用：(可用?, 说明)。"""
        return True, "可用"

    def search(self, query: str, limit: int = 10) -> list[ImageAsset]:
        raise NotImplementedError


# --------------------------------------------------------------------------
# 1. Wikimedia Commons —— 维基共享资源官方 API
# --------------------------------------------------------------------------
class WikimediaProvider(ImageProvider):
    """维基共享资源（Commons）官方 API，无需 key，图片多为 CC 授权。"""

    name = "wikimedia"
    display_name = "维基共享资源 (Commons)"
    license_type = "CC / 公有领域"
    API = "https://commons.wikimedia.org/w/api.php"

    def available(self) -> tuple[bool, str]:
        try:
            r = self._session.get(self.API, timeout=_PROBE_TIMEOUT, params={
                "action": "query", "format": "json", "list": "search",
                "srsearch": "test", "srlimit": 1,
            })
            if r.status_code == 200:
                return True, "可用"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, f"网络不可达（{type(e).__name__}）"

    def search(self, query: str, limit: int = 10) -> list[ImageAsset]:
        r = self._session.get(self.API, timeout=self.timeout, params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6,
            "gsrlimit": limit, "prop": "imageinfo",
            "iiprop": "url|size|extmetadata", "iiurlwidth": 1200,
        })
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
        out: list[ImageAsset] = []
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            meta = info.get("extmetadata") or {}
            out.append(ImageAsset(
                url=url, source=self.name, source_name=self.display_name,
                author=_clean(meta.get("Artist", {}).get("value", "")),
                license=_clean(meta.get("LicenseShortName", {}).get("value", "")),
                license_url=meta.get("LicenseUrl", {}).get("value", ""),
                title=page.get("title", ""),
                width=info.get("thumbwidth") or info.get("width") or 0,
                height=info.get("thumbheight") or info.get("height") or 0,
                license_covered=True,
            ))
        return out


# --------------------------------------------------------------------------
# 2. Openverse —— 开放许可图片聚合 API（聚合 CC / 公有领域）
# --------------------------------------------------------------------------
class OpenverseProvider(ImageProvider):
    """Openverse 开放许可图片 API，无需 key。"""

    name = "openverse"
    display_name = "Openverse 开放许可图库"
    license_type = "CC / 公有领域"
    API = "https://api.openverse.org/v1/images/"

    def available(self) -> tuple[bool, str]:
        try:
            r = self._session.get(self.API, timeout=_PROBE_TIMEOUT, params={"q": "landscape", "page_size": 1})
            if r.status_code == 200:
                return True, "可用"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, f"网络不可达（{type(e).__name__}）"

    def search(self, query: str, limit: int = 10) -> list[ImageAsset]:
        r = self._session.get(self.API, timeout=self.timeout, params={
            "q": query, "page_size": limit, "license_type": "all",
            "mature": "false",
        })
        r.raise_for_status()
        out: list[ImageAsset] = []
        for it in r.json().get("results", []):
            out.append(ImageAsset(
                url=it.get("url") or "", source=self.name, source_name=self.display_name,
                author=it.get("creator") or "", license=(it.get("license") or "").upper(),
                license_url=it.get("license_url") or "",
                title=it.get("title") or "",
                width=it.get("width") or 0, height=it.get("height") or 0,
                license_covered=True,
            ))
        return out


# --------------------------------------------------------------------------
# 3. Pixabay —— 官方 API，Pixabay License 允许商用
# --------------------------------------------------------------------------
class PixabayProvider(ImageProvider):
    """Pixabay 官方 API，需免费 key。Pixabay License 可商用。"""

    name = "pixabay"
    display_name = "Pixabay（官方 API）"
    license_type = "Pixabay License（可商用）"
    requires_key = True
    API = "https://pixabay.com/api/"

    def __init__(self, api_key: str, timeout: float = 20.0):
        super().__init__(timeout)
        self.api_key = api_key.strip()

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置 PIXABAY_API_KEY（可在系统设置 → 图片源中填写）"
        return True, "可用"

    def search(self, query: str, limit: int = 10) -> list[ImageAsset]:
        r = self._session.get(self.API, timeout=self.timeout, params={
            "key": self.api_key, "q": query, "image_type": "photo",
            "safesearch": "true", "per_page": max(1, min(limit, 20)),
            "min_width": 640, "min_height": 480,
        })
        r.raise_for_status()
        out: list[ImageAsset] = []
        for it in r.json().get("hits", []):
            out.append(ImageAsset(
                url=it.get("largeImageURL") or it.get("webformatURL") or "",
                source=self.name, source_name=self.display_name,
                author=it.get("user") or "", license="Pixabay License",
                license_url="https://pixabay.com/service/license-summary/",
                title=it.get("tags") or "", width=it.get("imageWidth") or 0,
                height=it.get("imageHeight") or 0,
                license_covered=True,
            ))
        return out


# --------------------------------------------------------------------------
# 4. Pexels —— 官方 API，Pexels License 允许商用
# --------------------------------------------------------------------------
class PexelsProvider(ImageProvider):
    """Pexels 官方 API，需免费 key。Pexels License 可商用。"""

    name = "pexels"
    display_name = "Pexels（官方 API）"
    license_type = "Pexels License（可商用）"
    requires_key = True
    API = "https://api.pexels.com/v1/search"

    def __init__(self, api_key: str, timeout: float = 20.0):
        super().__init__(timeout)
        self.api_key = api_key.strip()

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置 PEXELS_API_KEY（可在系统设置 → 图片源中填写）"
        return True, "可用"

    def search(self, query: str, limit: int = 10) -> list[ImageAsset]:
        r = self._session.get(self.API, timeout=self.timeout,
                              headers={"Authorization": self.api_key},
                              params={"query": query, "per_page": max(1, min(limit, 20))})
        r.raise_for_status()
        out: list[ImageAsset] = []
        for it in r.json().get("photos", []):
            src = it.get("src") or {}
            out.append(ImageAsset(
                url=src.get("large2x") or src.get("large") or src.get("medium") or "",
                source=self.name, source_name=self.display_name,
                author=it.get("photographer") or "", license="Pexels License",
                license_url="https://www.pexels.com/license/",
                title=it.get("alt") or "", width=it.get("width") or 0,
                height=it.get("height") or 0,
                license_covered=True,
            ))
        return out


# --------------------------------------------------------------------------
# 5. Web 搜索兜底 —— 默认关闭
# --------------------------------------------------------------------------
class WebSearchProvider(ImageProvider):
    """通用 Web 图片搜索兜底源。

    ⚠️ 搜索引擎结果页的 robots.txt 通常明确 Disallow 该路径
    （已实测 Bing 的 `/images/search?` 被禁止），因此本 Provider
    **默认不启用**；仅当管理员显式配置 `IMAGE_ALLOW_WEB_SEARCH=true`
    时才会启用，且启用前会先做 robots 判定。

    保留它的意义：部分站点允许抓取、或用于在内网/离线演示环境兜底。
    """

    name = "web"
    display_name = "Web 图片搜索（兜底，需显式开启）"
    license_type = "未知（需自行确认授权）"

    def __init__(self, timeout: float = 20.0):
        super().__init__(timeout)
        self._murl_re = None

    def available(self) -> tuple[bool, str]:
        if os.getenv("IMAGE_ALLOW_WEB_SEARCH", "").lower() not in ("1", "true", "yes"):
            return False, "默认关闭（目标站 robots.txt 禁止抓取搜索结果页）"
        return True, "已显式开启"

    def search(self, query: str, limit: int = 10) -> list[ImageAsset]:
        """返回候选直链。

        ⚠️ 即使管理员显式开启，本方法仍会**先做 robots 判定**：
        目标站若明确 Disallow 搜索结果页，则不发起请求，直接返回空。
        这保证「显式开启」只是解除默认关闭，而不能绕过 robots 协议。

        注意：robots 判定必须基于**带 query 的实际请求 URL**。
        例如 Bing 的规则是 `Disallow: /images/search?`，不带 query 的
        `/images/search` 不匹配该规则，但真实请求一定带 `?q=...`，
        若用无 query 的 URL 去判定就会误判为「允许」。
        """
        import re

        endpoint = "https://cn.bing.com/images/search"
        actual_url = f"{endpoint}?q={quote(query)}"
        if not ROBOTS.allowed(actual_url, strict=True):
            return []

        if self._murl_re is None:
            self._murl_re = re.compile(r'murl&quot;:&quot;(.*?)&quot;')
        r = self._session.get(endpoint, timeout=self.timeout,
                              params={"q": query, "form": "HDRSC2", "first": 1})
        r.raise_for_status()
        out: list[ImageAsset] = []
        for raw in self._murl_re.findall(r.text):
            url = raw.replace("\\/", "/").replace("&amp;", "&")
            if url.lower().startswith(("http://", "https://")):
                out.append(ImageAsset(url=url, source=self.name,
                                      source_name=self.display_name,
                                      license_covered=False))
            if len(out) >= limit * 3:
                break
        return out


def _clean(html_text: str) -> str:
    """把 extmetadata 里的 HTML 片段压成纯文本。"""
    if not html_text:
        return ""
    import re
    text = re.sub(r"<[^>]+>", "", html_text)
    return re.sub(r"\s+", " ", text).strip()


def build_providers() -> list[ImageProvider]:
    """按合规优先级构建 Provider 链。"""
    return [
        WikimediaProvider(),
        OpenverseProvider(),
        PixabayProvider(get_key("pixabay")),
        PexelsProvider(get_key("pexels")),
        WebSearchProvider(),
    ]
