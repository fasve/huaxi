"""从高德 POI 搜索批量扩充「花溪区」资源库（GCJ-02，合规半自动导入）。

背景：种子库只有 80 条演示 POI；高德 adcode=520111 下景点约 580、餐饮/住宿/休闲各 600+。
本脚本按类型分页抓取 → 清洗过滤 → 去重 → 补齐本项目字段（价格档/时长/标签/扩展）→
导出可人工抽检的 CSV/报告，或在 `--apply` 时直接写库（带完整的 open_time / ext / 标签）。

用法（在 travel-api 目录下）：
    .\.venv\Scripts\python.exe scripts\import_amap_pois.py --dry-run
    .\.venv\Scripts\python.exe scripts\import_amap_pois.py --apply

输出目录：travel-api/scripts/amap_export/
- amap_pois_extended.csv  完整抓取结果（含 open_time / ext / tags，便于抽检与备份）
- amap_pois_review.csv    需要人工核对的字段（门票/住宿价/营业时间缺失等）
- amap_pois_report.json   数量、地理分布、去重跳过明细

注意：
- 高德返回坐标即 GCJ-02，符合本项目「地图/行程用 GCJ-02」的口径；无需转换；
- 门票价格、A 级、评分人数等高德不提供，脚本按保守默认值处理并在 review CSV 中标注；
- 高德 POI 数据的存储与展示授权请遵循高德开放平台开发者协议，本项目仅本地演示使用。
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.config import settings  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "amap_export"
AMAP_URL = "https://restapi.amap.com/v3/place/text"

# 抓取计划：每类目抓取页数 / 最终保留条数 / 最低评分
PLAN = {
    "scenic": dict(types="110000", pages=12, limit=70, min_rating=4.0),
    "food": dict(types="050000", pages=20, limit=80, min_rating=4.2),
    "hotel": dict(types="100000", pages=6, limit=30, min_rating=4.0),
    "leisure": dict(types="080000", pages=10, limit=40, min_rating=4.0),
}
TYPE_PREFIX = {"scenic": "11", "food": "05", "hotel": "10", "leisure": "08"}

# 明显不是"游客可去资源"的子设施/机构
BAD_WORDS = (
    "售票", "停车场", "停车区", "厕所", "卫生间", "游客中心", "游客服务",
    "服务中心", "管理处", "派出所", "医务", "公交站", "地铁站", "充电", "ATM",
    "自动取款", "出入口", "入口", "出口", "检票", "垃圾", "培训", "中介", "售楼",
    "公共厕所", "保安", "警务", "变电站", "泵站", "垃圾站",
)
# 分类专属黑名单：避免把非旅游资源混进来
BAD_WORDS_BY_CAT = {
    "scenic": ("墓", "陵园", "殡", "火葬", "酒店", "宾馆", "客栈", "民宿",
               "餐厅", "饭店", "超市", "商店", "商铺", "专卖"),
    "food": ("食堂", "学校", "学院", "公司", "单位", "工厂", "超市", "便利店", "食品公司"),
    "hotel": (),
    "leisure": ("健身", "电竞", "网咖", "台球", "棋牌", "足浴", "洗浴", "KTV",
                "酒吧", "会所", "美容", "美发", "养生", "网吧", "酒店", "宾馆",
                "客栈", "民宿"),
}
# 美食类目按关键词补充召回（单一 types 查询分页有上限，靠关键词提高多样性）
FOOD_KEYWORDS = ("牛肉粉", "酸汤鱼", "丝娃娃", "烙锅", "烧烤", "火锅",
                 "黔菜", "小吃", "咖啡", "奶茶")
# 休闲只保留"旅游向"的玩法，过滤健身房/网咖等本地生活服务
LEISURE_KEEP = ("温泉", "游船", "露营", "花海", "采摘", "茶", "影院", "影城", "桌游",
                "旅拍", "卡丁车", "滑翔", "皮划艇", "马术", "骑马", "滑雪", "乐园",
                "亲子", "垂钓", "骑行", "手工", "非遗", "陶艺", "钓")

CATEGORY_CN = {"scenic": "景点", "food": "美食", "hotel": "住宿", "leisure": "休闲"}

# 花溪区大致边界（GCJ-02）
LON_MIN, LON_MAX = 106.40, 106.95
LAT_MIN, LAT_MAX = 26.15, 26.65

DEFAULT_OPEN = {
    "scenic": [["08:30", "18:00"]],
    "food": [["10:00", "21:30"]],
    "hotel": [["全天", "全天"]],
    "leisure": [["10:00", "22:00"]],
}
DEFAULT_DURATION = {"scenic": 120, "food": 60, "hotel": 60, "leisure": 90}

DURATION_RULES: dict[str, list[tuple[str, int]]] = {
    "scenic": [
        ("古镇", 180), ("湿地", 150), ("公园", 120), ("寺", 60), ("庙", 60),
        ("博物馆", 90), ("纪念馆", 90), ("展览", 90), ("山", 180), ("峡谷", 180),
        ("瀑布", 120), ("湖", 120), ("寨", 150), ("故居", 60), ("遗址", 90), ("广场", 60),
    ],
    "food": [
        ("小吃", 40), ("快餐", 30), ("饮品", 20), ("咖啡", 60), ("茶", 60),
        ("火锅", 90), ("烧烤", 80), ("中餐厅", 60), ("甜品", 30), ("面", 40),
    ],
    "leisure": [
        ("温泉", 180), ("露营", 180), ("垂钓", 120), ("游船", 90), ("影院", 120),
        ("KTV", 120), ("采摘", 90), ("花海", 120), ("乐园", 150), ("马术", 90),
        ("滑雪", 120), ("茶", 90), ("桌游", 120),
    ],
}

HOTEL_GRADE_RULES = [
    ("五星级", "高端"), ("四星级", "舒适"), ("三星级", "舒适"),
    ("经济型", "经济"), ("民宿", "民宿"), ("公寓", "经济"), ("青年旅舍", "经济"),
    ("青旅", "经济"), ("度假", "高端"), ("温泉", "高端"),
]
GRADE_PRICE = {"经济": 160, "舒适": 300, "高端": 600, "民宿": 240}
GRADE_LEVEL = {"经济": 2, "舒适": 3, "高端": 4, "民宿": 3}


# ---------------- 高德抓取 ----------------

def http_get(url: str, timeout: int = 20) -> dict:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(1.5)
    return {}


def _fetch_pages(types: str, pages: int, keywords: str | None = None) -> list[dict]:
    """按页抓取高德 POI（offset 固定 25）。"""
    pois: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        params = {
            "key": settings.amap_key, "types": types, "city": "520111",
            "citylimit": "true", "offset": 25, "page": page, "extensions": "all",
        }
        if keywords:
            params["keywords"] = keywords
        url = AMAP_URL + "?" + urllib.parse.urlencode(params)
        data = http_get(url)
        rows = data.get("pois") or []
        if not rows:
            break
        for poi in rows:
            pid = poi.get("id") or ""
            if not pid or pid in seen:
                continue
            seen.add(pid)
            pois.append(poi)
        time.sleep(0.15)
    return pois


def fetch_category(category: str) -> list[dict]:
    cfg = PLAN[category]
    pois = _fetch_pages(cfg["types"], cfg["pages"])
    if category == "food":
        # types 查询分页有上限，按本地菜品关键词再补几轮召回
        seen_ids = {p.get("id") for p in pois}
        for kw in FOOD_KEYWORDS:
            for poi in _fetch_pages(cfg["types"], 2, keywords=kw):
                pid = poi.get("id") or ""
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    pois.append(poi)
    print(f"[fetch] {category}: 抓取 {len(pois)} 条")
    return pois


# ---------------- 字段映射 ----------------

def _float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", [], {}):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _location(poi: dict) -> tuple[float, float] | None:
    raw = poi.get("location") or ""
    if "," not in raw:
        return None
    lng, lat = raw.split(",", 1)
    return _float(lng), _float(lat)


def _bbox_ok(lng: float, lat: float) -> bool:
    return LON_MIN <= lng <= LON_MAX and LAT_MIN <= lat <= LAT_MAX


def _type_parts(poi: dict) -> list[str]:
    raw = poi.get("type") or ""
    parts: list[str] = []
    for chunk in re.split(r"[;|]", raw):
        seg = chunk.strip()
        if seg and seg != "[]" and seg not in parts:
            parts.append(seg)
    return parts


CROSS_TYPES = {
    "体育休闲服务场所", "体育休闲服务", "购物相关场所", "购物服务",
    "餐饮相关场所", "住宿服务相关", "商务住宅相关", "商务住宅",
    "休闲场所", "风景名胜相关", "住宅小区", "商务写字楼", "购物中心",
    "商场", "超市", "便利店", "餐饮相关", "住宿服务",
}
_CROSS_WORDS = ("住宅", "写字楼", "购物", "商场", "超市", "停车", "商务", "公司", "单位")
# 不同类目下"合理"的子类关键词，用于跳过被混入的跨类目类型
CATEGORY_SUBTYPE_WORDS = {
    "scenic": ("古镇", "公园", "湿地", "湖", "山", "峡谷", "瀑布", "寺", "庙", "遗址",
               "故居", "博物", "纪念", "文化", "广场", "风景", "旅游", "观景", "寨", "村", "园"),
    "food": ("火锅", "小吃", "米线", "粉", "面", "烧烤", "咖啡", "茶", "甜品", "糕",
             "酒楼", "餐厅", "菜馆", "饭馆", "快餐", "料理", "菜", "餐饮"),
    "hotel": ("酒店", "宾馆", "旅馆", "招待所", "民宿", "客栈", "公寓", "青旅", "旅舍", "驿站"),
    "leisure": ("温泉", "游船", "露营", "采摘", "垂钓", "乐园", "游乐", "影院", "影城",
                "茶", "桌游", "旅拍", "卡丁车", "皮划艇", "滑翔", "马术", "滑雪",
                "骑行", "手工", "非遗", "水上", "体育", "休闲"),
}


def _sub_type(poi: dict, category: str) -> str:
    parts = _type_parts(poi)
    name = poi.get("name") or ""
    if category == "scenic" and "古镇" in name:
        return "古镇"
    words = CATEGORY_SUBTYPE_WORDS[category]
    for seg in reversed(parts):
        if seg in CROSS_TYPES or any(w in seg for w in _CROSS_WORDS):
            continue
        if any(w in seg for w in words):
            return seg
    # 类型不可用时按名称猜一个（仅景点做名称联想，避免酒店/餐饮误判成"公园"）
    if category == "scenic":
        for kw, label in (("古镇", "古镇"), ("公园", "公园"), ("湖", "湖泊"), ("寺", "寺庙"),
                          ("庙", "寺庙"), ("寨", "村寨"), ("博物", "文化场馆"),
                          ("艺术", "艺术园区"), ("湿地", "湿地")):
            if kw in name:
                return label
    return {"scenic": "景点", "food": "餐饮", "hotel": "酒店", "leisure": "休闲体验"}[category]


def parse_open_time(poi: dict, category: str) -> tuple[list, bool]:
    """解析高德 open_time（如 "周一至周日 08:00-19:00"/"00:00-24:00 08:30-17:00"）。"""
    biz = poi.get("biz_ext") or {}
    raw = biz.get("open_time") or biz.get("opentime2") or ""
    if isinstance(raw, list):
        raw = " ".join(str(x) for x in raw if x)
    pairs = re.findall(r"(\d{1,2}:\d{2})\s*[-~至]\s*(\d{1,2}:\d{2})", str(raw))
    if pairs:
        # 优先选“真实营业时段”（剔除 00:00-24:00 这类全天占位）
        useful = [(s, e) for s, e in pairs if not (s == "00:00" and e in ("24:00", "23:59"))]
        s, e = (useful or pairs)[0]
        if e <= s:  # 跨夜（如 16:00-02:00）裁剪到 23:59，避免行程算法异常
            e = "23:59"
        return [[s, e]], True
    return DEFAULT_OPEN[category], False


def duration_for(category: str, sub_type: str, name: str) -> int:
    for kw, minutes in DURATION_RULES.get(category, []):
        if kw in sub_type or kw in name:
            return minutes
    return DEFAULT_DURATION[category]


def _tags_build(category: str, name: str, sub_type: str, type_str: str,
                rating: float, cost: float, open_time: list, known_cost: bool = False) -> list[tuple[str, float]]:
    """按名称/类型/价格启发式打标，最多 5 个；权重递减。"""
    hits: list[str] = []

    def add(code: str) -> None:
        if code not in hits:
            hits.append(code)

    text = f"{name} {sub_type} {type_str}"
    if category == "scenic":
        if any(k in text for k in ("公园", "湿地", "湖", "山", "峡谷", "瀑布", "森林", "田园", "花海", "河")):
            add("nature")
        if any(k in text for k in ("古镇", "古城", "寺", "庙", "祠", "故居", "遗址", "博物", "纪念", "文化", "屯堡", "城墙")):
            add("heritage")
        if any(k in text for k in ("花海", "樱花", "荷花", "茶园", "采摘")):
            add("seasonal")
        if any(k in name for k in ("古镇", "湿地", "花海", "观景", "梯田", "夜景", "古街")):
            add("photospot")
        if any(k in text for k in ("公园", "乐园", "亲子", "动物园", "海洋馆", "科技馆")):
            add("family")
        if any(k in text for k in ("观景", "山顶", "塔", "楼", "桥", "湖景", "江景")):
            add("view")
        if any(k in text for k in ("苗寨", "布依", "民族", "村寨")):
            add("minority")
        if any(k in text for k in ("大学", "学院", "校园")):
            add("campus")
        # 只有高德明确给出 cost（且为 0）时才标"免费"，缺失不等于免费
        if known_cost and cost <= 0:
            add("budget_free")
    elif category == "food":
        if any(k in text for k in ("贵州", "黔", "花溪", "青岩", "本地", "牛肉粉", "酸汤", "丝娃娃", "烙锅", "肠旺")):
            add("local")
        if any(k in text for k in ("小吃街", "美食街", "夜市", "小吃城")):
            add("food_street")
        if cost and cost <= 20:
            add("budget_free")
    elif category == "hotel":
        if any(k in text for k in ("温泉", "度假", "观景", "湖景", "山景", "庄园")):
            add("comfort")
        if any(k in text for k in ("山", "湖", "景", "观景")):
            add("view")
        if "民宿" in text or "设计" in text or "青旅" in text:
            add("comfort")
    elif category == "leisure":
        if any(k in text for k in ("温泉", "茶", "书", "咖啡", "垂钓", "露营", "桌游")):
            add("comfort")
        if any(k in text for k in ("骑行", "徒步", "攀岩", "球场", "健身", "卡丁车", "滑翔", "皮划艇", "滑雪", "马术")):
            add("active")
        if any(k in text for k in ("花海", "公园", "湿地", "自然", "露营")):
            add("nature")
        if any(k in text for k in ("亲子", "乐园", "游乐园", "动物", "采摘")):
            add("family")
        if any(k in text for k in ("夜市", "影院", "KTV", "夜")):
            add("night_view")
        if any(k in name for k in ("旅拍", "观景", "花海", "夜景")):
            add("photospot")

    if not hits:
        add({"scenic": "nature", "food": "local", "hotel": "comfort", "leisure": "comfort"}[category])
    weights = [1.0, 0.8, 0.6, 0.5, 0.4]
    return [(code, weights[i]) for i, code in enumerate(hits[:5])]


def price_level_for(category: str, value: float) -> int:
    if category == "hotel":
        return 2 if value <= 180 else 3 if value <= 350 else 4 if value <= 700 else 5
    if value <= 0:
        return 1
    if value <= 30:
        return 1
    if value <= 60:
        return 2
    if value <= 120:
        return 3
    if value <= 300:
        return 4
    return 5


def _indoor(poi: dict, category: str) -> bool:
    text = f"{poi.get('name') or ''} {';'.join(_type_parts(poi))}"
    return any(k in text for k in ("博物", "纪念馆", "展览", "美术馆", "图书馆", "书店", "影院", "KTV", "桌游", "室内"))


def _grade(poi: dict) -> tuple[str, int]:
    text = f"{poi.get('name') or ''} {';'.join(_type_parts(poi))}"
    for kw, grade in HOTEL_GRADE_RULES:
        if kw in text:
            return grade, {"经济": 0, "舒适": 3, "高端": 5, "民宿": 0}[grade]
    return "经济", 0


def build_record(poi: dict, category: str) -> dict | None:
    name = (poi.get("name") or "").strip()
    if not name or any(bad in name for bad in BAD_WORDS):
        return None
    if any(bad in name for bad in BAD_WORDS_BY_CAT[category]):
        return None
    # 严格限定花溪区（citylimit 仍会漏出南明/经开等周边结果）
    if (poi.get("adname") or "").strip() != "花溪区":
        return None
    if len(name) < 2 or len(name) > 60:
        return None
    loc = _location(poi)
    if not loc or not _bbox_ok(*loc):
        return None
    lng, lat = loc
    typecode = (poi.get("typecode") or "").strip()
    if not typecode.startswith(TYPE_PREFIX[category]):
        return None
    # 休闲只保留旅游向玩法
    if category == "leisure":
        leisure_text = name + " " + " ".join(_type_parts(poi))
        if not any(k in leisure_text for k in LEISURE_KEEP):
            return None
    biz = poi.get("biz_ext") or {}
    rating = _float(biz.get("rating"))
    if rating <= 0:  # 无评分的不入库，避免排序被污染
        return None
    cost = _float(biz.get("cost"))
    known_cost = biz.get("cost") not in (None, "", [], {}, "[]")
    sub_type = _sub_type(poi, category)
    type_str = " ".join(_type_parts(poi))
    open_time, open_ok = parse_open_time(poi, category)
    tags = _tags_build(category, name, sub_type, type_str, rating, cost, open_time, known_cost)
    issues: list[str] = []
    if not open_ok:
        issues.append("营业时间缺失，已用默认值")
    if not (poi.get("address") or "").strip():
        issues.append("地址缺失")

    ext: dict = {}
    ticket_price = 0.0
    price_level = 1
    if category == "scenic":
        ticket_price = 0.0
        price_level = 2
        ext = dict(level="", need_reservation=False, best_season="全季",
                   indoor=_indoor(poi, category), physical_level=2, is_landmark=rating >= 4.7)
        issues.append("门票/等级未知（按 0 元、2 档处理）")
    elif category == "food":
        ticket_price = cost
        price_level = price_level_for(category, cost)
        cuisine = "黔菜" if any(k in type_str + name for k in ("贵州", "黔", "本地")) else "中餐"
        ext = dict(cuisine=cuisine, signature=[], avg_price=cost or 40,
                   meal_period="午,晚", is_time_honored=False)
        if not cost:
            issues.append("人均消费缺失，按 40 元估算")
    elif category == "hotel":
        grade, star = _grade(poi)
        price_min = GRADE_PRICE[grade]
        price_level = GRADE_LEVEL[grade]
        ticket_price = float(price_min)
        ext = dict(grade=grade, star=star, facility_tags=[],
                   price_min=float(price_min), with_breakfast=False)
        issues.append(f"无公开房价，按{grade}档 {price_min} 元/晚估算")
    else:
        ticket_price = cost
        price_level = price_level_for(category, cost)
        play_type = sub_type if sub_type not in ("休闲场所", "体育休闲服务场所", "") else "休闲体验"
        night = any(k in type_str + name for k in ("夜市", "酒吧", "KTV", "影院"))
        ext = dict(play_type=play_type, night_open=night, indoor=_indoor(poi, category))

    return dict(
        name=name, category=category, sub_type=sub_type,
        address=(poi.get("address") or "").strip() or "花溪区",
        longitude=round(lng, 6), latitude=round(lat, 6),
        open_time=open_time, suggest_duration_min=duration_for(category, sub_type, name),
        ticket_price=ticket_price, price_level=price_level,
        rating=round(rating, 1), review_count=0,
        tags=tags, ext=ext, issues=issues,
        amap_id=poi.get("id") or "", tel=str(poi.get("tel") or ""),
    )


# ---------------- 去重 ----------------

def _norm_name(name: str) -> str:
    s = re.sub(r"[（(].*?[）)]", "", name)
    s = re.sub(r"[\s·•,，。.、-]+", "", s)
    return s.lower()


def _core_name(name: str) -> str:
    """去掉行政区/修饰词，得到"核心地名"，用于识别同地异名（如 十里河滩）。"""
    s = _norm_name(name)
    for word in ("花溪区", "花溪", "贵阳市", "贵阳", "贵州省", "贵州", "国家", "城市",
                 "旅游", "度假区", "风景区", "景区", "湿地公园", "湿地", "公园",
                 "古镇", "景区内"):
        s = s.replace(word, "")
    return s


def dedupe(records: list[dict], existing_names: set[str]) -> tuple[list[dict], list[dict]]:
    accepted: list[dict] = []
    skipped: list[dict] = []
    existing_norm = {_norm_name(n) for n in existing_names}
    existing_core = {_core_name(n) for n in existing_names}
    accepted_core: set[str] = set()
    for rec in records:
        key = _norm_name(rec["name"])
        core = _core_name(rec["name"])
        dup_reason = ""
        if key in existing_norm or (len(core) >= 2 and core in existing_core):
            dup_reason = "与现有资源重名/同地异名"
        elif core in accepted_core:
            dup_reason = "抓取结果内部重名"
        else:
            for acc in accepted:
                acc_key = _norm_name(acc["name"])
                if key == acc_key:
                    dup_reason = "抓取结果内部重名"
                    break
                if difflib.SequenceMatcher(None, key, acc_key).ratio() >= 0.9:
                    dup_reason = f"与 {acc['name']} 高度相似"
                    break
        if dup_reason:
            skipped.append(dict(name=rec["name"], category=rec["category"], reason=dup_reason))
        else:
            accepted.append(rec)
            accepted_core.add(core)
    return accepted, skipped


# ---------------- 输出 ----------------

def write_outputs(records: list[dict], skipped: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "amap_pois_extended.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "category", "sub_type", "address", "longitude", "latitude",
                         "open_time", "suggest_duration_min", "ticket_price", "price_level",
                         "rating", "tags", "ext", "amap_id"])
        for r in records:
            writer.writerow([
                r["name"], r["category"], r["sub_type"], r["address"], r["longitude"], r["latitude"],
                json.dumps(r["open_time"], ensure_ascii=False),
                r["suggest_duration_min"], r["ticket_price"], r["price_level"], r["rating"],
                "|".join(code for code, _ in r["tags"]),
                json.dumps(r["ext"], ensure_ascii=False), r["amap_id"],
            ])
    review_path = OUT_DIR / "amap_pois_review.csv"
    with review_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "category", "sub_type", "address", "rating", "price_level",
                         "amap_id", "issues"])
        for r in records:
            writer.writerow([r["name"], r["category"], r["sub_type"], r["address"],
                             r["rating"], r["price_level"], r["amap_id"], "；".join(r["issues"])])

    cats = Counter(r["category"] for r in records)
    quad = Counter()
    lons = [r["longitude"] for r in records] or [106.67]
    lats = [r["latitude"] for r in records] or [26.42]
    mid_lon, mid_lat = sum(lons) / len(lons), sum(lats) / len(lats)
    for r in records:
        quad[("东" if r["longitude"] >= mid_lon else "西") + ("北" if r["latitude"] >= mid_lat else "南")] += 1
    report = dict(
        accepted_total=len(records),
        by_category=dict(cats),
        review_needed=sum(1 for r in records if r["issues"]),
        skipped_total=len(skipped),
        skipped=skipped[:50],
        quadrant_distribution=dict(quad),
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    (OUT_DIR / "amap_pois_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[output] {csv_path}")
    print(f"[output] {review_path}")
    print(f"[output] {OUT_DIR / 'amap_pois_report.json'}")


# ---------------- 写库 ----------------

def apply_to_db(records: list[dict]) -> None:
    from sqlalchemy import func

    from app.database import SessionLocal
    from app.models import (
        Poi, PoiExtFood, PoiExtHotel, PoiExtLeisure, PoiExtScenic, PoiTag, Tag,
    )
    from app.services import qa_retrieval
    from app.services.cache import poi_cache

    db = SessionLocal()
    try:
        tag_ids = {code: tid for tid, code in db.query(Tag.id, Tag.code).all()}
        inserted = 0
        for r in records:
            p = Poi(
                name=r["name"], category=r["category"], sub_type=r["sub_type"],
                address=r["address"], longitude=r["longitude"], latitude=r["latitude"],
                district="花溪区", open_time=r["open_time"],
                suggest_duration_min=r["suggest_duration_min"],
                ticket_price=r["ticket_price"], price_level=r["price_level"],
                rating=r["rating"], review_count=0,
                hot_score=round(r["rating"] / 5 * 0.7, 3),
                quality_score=round(r["rating"] / 5 * 0.85, 3),
                visitable=True, images=[], image_meta=[],
            )
            db.add(p)
            db.flush()
            ext = r["ext"]
            cat = r["category"]
            if cat == "scenic":
                db.add(PoiExtScenic(poi_id=p.id, level=ext.get("level", ""),
                                    need_reservation=ext.get("need_reservation", False),
                                    best_season=ext.get("best_season", "全季"),
                                    indoor=ext.get("indoor", False),
                                    physical_level=ext.get("physical_level", 2),
                                    is_landmark=ext.get("is_landmark", False)))
            elif cat == "food":
                db.add(PoiExtFood(poi_id=p.id, cuisine=ext.get("cuisine", "中餐"),
                                  signature=ext.get("signature", []),
                                  avg_price=ext.get("avg_price", 40),
                                  meal_period=ext.get("meal_period", "午,晚"),
                                  is_time_honored=False))
            elif cat == "hotel":
                db.add(PoiExtHotel(poi_id=p.id, grade=ext.get("grade", "经济"),
                                   star=ext.get("star", 0),
                                   facility_tags=ext.get("facility_tags", []),
                                   price_min=ext.get("price_min", 160),
                                   with_breakfast=False))
            elif cat == "leisure":
                db.add(PoiExtLeisure(poi_id=p.id, play_type=ext.get("play_type", "休闲体验"),
                                     night_open=ext.get("night_open", False),
                                     indoor=ext.get("indoor", False)))
            for code, weight in r["tags"]:
                tid = tag_ids.get(code)
                if tid:
                    db.add(PoiTag(poi_id=p.id, tag_id=tid, weight=weight))
            inserted += 1
            if inserted % 50 == 0:
                db.commit()
        db.commit()
        total = db.query(func.count(Poi.id)).scalar()
        print(f"[apply] 新增 {inserted} 条，库内 POI 总数 = {total}")
        poi_cache.invalidate_prefix("pois:")
        qa_retrieval.invalidate()
    finally:
        db.close()


# ---------------- 主流程 ----------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只抓取并导出 CSV/报告，不写库")
    parser.add_argument("--apply", action="store_true", help="抓取后直接写入数据库")
    parser.add_argument("--scenic", type=int, help="景点保留条数（覆盖默认）")
    parser.add_argument("--food", type=int, help="美食保留条数")
    parser.add_argument("--hotel", type=int, help="住宿保留条数")
    parser.add_argument("--leisure", type=int, help="休闲保留条数")
    args = parser.parse_args()
    if not (args.dry_run or args.apply):
        parser.error("请指定 --dry-run 或 --apply")
    if not settings.amap_key:
        print("缺少 AMAP_KEY，请先配置 travel-api/.env")
        return 1
    overrides = {"scenic": args.scenic, "food": args.food,
                 "hotel": args.hotel, "leisure": args.leisure}
    for cat, value in overrides.items():
        if value:
            PLAN[cat]["limit"] = value

    # 现有资源名称（用于去重）
    existing_names: set[str] = set()
    try:
        import scripts.seed_data as sd
        for lst in (sd.SCENIC, sd.FOOD, sd.HOTEL, sd.LEISURE):
            existing_names.update(r["name"] for r in lst)
    except Exception:  # noqa: BLE001
        pass

    all_records: list[dict] = []
    for category in ("scenic", "food", "hotel", "leisure"):
        cfg = PLAN[category]
        raw = fetch_category(category)
        mine: list[dict] = []
        for poi in raw:
            rec = build_record(poi, category)
            if rec and rec["rating"] >= cfg["min_rating"]:
                mine.append(rec)
        mine.sort(key=lambda r: (-r["rating"], -len(r["name"])))
        all_records.extend(mine)

    accepted, skipped = dedupe(all_records, existing_names)

    # 每类目截断到目标条数
    final: list[dict] = []
    by_cat: dict[str, list[dict]] = {}
    for rec in accepted:
        by_cat.setdefault(rec["category"], []).append(rec)
    for cat in ("scenic", "food", "hotel", "leisure"):
        final.extend(by_cat.get(cat, [])[:PLAN[cat]["limit"]])
    print("[result]", {cat: len(by_cat.get(cat, [])) for cat in ("scenic", "food", "hotel", "leisure")},
          "→ 保留", len(final), "条")

    write_outputs(final, skipped)
    if args.apply:
        apply_to_db(final)
    else:
        print("[dry-run] 未写库；确认 review CSV 后可加 --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
