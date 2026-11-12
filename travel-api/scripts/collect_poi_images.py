"""按 POI 采集免费商用图库的实拍图，并通过管理端上传接口入库。

设计要点
--------
1. **合规**：只接受免费商用授权（Pexels License / Unsplash License / CC0 / PD / CC BY / CC BY-SA），
   每张图把 `source_name / author / license / license_url` 一并写进 `poi.image_meta`。
2. **只走上传通道**：图片经 `POST /admin/pois/{id}/images/upload` 落盘并入库，
   与手工在管理端上传完全同一条路径（`source=upload`）。
3. **幂等**：已有 N 张 upload 图的 POI 默认跳过；`--force` 可重采。
4. **可暂停**：`--limit` 控制本轮处理多少个 POI，`--only` 指定 id 列表。

用法
----
    # 先看计划，不发请求
    python scripts/collect_poi_images.py --dry-run

    # 需要免费 key（二选一）：Pexels 或 Unsplash
    set PEXELS_API_KEY=xxx            # pexels.com/api
    set UNSPLASH_ACCESS_KEY=xxx       # unsplash.com/developers

    # 正式采集（每个 POI 3 张，先跑 10 个看看效果）
    python scripts/collect_poi_images.py --per-poi 3 --limit 10

    # 先跑小样本人工确认质量，再全量
    python scripts/collect_poi_images.py --per-poi 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api/v1")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
UA = "TravelPortalBot/1.0 (+http://localhost:8000; contact=local)"

# ---------------------------------------------------------------- 授权白名单
# Pexels / Unsplash 的“免费商用”许可；CC 家族只收可商用的
ALLOWED_LICENSES = {
    "pexels license": ("Pexels License", "https://www.pexels.com/license/"),
    "unsplash license": ("Unsplash License", "https://unsplash.com/license"),
    "cc0": ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "public domain": ("Public Domain", ""),
    "cc by 4.0": ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
    "cc by 3.0": ("CC BY 3.0", "https://creativecommons.org/licenses/by/3.0/"),
    "cc by-sa 4.0": ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
    "cc by-sa 3.0": ("CC BY-SA 3.0", "https://creativecommons.org/licenses/by-sa/3.0/"),
}

# 检索词：中文 POI 名称 → 英文/中文关键词（免费图库以英文为主）
# 精确实景很少，因此按「品类」检索；meta.note 会标明实际检索词，便于日后替换
CATEGORY_KEYWORDS = {
    "scenic": ["china landscape", "park lake china"],
    "food": ["chinese food dish", "chinese restaurant table"],
    "hotel": ["hotel room modern", "hotel lobby interior"],
    "leisure": ["leisure park china", "weekend activity china"],
    "study": ["university campus china", "campus architecture"],
}

# 子类型 → 检索词（按 key 长度优先匹配，覆盖库里全部 sub_type）
SUB_TYPE_KEYWORDS = {
    # 景点
    "古镇": ["ancient town china", "old town stone street"],
    "屯堡遗址": ["chinese stone village", "ancient fort china"],
    "城墙遗址": ["ancient city wall china", "stone gate tower"],
    "湿地步道": ["wetland boardwalk", "lake park trail"],
    "湿地": ["wetland park", "marsh lake china"],
    "滨水景观": ["riverside promenade", "lakefront park"],
    "亲水河谷": ["river valley china", "stream park"],
    "城市山水": ["city park lake", "urban park china"],
    "峡谷": ["canyon china", "gorge river"],
    "溶洞山水": ["karst cave china", "limestone cave"],
    "田园风光": ["terraced fields china", "rural farmland"],
    "乡村": ["chinese village countryside", "rural landscape"],
    "花海": ["flower field china", "blooming garden"],
    "茶园": ["tea plantation china", "tea garden hills"],
    "艺术园区": ["art district china", "creative park"],
    "艺术地貌": ["stone sculpture park", "art landscape"],
    "民族村寨": ["ethnic minority village china", "miao village"],
    "大学校园": ["university campus china", "campus building"],
    "文化场馆": ["museum interior china", "cultural center"],
    # 美食
    "米粉小吃": ["rice noodle soup", "chinese noodle bowl"],
    "面食": ["chinese noodles", "hand pulled noodles"],
    "小吃街": ["chinese street food market", "snack street night"],
    "街头小吃": ["chinese street food", "street food stall"],
    "油炸小吃": ["chinese fried snack", "fried dough street food"],
    "黔味小吃": ["guizhou snack", "chinese savory snack"],
    "火锅": ["chinese hotpot", "hotpot table"],
    "烙锅夜宵": ["chinese griddle food", "late night street food"],
    "烧烤夜宵": ["chinese barbecue skewers", "bbq street food"],
    "酸汤鱼": ["fish soup chinese", "sour soup fish"],
    "黔菜宴席": ["chinese banquet table", "chinese dishes spread"],
    "黔菜老字号": ["braised pork chinese", "chinese traditional dish"],
    "黔菜": ["chinese home style dishes", "stir fry chinese"],
    "农家菜": ["chinese farmhouse dishes", "rustic chinese food"],
    "屯堡菜": ["chinese traditional cuisine", "chinese clay pot"],
    "甜品伴手礼": ["chinese dessert", "chinese pastry shop"],
    "轻食茶歇": ["cafe interior", "coffee and cake"],
    # 住宿
    "古镇民宿": ["boutique guesthouse courtyard", "traditional inn china"],
    "设计民宿": ["design hotel room", "boutique hotel interior"],
    "温泉度假": ["hot spring resort", "onsen hotel"],
    "温泉酒店": ["hot spring bath hotel", "hotel pool"],
    "山景酒店": ["mountain view hotel", "hotel balcony view"],
    "湖景酒店": ["lake view hotel", "hotel window lake"],
    "国宾接待": ["luxury hotel lobby", "grand hotel interior"],
    "连锁舒适": ["hotel room modern", "hotel room bed"],
    "连锁经济": ["budget hotel room", "simple hotel room"],
    "青旅": ["hostel dorm room", "hostel common area"],
    "特色露营": ["glamping tent", "camping tent night"],
    "校园酒店": ["hotel room modern", "hotel corridor"],
    # 休闲
    "温泉": ["hot spring pool", "onsen bath"],
    "游船": ["boat on lake", "river cruise china"],
    "皮划艇": ["kayak lake", "canoe river"],
    "滑翔伞": ["paragliding sky", "paraglider mountain"],
    "骑行": ["cycling path park", "bicycle riverside"],
    "露营": ["camping tent park", "tent outdoor night"],
    "草坪休闲": ["picnic lawn park", "green lawn people"],
    "夜市": ["night market china", "street food night lights"],
    "茶馆": ["chinese teahouse interior", "tea set table"],
    "影院": ["cinema screen seats", "movie theater"],
    "室内桌游": ["board game cafe", "friends playing board game"],
    "手工体验": ["pottery workshop hands", "craft workshop"],
    "非遗手作": ["traditional handicraft china", "artisan workshop"],
    "旅拍": ["portrait photo street", "photographer shooting"],
    "卡丁车": ["go kart track", "karting race"],
    "亲子游乐": ["children playground park", "kids playing outdoor"],
    # 游学
    "校园广场": ["university campus plaza", "campus square china"],
    "校园建筑": ["university building china", "campus architecture"],
    "校史展馆": ["museum exhibition hall", "archive exhibition"],
    "文保建筑": ["historic brick building china", "heritage architecture"],
    "省级文保": ["historic architecture china", "protected building"],
    "季节景观": ["cherry blossom campus", "spring blossom trees"],
    "常绿景观": ["campus lake green", "evergreen garden"],
    "出校动线": ["campus gate street", "university entrance"],
}


def http_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_bytes(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as resp:
        ctype = resp.headers.get("Content-Type", "")
        return resp.read(), ctype


# ---------------------------------------------------------------- Providers
class Candidate:
    __slots__ = ("url", "author", "source_name", "license", "license_url", "query", "width")

    def __init__(self, url, author, source_name, license, license_url, query, width=0):
        self.url = url
        self.author = author
        self.source_name = source_name
        self.license = license
        self.license_url = license_url
        self.query = query
        self.width = width


def search_pexels(query: str, limit: int) -> list[Candidate]:
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        return []
    url = ("https://api.pexels.com/v1/search?query="
           + urllib.parse.quote(query) + f"&per_page={max(1, min(limit, 15))}&orientation=landscape")
    data = http_json(url, {"Authorization": key})
    out = []
    for p in data.get("photos", []):
        src = p.get("src", {})
        link = src.get("large2x") or src.get("large") or src.get("original")
        if not link:
            continue
        out.append(Candidate(
            url=link, author=p.get("photographer") or "", source_name="Pexels",
            license=ALLOWED_LICENSES["pexels license"][0],
            license_url=ALLOWED_LICENSES["pexels license"][1],
            query=query, width=int(p.get("width") or 0),
        ))
    return out


def search_unsplash(query: str, limit: int) -> list[Candidate]:
    key = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
    if not key:
        return []
    url = ("https://api.unsplash.com/search/photos?query="
           + urllib.parse.quote(query) + f"&per_page={max(1, min(limit, 15))}&orientation=landscape")
    data = http_json(url, {"Authorization": "Client-ID " + key})
    out = []
    for p in data.get("results", []):
        link = (p.get("urls") or {}).get("regular")
        if not link:
            continue
        out.append(Candidate(
            url=link, author=(p.get("user") or {}).get("name", ""), source_name="Unsplash",
            license=ALLOWED_LICENSES["unsplash license"][0],
            license_url=ALLOWED_LICENSES["unsplash license"][1],
            query=query, width=int((p.get("width") or 0)),
        ))
    return out


PROVIDERS = [("pexels", search_pexels), ("unsplash", search_unsplash)]


def available_providers() -> list[str]:
    names = []
    if os.getenv("PEXELS_API_KEY", "").strip():
        names.append("pexels")
    if os.getenv("UNSPLASH_ACCESS_KEY", "").strip():
        names.append("unsplash")
    return names


# ---------------------------------------------------------------- 业务
def admin_login() -> str:
    body = json.dumps({"username": ADMIN_USER, "password": ADMIN_PASS}).encode()
    req = urllib.request.Request(
        API_BASE + "/admin/login", data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())["token"]


def list_pois() -> list[dict]:
    """分页取全部 POI（含 study，游学点也要配图）。"""
    items, page = [], 1
    while True:
        data = http_json(f"{API_BASE}/pois?page={page}&page_size=50")
        items.extend(data.get("items", []))
        if len(items) >= data.get("total", 0) or not data.get("items"):
            break
        page += 1
    return items


def queries_for(poi: dict) -> list[str]:
    """按子类型（最长匹配）优先、再按类别，拼 2~4 个检索词。"""
    qs: list[str] = []
    sub = (poi.get("sub_type") or "").strip()
    if sub:
        for key in sorted(SUB_TYPE_KEYWORDS, key=len, reverse=True):
            if key in sub:
                qs.extend(SUB_TYPE_KEYWORDS[key])
                break
    qs.extend(CATEGORY_KEYWORDS.get(poi.get("category", ""), ["travel china"]))
    out, seen = [], set()
    for q in qs:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def upload(poi_id: int, data: bytes, filename: str, cand: Candidate, token: str,
           set_cover: bool) -> dict:
    boundary = "----TravelPortalBoundary7d1a"
    fields = {
        "source_name": cand.source_name,
        "author": cand.author or "",
        "license": cand.license,
        "license_url": cand.license_url,
        "note": f"query: {cand.query}",
        "set_cover": "true" if set_cover else "false",
    }
    body = bytearray()
    for k, v in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
        body += str(v).encode("utf-8") + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += (f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             "Content-Type: image/jpeg\r\n\r\n").encode()
    body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{API_BASE}/admin/pois/{poi_id}/images/upload", data=bytes(body),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": "Bearer " + token,
            "User-Agent": UA,
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-poi", type=int, default=3, help="每个 POI 目标图片数（2~5）")
    ap.add_argument("--limit", type=int, default=0, help="本轮最多处理多少个 POI")
    ap.add_argument("--only", default="", help="只处理这些 id，逗号分隔")
    ap.add_argument("--force", action="store_true", help="已有 upload 图也重采")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不发请求")
    args = ap.parse_args()

    providers = available_providers()
    pois = list_pois()
    only = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
    if only:
        pois = [p for p in pois if p["id"] in only]

    targets = []
    for p in pois:
        have = len(p.get("images") or [])  # 已过滤为 upload-only
        if have >= args.per_poi and not args.force:
            continue
        targets.append((p, max(0, args.per_poi - have)))
    if args.limit:
        targets = targets[: args.limit]

    print(f"POI 总数 {len(pois)}，本轮待补 {len(targets)} 个；可用图源: {providers or '无（缺 API Key）'}")
    if args.dry_run:
        for p, need in targets[:20]:
            print(f"  [{p['id']}] {p['name']}（{p['category']}/{p.get('sub_type','')}）还差 {need} 张 → {queries_for(p)[:2]}")
        if len(targets) > 20:
            print(f"  …… 其余 {len(targets) - 20} 个省略")
        return

    if not providers:
        print("没有可用的图源：请设置 PEXELS_API_KEY 或 UNSPLASH_ACCESS_KEY（均免费申请）")
        sys.exit(2)

    token = admin_login()
    report = {"uploaded": [], "skipped": [], "failed": []}
    for idx, (p, need) in enumerate(targets, 1):
        pid, name = p["id"], p["name"]
        got = 0
        for q in queries_for(p):
            if got >= need:
                break
            for prov_name, fn in PROVIDERS:
                if got >= need:
                    break
                if prov_name not in providers:
                    continue
                try:
                    cands = fn(q, need - got + 2)
                except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                    print(f"  ! {prov_name} 检索失败 {q}: {exc}")
                    continue
                for c in cands:
                    if got >= need:
                        break
                    try:
                        data, ctype = http_bytes(c.url)
                    except Exception as exc:  # noqa: BLE001
                        report["failed"].append({"id": pid, "url": c.url, "err": str(exc)})
                        continue
                    if len(data) < 20_000 or "image" not in ctype:
                        continue
                    try:
                        res = upload(pid, data, f"poi{pid}_{int(time.time())}.jpg", c, token,
                                     set_cover=(len(p.get("images") or []) + got == 0))
                    except Exception as exc:  # noqa: BLE001
                        report["failed"].append({"id": pid, "url": c.url, "err": str(exc)})
                        continue
                    got += 1
                    report["uploaded"].append({"id": pid, "name": name, "url": res.get("url"),
                                               "source": c.source_name, "query": q,
                                               "license": c.license})
                    print(f"  [{idx}/{len(targets)}] {name} +1 ← {c.source_name} / {q}")
        if got == 0:
            report["skipped"].append({"id": pid, "name": name, "reason": "无合适素材"})

    out = BASE_DIR / "scripts" / "poi_images_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成：新增 {len(report['uploaded'])} 张，跳过 {len(report['skipped'])} 个 POI，失败 {len(report['failed'])} 次")
    print("报告:", out)


if __name__ == "__main__":
    main()
