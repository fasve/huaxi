"""个性化权重：维度元数据、归一化、预设模板、节奏微调。

对应设计方案 4.2（权重向量）与 4.4（加权打分）。本模块把"用户可调的个人偏好"
翻译成引擎可用的权重向量：

- 权重维度共 8 项（含动态项 budget_fit），与 trip_mode_config.weights 的键一致。
- 用户在前端拖动滑块给出 0~100 的"关注度"，normalize_weights 归一化为和为 1 的向量。
- 未调整时与所选模式的默认权重完全一致；调整后仅改变"关注度分配"，不改变维度定义，
  因此引擎（scoring.score_poi）无需改动即可生效。
- 节奏微调（每日点数上限 / 游玩小时上限 / 晚间偏好）改写 hard_rules 副本，
  只影响本次生成，不污染数据库里的模式配置。
"""
from __future__ import annotations

# ---------- 权重维度元数据（前端滑块由该字典驱动） ----------

WEIGHT_DIMENSIONS: list[dict] = [
    {
        "key": "quality", "label": "品质口碑", "icon": "⭐",
        "desc": "评分、点评与体验质量",
        "hint": "拉高 → 只挑评价好的地方，行程更稳但选择变少",
    },
    {
        "key": "popularity", "label": "人气热度", "icon": "🔥",
        "desc": "网络热度与话题性",
        "hint": "拉高 → 玩法热门热闹，避开冷门",
    },
    {
        "key": "landmark", "label": "地标打卡", "icon": "📍",
        "desc": "必去地标与出片点位",
        "hint": "拉高 → 青岩古镇这类地标优先入程",
    },
    {
        "key": "cost_efficiency", "label": "性价比", "icon": "💰",
        "desc": "单位花费换来的满意度",
        "hint": "拉高 → 优先免费、高性价比点位",
    },
    {
        "key": "budget_fit", "label": "预算贴合", "icon": "🧮",
        "desc": "花费与剩余预算的匹配度",
        "hint": "拉高 → 更贴着每日预算花，不轻易超支",
    },
    {
        "key": "time_density", "label": "时间效率", "icon": "⏱",
        "desc": "单位时间能获得的体验密度",
        "hint": "拉高 → 少排长线景点，多排短平快",
    },
    {
        "key": "rest_comfort", "label": "舒适休憩", "icon": "🛋",
        "desc": "可坐可歇、室内、温泉类体验",
        "hint": "拉高 → 偏泡汤、亲水公园、慢节奏",
    },
    {
        "key": "local_flavor", "label": "本地风土", "icon": "🍜",
        "desc": "老字号、黔菜、非遗与在地体验",
        "hint": "拉高 → 更偏在地美食与民俗",
    },
]

WEIGHT_KEYS: tuple[str, ...] = tuple(d["key"] for d in WEIGHT_DIMENSIONS)

DIMENSION_MAP: dict[str, dict] = {d["key"]: d for d in WEIGHT_DIMENSIONS}

# ---------- 晚间偏好（对应 hard_rules.evening_slot） ----------

EVENING_PREFERENCES: list[dict] = [
    {
        "key": "relax", "label": "早点休息", "icon": "🌙",
        "evening_slot": "rest", "day_end": "19:30",
        "desc": "晚间只安排泡汤/室内轻休闲，21 点前收工",
    },
    {
        "key": "night_scene", "label": "夜游打卡", "icon": "🌃",
        "evening_slot": "landmark_night", "day_end": "21:30",
        "desc": "夜市、灯光、夜景一条龙，收尾不早于 21:30",
    },
    {
        "key": "fine_dining", "label": "观景晚宴", "icon": "🍷",
        "evening_slot": "dine_night", "day_end": "22:00",
        "desc": "晚餐延到 18:30，锁定观景餐厅/温泉",
    },
]

# ---------- 权重预设模板（前端一键套用） ----------

WEIGHT_PRESETS: list[dict] = [
    {
        "key": "balanced", "label": "均衡默认", "icon": "⚖️",
        "desc": "沿用模式默认权重，不偏不倚",
        "weights": {},
    },
    {
        "key": "value", "label": "省钱优先", "icon": "🪙",
        "desc": "性价比 + 预算贴合拉满，避开高消费点位",
        "weights": {
            "quality": 18, "popularity": 8, "landmark": 8, "cost_efficiency": 32,
            "budget_fit": 26, "time_density": 14, "rest_comfort": 6, "local_flavor": 4,
        },
    },
    {
        "key": "quality_first", "label": "品质优先", "icon": "💎",
        "desc": "口碑与品质拉满，慢一点但体验更稳",
        "weights": {
            "quality": 34, "popularity": 8, "landmark": 8, "cost_efficiency": 10,
            "budget_fit": 12, "time_density": 6, "rest_comfort": 16, "local_flavor": 6,
        },
    },
    {
        "key": "checkin_king", "label": "打卡刷屏", "icon": "📸",
        "desc": "地标与热度拉满，社交平台素材优先",
        "weights": {
            "quality": 12, "popularity": 30, "landmark": 34, "cost_efficiency": 6,
            "budget_fit": 6, "time_density": 10, "rest_comfort": 2, "local_flavor": 0,
        },
    },
    {
        "key": "deep_local", "label": "深度在地", "icon": "🧺",
        "desc": "本地风土 + 舒适休憩，走慢一点吃透",
        "weights": {
            "quality": 20, "popularity": 4, "landmark": 10, "cost_efficiency": 12,
            "budget_fit": 10, "time_density": 6, "rest_comfort": 16, "local_flavor": 22,
        },
    },
    {
        "key": "family_fun", "label": "亲子悠闲", "icon": "🧸",
        "desc": "舒适休憩 + 口碑优先，节奏放缓",
        "weights": {
            "quality": 26, "popularity": 12, "landmark": 8, "cost_efficiency": 10,
            "budget_fit": 12, "time_density": 4, "rest_comfort": 22, "local_flavor": 6,
        },
    },
    {
        "key": "efficient", "label": "效率拉满", "icon": "⚡",
        "desc": "时间效率 + 性价比拉满，一天顶两天",
        "weights": {
            "quality": 12, "popularity": 12, "landmark": 12, "cost_efficiency": 24,
            "budget_fit": 14, "time_density": 24, "rest_comfort": 2, "local_flavor": 0,
        },
    },
]

# ---------- 权重归一化 ----------

# 滑块原始分上限（百分制）
SLIDER_MAX = 100


def slider_defaults(base_weights: dict[str, float]) -> dict[str, int]:
    """把模式默认权重（和为 1）转成前端滑块初值（0~100 整数）。"""
    out: dict[str, int] = {}
    for k in WEIGHT_KEYS:
        w = float(base_weights.get(k, 0.0) or 0.0)
        out[k] = int(round(max(0.0, min(1.0, w)) * SLIDER_MAX))
    return out


def normalize_weights(
    raw: dict[str, float] | None,
    base_weights: dict[str, float],
) -> dict[str, float]:
    """把 0~100 的关注度归一化为和为 1 的权重向量。

    - raw 为空或全 0 → 直接返回模式默认权重（完全等价于未做个性化）。
    - 只接受白名单维度，忽略非法键与负值。
    - 结果保留 4 位小数，末位做误差回补，保证 sum == 1。
    """
    base = {k: float(base_weights.get(k, 0.0) or 0.0) for k in WEIGHT_KEYS}
    if not raw:
        return base

    vals: dict[str, float] = {}
    for k in WEIGHT_KEYS:
        v = raw.get(k)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv < 0:
            continue
        vals[k] = min(SLIDER_MAX, fv)

    if not vals or sum(vals.values()) <= 0:
        return base

    total = sum(vals.values())
    out = {k: round(vals[k] / total, 4) for k in vals}
    # 误差回补到权重最大的维度，确保 sum == 1
    diff = round(1.0 - sum(out.values()), 4)
    if abs(diff) > 0:
        top = max(out, key=lambda k: out[k])
        out[top] = round(out[top] + diff, 4)
    return out


def weight_profile(weights: dict[str, float]) -> list[dict]:
    """权重向量 → 前端可读的结构（含标签与占比百分比）。

    百分比采用最大余数法分配，保证合计精确为 100（避免逐项四舍五入的累积偏差）。
    """
    total = sum(weights.values()) or 1.0
    raw = [(d, float(weights.get(d["key"], 0.0) or 0.0) / total * 100) for d in WEIGHT_DIMENSIONS]
    floors = [(d, int(v // 1)) for d, v in raw]
    remain = 100 - sum(f for _, f in floors)
    # 余数大的优先 +1 补齐
    order = sorted(range(len(raw)), key=lambda i: -(raw[i][1] - floors[i][1]))
    counts = {i: floors[i][1] for i in range(len(raw))}
    for k in range(remain):
        counts[order[k % len(order)]] += 1

    out = []
    for i, (d, v) in enumerate(raw):
        out.append({
            "key": d["key"], "label": d["label"], "icon": d["icon"],
            "desc": d["desc"], "hint": d["hint"],
            "weight": round(v / 100, 4),
            "percent": counts[i],
        })
    return out


def is_custom(weights: dict[str, float], base_weights: dict[str, float]) -> bool:
    """判断权重是否偏离模式默认（用于前端显示"已个性化"标记）。"""
    for k in WEIGHT_KEYS:
        if abs(float(weights.get(k, 0.0) or 0.0) - float(base_weights.get(k, 0.0) or 0.0)) > 0.005:
            return True
    return False


# ---------- 节奏微调（改写 hard_rules 副本） ----------

PACE_LIMITS = {
    "daily_poi_max": (2, 6),
    "play_hours_max": (3, 12),
}


def apply_pace(
    rules: dict,
    pace: dict | None,
    mode: str,
) -> dict:
    """按用户节奏偏好改写 hard_rules 副本，返回新 rules（不改原对象）。

    pace 字段：
      daily_poi_max  每日游玩点数量上限（2~6）
      play_hours_max 每日游玩时长上限（小时，3~12）
      evening         晚间偏好 key（relax / night_scene / fine_dining）
    """
    out = dict(rules)
    if not pace:
        # 未指定时按模式自身口径补齐晚间策略键，保持引擎行为一致
        out.setdefault("evening_slot", rules.get("evening_slot", "none"))
        return out

    if pace.get("daily_poi_max") is not None:
        lo, hi = PACE_LIMITS["daily_poi_max"]
        v = max(lo, min(hi, int(pace["daily_poi_max"])))
        out["daily_poi_max"] = v
        out["daily_poi_min"] = min(out.get("daily_poi_min", 2), v)

    if pace.get("play_hours_max") is not None:
        lo, hi = PACE_LIMITS["play_hours_max"]
        out["daily_play_hours_max"] = max(lo, min(hi, int(pace["play_hours_max"])))

    ev_key = pace.get("evening")
    if ev_key:
        for pref in EVENING_PREFERENCES:
            if pref["key"] != ev_key:
                continue
            out["evening_slot"] = pref["evening_slot"]
            out["day_end"] = pref["day_end"]
            if ev_key == "fine_dining":
                out["dinner_start"] = "18:30"
                out["dinner_duration_min"] = 90
            break

    # 引擎读取统一的晚餐参数（缺省沿用模式口径）
    out.setdefault("dinner_start", "18:30" if mode == "premium" else "18:00")
    out.setdefault("dinner_duration_min", 90 if mode == "premium" else 60)
    return out
