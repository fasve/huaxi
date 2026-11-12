"""robots.txt 合规闸门 + 诚实 User-Agent。

背景：本项目的图片抓取曾直接请求搜索引擎结果页。核查目标站 robots.txt 后发现，
`/images/search?` 被明确 Disallow，属于不被允许的机器抓取路径。本模块把
robots 协议变成代码里的硬约束：

1. `RobotsGate.allowed(url)` —— 命中目标站 Disallow 规则时直接拒绝，不发请求。
2. 抓取一律使用**诚实 UA**（标识 bot 名称 + 版本 + 联系方式 + 项目地址），
   不再伪装成 Chrome 浏览器。伪装 UA 既违反 robots 精神，也拿不到应有的
   速率豁免。
3. 尊重 robots.txt 里的 `Crawl-delay`，作为请求间隔的下限。

设计取向：**默认拒绝**。取不到 robots.txt 时（超时 / 4xx）按 Google 的
robots 规范处理 —— 4xx 视为完全允许，5xx 与网络错误视为完全禁止。
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass

import requests

# 抓取行为标识：诚实声明这是一个 bot，并给出联系方式与项目地址。
# 站点方如需封禁或协商速率，可直接按此信息联系。
_BOT_NAME = "TravelPortalBot"
_BOT_VERSION = "1.0"
_PROJECT_URL = "http://localhost:8000"


def polite_user_agent(contact: str = "") -> str:
    """生成诚实 UA：TravelPortalBot/1.0 (+项目地址; 联系邮箱)

    不伪装浏览器。搜索引擎据此可以识别并给予合适速率，
    也让站点方有明确的对接入口。
    """
    tail = f"({_PROJECT_URL}"
    if contact:
        tail += f"; contact={contact}"
    tail += ")"
    return f"{_BOT_NAME}/{_BOT_VERSION} {tail}"


@dataclass
class _Cached:
    parser: urllib.robotparser.RobotFileParser | None
    fetched_at: float
    crawl_delay: int


class RobotsGate:
    """按域名缓存 robots.txt 规则，提供 allow / crawl-delay 判定。"""

    def __init__(self, user_agent: str, timeout: float = 10.0, cache_ttl: float = 3600.0):
        self.user_agent = user_agent
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cache: dict[tuple[str, bool], _Cached] = {}

    # ---------- 内部 ----------

    def _fetch_robots(self, url: str, strict: bool = True) -> _Cached:
        parts = urllib.parse.urlsplit(url)
        robots_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        crawl_delay = 0
        try:
            resp = requests.get(robots_url, timeout=self.timeout,
                                headers={"User-Agent": self.user_agent})
            if resp.status_code == 401 or resp.status_code == 403:
                # 明确拒绝读取 → strict 模式视为全站禁止；
                # asset 模式（图片 CDN 直链）按「无 robots 约束」处理
                if strict:
                    parser.disallow_all = True
                else:
                    parser.allow_all = True
            elif resp.status_code >= 400:
                # 4xx（含 404）→ 视为全站允许
                parser.allow_all = True
            else:
                parser.parse(resp.text.splitlines())
                crawl_delay = self._parse_crawl_delay(resp.text)
        except requests.RequestException:
            # 网络故障 / 超时：strict 模式保守禁止；asset 模式放行
            if strict:
                parser.disallow_all = True
            else:
                parser.allow_all = True

        item = _Cached(parser=parser, fetched_at=time.time(), crawl_delay=crawl_delay)
        # 缓存按 (host, strict) 分开：两种档位对「robots 不可读」的处理结论相反，
        # 共用同一份缓存会导致档位串味。
        self._cache[(parts.netloc, strict)] = item
        return item

    @staticmethod
    def _parse_crawl_delay(text: str) -> int:
        """从 robots.txt 中提取 Crawl-delay（秒）。"""
        delay = 0
        in_star = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip()
            if key == "user-agent":
                in_star = (val == "*")
            elif key == "crawl-delay" and in_star:
                try:
                    delay = max(delay, int(float(val)))
                except ValueError:
                    pass
        return delay

    def _entry(self, url: str, strict: bool = True) -> _Cached:
        host = urllib.parse.urlsplit(url).netloc
        key = (host, strict)
        item = self._cache.get(key)
        if item and (time.time() - item.fetched_at) < self.cache_ttl:
            return item
        return self._fetch_robots(url, strict=strict)

    # ---------- 对外 ----------

    def allowed(self, url: str, strict: bool = True) -> bool:
        """该 URL 是否允许本 bot 抓取。

        `strict=True`（默认，用于搜索结果页 / API 端点）：
            命中 Disallow、robots 拒绝读取或读取失败 → 一律禁止。
        `strict=False`（用于图片资源直链）：
            仅当 robots.txt 明确 Disallow 该路径时禁止；
            robots 不可读（CDN 常见 403）时放行 —— 这类图片的使用权
            由图库自身的授权协议（Pixabay / Pexels / CC）覆盖，
            而不是由 CDN 的 robots.txt 决定。
        """
        item = self._entry(url, strict=strict)
        if item.parser is None:
            return False
        try:
            return bool(item.parser.can_fetch(self.user_agent, url))
        except Exception:
            return False

    def crawl_delay(self, url: str) -> int:
        """目标站声明的 Crawl-delay（秒），未声明则为 0。"""
        return self._entry(url).crawl_delay

    def explain(self, url: str, strict: bool = True) -> str:
        """给管理端看的判定说明文本。"""
        item = self._entry(url, strict=strict)
        p = item.parser
        if p is None:
            return "未知"
        if getattr(p, "disallow_all", False):
            return "robots.txt 拒绝读取或读取失败 → 禁止"
        if getattr(p, "allow_all", False):
            return "robots.txt 无有效约束 → 允许"
        return "允许" if self.allowed(url, strict=strict) else "命中 robots.txt Disallow 规则"

    def clear_cache(self) -> None:
        self._cache.clear()
