"""专属知识检索：把库里的 POI / 模式配置 / FAQ 变成「知识卡」，按问题相关度取 top-k。

为什么不用向量库：一期知识规模只有 80 条 POI + 4 套模式 + 十余条 FAQ，
关键词（中文二元组 + 标签 + 意图）检索已经够用，且零额外依赖、零外部调用；
后续知识量变大时再在本模块内加 embedding，不影响调用方。

对外只暴露：
- `search(db, query, top_k)` → (卡片列表, 命中的意图)
- `refs_from_cards(cards)` → 接口返回给前端的引用来源
- `invalidate()` → 管理端改完 POI/FAQ 后主动失效缓存
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import (
    Poi, PoiExtFood, PoiExtHotel, PoiExtLeisure, PoiExtScenic, PoiTag,
    QaKnowledge, Tag, TripModeConfig,
)
from app.services.cache import TTLCache

CATEGORY_CN = {
    "scenic": "景点", "food": "美食", "hotel": "住宿",
    "leisure": "休闲", "study": "游学",
}

# 与具体 POI 无关的高频词：参与检索只会放大噪音，直接当停用词
_STOPWORDS = {
    "花溪", "花溪区", "贵阳市", "贵阳", "贵州", "请问", "什么", "怎么", "怎样",
    "可以", "能否", "帮我", "我们", "你们", "一下", "推荐", "介绍", "一些",
    "有没有", "哪里", "哪些", "这个", "那个", "以及", "或者", "还有", "的话",
    # 通用疑问二元组（否则会误中「有什么避坑提醒」这类 FAQ 标题）
    "有什", "有哪", "去哪", "哪儿", "哪个", "如何", "是否", "值得", "需要",
    "玩的", "么好", "么必", "点的", "的吗",
}

# 意图 → 关键词（用于在没有直接命中时按类别兜底）
_INTENTS: dict[str, tuple[str, ...]] = {
    "scenic": ("景点", "风景", "好玩", "打卡", "拍照", "古镇", "公园", "湿地",
               "山", "湖", "瀑布", "峡谷", "夜郎谷", "青岩", "花溪公园", "游玩"),
    "food": ("吃", "美食", "餐厅", "小吃", "早餐", "午餐", "晚餐", "夜宵",
             "牛肉粉", "酸汤", "丝娃娃", "烙锅", "招牌", "人均"),
    "hotel": ("住", "酒店", "民宿", "住宿", "宾馆", "客栈", "过夜"),
    "leisure": ("休闲", "温泉", "夜生活", "骑行", "游船", "亲子", "放松", "咖啡"),
    "transport": ("怎么去", "交通", "公交", "地铁", "打车", "自驾", "停车",
                  "机场", "高铁", "火车站", "多远", "车程", "路线怎么走"),
    "plan": ("模式", "行程", "规划", "安排", "几天", "预算", "路线", "定制",
             "半日", "一日", "两日", "三日", "特种兵", "休闲模式", "高端", "打卡模式"),
    "weather": ("天气", "下雨", "气温", "温度", "穿衣", "带伞", "冷不冷", "热不热"),
}

# 意图 → 知识卡类别偏好（检索兜底用）
_INTENT_CATEGORY = {"scenic": "scenic", "food": "food", "hotel": "hotel", "leisure": "leisure"}

_cards_cache = TTLCache(ttl_seconds=120, max_items=8)


def invalidate() -> None:
    """知识卡缓存失效（管理端修改 POI/FAQ 后调用）。"""
    _cards_cache.invalidate_prefix("qa_cards")


def _money(v: float | int | None) -> str:
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return "未知"
    return f"{n:.0f} 元"


def _open_text(open_time: list) -> str:
    if not open_time:
        return "未知"
    try:
        return " / ".join(f"{a}-{b}" for a, b in open_time)
    except (TypeError, ValueError):
        return "未知"


def _poi_card(p: Poi, ext: object | None, tag_names: list[str]) -> dict | None:
    """POI 主表 + 扩展 → 一条知识卡（text 即注入 prompt 的资料原文）。

    `review_count == 0` 视为「高德批量导入、部分字段未人工核实」的数据：
    门票/预约/房价这类不能确认的事实要标注"未标注/估算"，不能直接说"免费"。
    """
    unverified = (p.review_count or 0) <= 0
    cat_cn = CATEGORY_CN.get(p.category, p.category)
    parts = [
        f"{p.name}（{cat_cn}{('·' + p.sub_type) if p.sub_type else ''}）",
        f"地址：{p.address or '花溪区'}",
        f"开放：{_open_text(p.open_time)}",
        f"建议游玩：{p.suggest_duration_min} 分钟",
    ]
    summary = f"{cat_cn}·评分 {p.rating:.1f}"
    if p.category == "food":
        e = ext  # PoiExtFood
        if e is not None:
            sig = "、".join(e.signature or []) or "—"
            parts.append(f"人均：{_money(e.avg_price)}；招牌菜：{sig}；菜系：{e.cuisine}")
            summary = f"美食·人均 {_money(e.avg_price)}"
    elif p.category == "hotel":
        e = ext  # PoiExtHotel
        if e is not None:
            price_tag = "（估算，以酒店实际报价为准）" if unverified else ""
            parts.append(
                f"档次：{e.grade}；星级：{e.star or '—'}；参考价：{_money(e.price_min)}/晚起{price_tag}；"
                f"含早：{'是' if e.with_breakfast else '否'}"
            )
            summary = f"住宿·{e.grade}·{_money(e.price_min)}/晚起"
    elif p.category == "leisure":
        e = ext  # PoiExtLeisure
        if e is not None:
            parts.append(
                f"玩法：{e.play_type or '—'}；夜间开放：{'是' if e.night_open else '否'}；"
                f"室内：{'是' if e.indoor else '否'}"
            )
            summary = f"休闲·{e.play_type or '体验'}"
    elif p.category == "scenic":
        e = ext  # PoiExtScenic
        if e is not None:
            booking = "未收录（以景区公告为准）" if unverified else ("是" if e.need_reservation else "否")
            parts.append(
                f"等级：{e.level or '未标注'}；需预约：{booking}；"
                f"最佳季节：{e.best_season or '全季'}；室内：{'是' if e.indoor else '否'}；"
                f"体力消耗：{e.physical_level}/5"
            )
            summary = f"景点·{e.level or cat_cn}·评分 {p.rating:.1f}"
    if p.category != "hotel":
        if p.ticket_price > 0:
            price_text = _money(p.ticket_price)
        elif unverified:
            price_text = "未标注（以景区公示为准）"
        else:
            price_text = "免费"
        parts.append(f"门票/参考价：{price_text}")
    if tag_names:
        parts.append(f"标签：{'/'.join(tag_names)}")
    review_note = f"（{p.review_count} 条评价）" if (p.review_count or 0) > 0 else ""
    parts.append(f"评分：{p.rating:.1f}{review_note}")
    if unverified:
        parts.append("数据来源：高德开放平台（字段未人工核实）")
    return dict(
        kind="poi", ref_id=f"P{p.id}", poi_id=p.id, name=p.name,
        summary=summary, text="｜".join(parts),
        category=p.category, tags=list(tag_names),
        hot=p.hot_score or 0.0,
    )


def _mode_cards(db: Session) -> list[dict]:
    out: list[dict] = []
    for cfg in db.query(TripModeConfig).all():
        rules = cfg.hard_rules or {}
        desc = cfg.description or ""
        text = (
            f"【{cfg.mode_name}（{cfg.mode}）】{desc}｜"
            f"每日点位：{rules.get('daily_poi_min', '?')}~{rules.get('daily_poi_max', '?')} 个；"
            f"每日游玩上限：{rules.get('daily_play_hours_max', '?')} 小时；"
            f"住宿档次下限：{rules.get('hotel_price_level_min', '?')}；"
            f"交通假设：{rules.get('transit_desc', '—')}"
        )
        out.append(dict(
            kind="mode", ref_id=f"M{cfg.mode}", poi_id=None,
            name=f"{cfg.mode_name}模式", summary="行程模式说明",
            text=text, category="mode", tags=["模式", cfg.mode_name],
            hot=0.0,
        ))
    return out


def _faq_cards(db: Session) -> list[dict]:
    out: list[dict] = []
    for k in db.query(QaKnowledge).filter(QaKnowledge.enabled.is_(True)).all():
        tags = list(k.tags or [])
        out.append(dict(
            kind="faq", ref_id=f"K{k.id}", poi_id=None,
            name=k.title, summary=(k.content or "")[:40],
            text=f"{k.title}：{k.content}", category=k.category,
            tags=[k.title, *tags], hot=0.0,
        ))
    return out


def _build_cards(db: Session) -> list[dict]:
    """全量构建知识卡（80 条 POI 量级，毫秒级）。"""
    tag_rows = (
        db.query(PoiTag.poi_id, Tag.name)
        .join(Tag, Tag.id == PoiTag.tag_id).all()
    )
    tags_by_poi: dict[int, list[str]] = {}
    for poi_id, name in tag_rows:
        tags_by_poi.setdefault(poi_id, []).append(name)

    cards: list[dict] = []
    for p in db.query(Poi).filter(Poi.visitable.is_(True)).all():
        ext = None
        if p.category == "scenic":
            ext = db.get(PoiExtScenic, p.id)
        elif p.category == "food":
            ext = db.get(PoiExtFood, p.id)
        elif p.category == "hotel":
            ext = db.get(PoiExtHotel, p.id)
        elif p.category == "leisure":
            ext = db.get(PoiExtLeisure, p.id)
        card = _poi_card(p, ext, tags_by_poi.get(p.id, []))
        if card:
            cards.append(card)
    cards.extend(_mode_cards(db))
    cards.extend(_faq_cards(db))
    return cards


def _get_cards(db: Session) -> list[dict]:
    hit = _cards_cache.get("qa_cards")
    if hit is not None:
        return hit
    cards = _build_cards(db)
    _cards_cache.set("qa_cards", cards)
    return cards


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


def _tokens(query: str) -> set[str]:
    """中文按二元组切分 + 英文/数字整词；过滤停用词。"""
    q = _normalize(query)
    tokens: set[str] = set()
    # 英文/数字词
    for w in re.findall(r"[a-z0-9]{2,}", q):
        tokens.add(w)
    # 中文二元组
    for i in range(len(q) - 1):
        gram = q[i:i + 2]
        if gram not in _STOPWORDS:
            tokens.add(gram)
    if len(q) <= 4 and q and q not in _STOPWORDS:
        tokens.add(q)
    return tokens


def _detect_intents(query: str) -> set[str]:
    q = query or ""
    hits: set[str] = set()
    for intent, words in _INTENTS.items():
        if any(w in q for w in words):
            hits.add(intent)
    return hits


def _score_card(card: dict, tokens: set[str], intents: set[str], raw_query: str) -> float:
    score = 0.0
    name = card["name"]
    text = card["text"]
    tags = " ".join(card.get("tags") or [])

    # 名称直接命中（"青岩古镇门票多少" → 该 POI 必进）
    if name and (name in raw_query or (raw_query in name and len(raw_query) >= 2)):
        score += 12.0
    for tok in tokens:
        if tok in name:
            score += 3.0
        elif tok in tags:
            score += 2.0
        elif tok in text:
            score += 0.6

    # 意图加成
    cat = card.get("category")
    if cat in _INTENT_CATEGORY:
        if _INTENT_CATEGORY[cat] in intents:
            score += 2.5
    if card["kind"] == "mode" and "plan" in intents:
        score += 2.5
    if card["kind"] == "faq":
        faq_tags = " ".join(card.get("tags") or [])
        if "transport" in intents and "交通" in faq_tags:
            score += 2.5
        if "weather" in intents and "天气" in faq_tags:
            score += 2.5
        if "plan" in intents and "行程" in faq_tags:
            score += 1.5

    # 同分时按热度/评分稳定排序
    return score + float(card.get("hot") or 0) * 0.5


def search(db: Session, query: str, top_k: int = 5) -> tuple[list[dict], set[str]]:
    """按问题检索知识卡：返回 (top_k 卡片, 命中意图集合)。"""
    cards = _get_cards(db)
    intents = _detect_intents(query)
    tokens = _tokens(query)
    scored = [(_score_card(c, tokens, intents, query), c) for c in cards]
    scored.sort(key=lambda x: x[0], reverse=True)
    # 取分：FAQ 最多 2 条，避免小模型拿知识库条目挤掉真正的资源卡
    picked: list[dict] = []
    faq_count = 0
    for score, card in scored:
        if score <= 0.5:
            continue
        if card["kind"] == "faq":
            if faq_count >= 2:
                continue
            faq_count += 1
        picked.append(card)
        if len(picked) >= top_k:
            break
    # 意图兜底：什么都没匹配上时，按意图给该类别最热的卡片，避免「检索为空」直接拒答
    if not picked and intents:
        for cat in ("scenic", "food", "hotel", "leisure"):
            if cat in intents:
                same = [c for c in cards if c.get("category") == cat]
                same.sort(key=lambda c: float(c.get("hot") or 0), reverse=True)
                picked = same[:top_k]
                break
    if not picked and "plan" in intents:
        picked = [c for c in cards if c["kind"] == "mode"][:top_k]

    # 意图补位：问「吃什么」时即使有弱匹配的别的卡，也必须带上美食卡；
    # 但「模式/行程」类问题例外（那类问题的答案就是模式说明，不该被资源卡挤掉）。
    intent_cats = {
        _INTENT_CATEGORY[i] for i in intents
        if i in _INTENT_CATEGORY and not (i != "plan" and "plan" in intents)
    }
    if intent_cats and top_k >= 2:
        have = {c.get("category") for c in picked}
        extras: list[dict] = []
        for cat in intent_cats - have:
            same = [c for c in cards if c.get("category") == cat]
            same.sort(key=lambda c: float(c.get("hot") or 0), reverse=True)
            extras.extend(same[:2])
        if extras:
            picked = extras[:2] + [c for c in picked if c not in extras]
            picked = picked[:top_k]
    return picked, intents


def refs_from_cards(cards: list[dict]) -> list[dict]:
    """知识卡 → 前端引用来源（去重、精简字段）。"""
    seen: set[str] = set()
    refs: list[dict] = []
    for c in cards:
        if c["ref_id"] in seen:
            continue
        seen.add(c["ref_id"])
        refs.append(dict(
            kind=c["kind"], ref_id=c["ref_id"], name=c["name"],
            summary=c.get("summary", ""), poi_id=c.get("poi_id"),
        ))
    return refs
