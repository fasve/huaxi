"""联网图片抓取服务：为 POI 检索真实景点/商户照片。

数据源策略（**合规优先**，按优先级自动降级）：
1. Wikimedia Commons 官方 API —— CC 授权，无需 key
2. Openverse 开放许可图库 API —— CC / 公有领域，无需 key
3. Pixabay 官方 API —— Pixabay License 可商用，需 key
4. Pexels 官方 API —— Pexels License 可商用，需 key
5. Web 图片搜索兜底 —— **默认关闭**（目标站 robots.txt 禁止抓取搜索结果页），
   仅当 IMAGE_ALLOW_WEB_SEARCH=true 时启用，且启用前仍做 robots 判定

同时遵守 robots 协议：抓取前用 RobotsGate 检查目标 URL 是否被 Disallow；
下载到的图片一律**本地化保存**到 static/poi/，对外只暴露相对路径，
既避免外链失效与跨域，也让每一张图都能追溯来源与授权。

合规说明：优先使用带明确授权协议的官方 API（CC / Pixabay / Pexels License）。
Web 兜底源只用于离线演示，商用上线应配置前述官方源并保留署名与授权记录。
"""
from __future__ import annotations

import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

from app.config import BASE_DIR
from app.services.image_providers import (
    ROBOTS, ImageAsset, ImageProvider, build_providers,
)

# 项目内静态资源根目录：travel-api/static
STATIC_DIR = os.path.join(str(BASE_DIR), "static")
POI_IMG_DIR = os.path.join(STATIC_DIR, "poi")

# 允许的图片域名白名单：优先国内图床 + 主流合规图库（速度快、稳定性好）
_ALLOWED_HOST_HINTS = (
    "699pic.com", "sinaimg.cn", "qunarzz.com", "ctrip.com", "qunar.com",
    "you.ctrip.com", "mafengwo.net", "pic.qianjin.com", "16pic.com",
    "nipic.com", "photophoto.cn", "huitu.com", "tuchong.com", "aliyuncs.com",
    "oss-cn", "baidu.com", "sina.com.cn", "qq.com", "163.com", "zjol.com.cn",
    "huaban.com", "xiaohongshu.com", "douban.com", "mafengwo.cn", "in.ctrip.com",
    # 合规图库 CDN
    "wikimedia.org", "upload.wikimedia.org", "openverse.org", "pixabay.com",
    "cdn.pixabay.com", "pexels.com", "images.pexels.com", "staticflickr.com",
)

# 明显不是实景照片的关键词（logo / 图标 / 文字海报等）
_BAD_KEYWORDS = (
    "logo", "icon", "gif", "qrcode", "二维码", "图标", "标志", "png",
    "vector", "clipart", "地图", "导览图", "示意图", "矢量",
)


@dataclass
class FetchResult:
    ok: bool
    url: str = ""              # 可直接用于前端的地址（/static/poi/xxx.jpg）
    source: str = ""           # 来源标识
    source_name: str = ""      # 来源中文名
    author: str = ""           # 作者 / 拍摄者
    license: str = ""          # 授权名称
    license_url: str = ""      # 授权协议链接
    message: str = ""
    width: int = 0
    height: int = 0

    def to_meta(self) -> dict:
        """写入 poi.image_meta 的授权元信息。"""
        return dict(
            source=self.source, source_name=self.source_name,
            author=self.author, license=self.license,
            license_url=self.license_url,
        )


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": ROBOTS.user_agent,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    return s


def _build_query(name: str, sub_type: str = "", category: str = "") -> str:
    """构造检索词：名称 + 地域 + 类别关键词，提高命中率。

    英文关键词同时带上，便于命中 CC 图库（其元数据以英文为主）。
    """
    region = "贵阳"
    if "花溪" in name or "花溪" in sub_type:
        region = "贵阳花溪"
    kind = {
        "scenic": ("风景", "scenic landscape"),
        "food": ("美食", "food restaurant"),
        "hotel": ("酒店", "hotel room"),
        "leisure": ("休闲", "park leisure"),
    }.get(category, ("", ""))
    parts = [name, region]
    if kind:
        parts.extend(k for k in kind if k)
    return " ".join(p for p in parts if p)


def _download(url: str, session: requests.Session | None = None) -> tuple[bytes, str] | None:
    """下载图片，返回 (数据, 扩展名)。"""
    try:
        s = session or _session()
        resp = s.get(url, timeout=20, stream=True)
        resp.raise_for_status()
        ctype = resp.headers.get("Content-Type", "")
        if "image" not in ctype.lower():
            return None
        data = resp.content
        if len(data) < 8_000:      # 太小的一般是占位图/缩略图
            return None
        ext = ".jpg"
        if "png" in ctype.lower():
            ext = ".png"
        elif "webp" in ctype.lower():
            ext = ".webp"
        elif "gif" in ctype.lower():
            return None
        return data, ext
    except Exception:
        return None


def _is_valid_image(data: bytes) -> tuple[bool, int, int]:
    """校验图片可解码且尺寸达标（宽 >= 480，高 >= 320）。"""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if w < 480 or h < 320:
                return False, w, h
            return True, w, h
    except Exception:
        return False, 0, 0


def _fallback_svg(name: str, sub_type: str) -> bytes:
    """生成离线占位图（渐变底 + 名称），保证永远有图可显示。"""
    safe = (name or "景点").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    sub = (sub_type or "花溪").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    hue = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:4], 16) % 360
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="hsl({hue},58%,62%)"/>
<stop offset="100%" stop-color="hsl({(hue+48)%360},52%,38%)"/>
</linearGradient></defs>
<rect width="800" height="600" fill="url(#g)"/>
<g fill="rgba(255,255,255,.22)">
<circle cx="130" cy="140" r="90"/><circle cx="660" cy="470" r="130"/>
<circle cx="430" cy="90" r="60"/></g>
<text x="400" y="290" text-anchor="middle" font-family="Microsoft YaHei, sans-serif"
 font-size="46" font-weight="bold" fill="rgba(255,255,255,.95)">{safe}</text>
<text x="400" y="344" text-anchor="middle" font-family="Microsoft YaHei, sans-serif"
 font-size="26" fill="rgba(255,255,255,.8)">{sub} · 花溪区</text>
<text x="400" y="392" text-anchor="middle" font-family="Microsoft YaHei, sans-serif"
 font-size="18" fill="rgba(255,255,255,.62)">图片待补充</text>
</svg>"""
    return svg.encode("utf-8")


def save_local(data: bytes, ext: str, key: str) -> str:
    """把图片数据写入 static/poi，返回可访问的相对 URL。"""
    os.makedirs(POI_IMG_DIR, exist_ok=True)
    digest = hashlib.md5((key + str(len(data))).encode("utf-8")).hexdigest()[:12]
    fname = f"{digest}{ext}"
    path = os.path.join(POI_IMG_DIR, fname)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return f"/static/poi/{fname}"


def _host_allowed(url: str) -> bool:
    """域名白名单 + 坏词过滤。"""
    low = url.lower()
    if any(bad in low for bad in _BAD_KEYWORDS):
        return False
    return any(hint in low for hint in _ALLOWED_HOST_HINTS)


def _collect_candidates(
    providers: list[ImageProvider], query: str, max_count: int,
) -> tuple[list[ImageAsset], list[ImageProvider]]:
    """按 Provider 链收集候选素材，返回 (候选列表, 实际产出候选的源)。"""
    candidates: list[ImageAsset] = []
    used: list[ImageProvider] = []
    for p in providers:
        ok, _reason = p.available()
        if not ok:
            continue
        try:
            found = p.search(query, limit=max_count * 3)
        except Exception:
            continue
        if not found:
            continue
        used.append(p)
        for a in found:
            if not a.url.lower().startswith(("http://", "https://")):
                continue
            if not _host_allowed(a.url):
                continue
            candidates.append(a)
        if len(candidates) >= max_count * 2:
            break
    return candidates, used


def fetch_poi_images(
    name: str,
    sub_type: str = "",
    category: str = "",
    key: str | None = None,
    max_count: int = 3,
) -> list[FetchResult]:
    """为单个 POI 抓取多张图片，返回本地化后的 URL 与授权元信息。"""
    query = _build_query(name, sub_type, category)
    providers = build_providers()
    candidates, _used = _collect_candidates(providers, query, max_count)

    out: list[FetchResult] = []
    seen: set = set()
    session = _session()
    for asset in candidates:
        if len(out) >= max_count:
            break
        # robots 协议闸门：
        #   - 授权已由图库协议覆盖（CC / Pixabay / Pexels）→ 直链按宽松档判定，
        #     CDN 的 robots 不可读不再一票否决；
        #   - 来源不明（Web 兜底）→ 严格档，命中 Disallow 一律拒绝。
        strict = not asset.license_covered
        if not ROBOTS.allowed(asset.url, strict=strict):
            continue
        dl = _download(asset.url, session)
        if not dl:
            continue
        data, ext = dl
        ok, w, h = _is_valid_image(data)
        if not ok:
            continue
        if data[:12] in seen:
            continue
        seen.add(data[:12])
        local = save_local(data, ext, key or name)
        out.append(FetchResult(
            ok=True, url=local, source=asset.source,
            source_name=asset.source_name, author=asset.author,
            license=asset.license, license_url=asset.license_url,
            width=w, height=h,
        ))

    if not out:
        svg = _fallback_svg(name, sub_type)
        local = save_local(svg, ".svg", key or name)
        out.append(FetchResult(
            ok=True, url=local, source="placeholder",
            source_name="内置占位图", license="本地生成",
            width=800, height=600,
        ))
    return out


def fetch_single_remote_url(url: str) -> FetchResult:
    """把外部图片直链本地化（用于管理端"从 URL 添加图片"）。

    管理员手动指定的地址，来源不明，按**严格档**遵守 robots.txt。
    """
    if not ROBOTS.allowed(url, strict=True):
        return FetchResult(
            ok=False,
            message=f"目标地址被 robots.txt 禁止抓取：{ROBOTS.explain(url, strict=True)}",
        )
    dl = _download(url)
    if not dl:
        return FetchResult(ok=False, message="图片下载失败或格式不支持")
    data, ext = dl
    ok, w, h = _is_valid_image(data)
    if not ok:
        return FetchResult(ok=False, message="图片尺寸过小或无法解析")
    local = save_local(data, ext, url)
    return FetchResult(ok=True, url=local, source="manual",
                       source_name="管理员上传", width=w, height=h)


def provider_status() -> list[dict]:
    """各图片源的可用性，用于管理端系统设置页展示。

    逐个串行探测在网络受限环境下会累加到十几秒（每个源各等一次超时），
    这里用线程池并发探测，把整体耗时压到「单次超时」量级。
    """
    providers = build_providers()
    out: list[dict] = []

    def probe(p: ImageProvider) -> dict:
        try:
            ok, reason = p.available()
        except Exception as e:
            ok, reason = False, f"探测异常（{type(e).__name__}）"
        return dict(
            name=p.name, display_name=p.display_name,
            license_type=p.license_type, available=ok, reason=reason,
            requires_key=p.requires_key,
        )

    with ThreadPoolExecutor(max_workers=len(providers) or 1) as pool:
        for item in pool.map(probe, providers):
            out.append(item)

    return out
