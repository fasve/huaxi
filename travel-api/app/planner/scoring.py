"""Stage2 权重打分：9 维静态评分 + 动态预算贴合 + 多样性/通勤惩罚（方案 4.4）。"""
import math

from app.planner.models import PlannerPoi

OVERLAP_LAMBDA = 0.15   # 多样性惩罚系数 λ（方案 4.4，统一作用于四模式）

# 通勤估算参数（方案 8.1 降级口径：Haversine × 绕行系数 1.4 ÷ 模式速度）
DETOUR_FACTOR = 1.4


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """球面直线距离（km）。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def estimate_travel_min(a: PlannerPoi | None, b: PlannerPoi, speed_kmh: float) -> int:
    """通勤分钟估算：直线距离 × 绕行系数 ÷ 模式速度假设。"""
    if a is None:
        return 0
    km = haversine_km(a.longitude, a.latitude, b.longitude, b.latitude)
    return max(3, round(km * DETOUR_FACTOR / speed_kmh * 60))


def _rest_comfort(p: PlannerPoi) -> float:
    """休憩舒适度：有座/室内/温泉/住宿类得分高；夜游徒步类低。"""
    if p.category == "hotel":
        return 0.9
    if p.category == "food":
        return 0.65
    if p.category == "leisure":
        if p.indoor or "温泉" in p.play_type:
            return 0.8
        return 0.4
    # scenic
    if p.indoor:
        return 0.6
    return max(0.1, 0.55 - 0.1 * p.physical_level)


def _local_flavor(p: PlannerPoi) -> float:
    """在地风味/深度：老字号、本地菜系、非遗、乡镇小众属性。"""
    score = 0.3
    if p.category == "food":
        if p.is_time_honored:
            return 1.0
        if p.cuisine in ("黔菜", "贵州菜", "苗家菜", "侗家菜"):
            score = max(score, 0.7)
    if p.sub_type in ("古镇", "非遗", "民族村寨", "田园风光", "艺术地貌"):
        score = max(score, 0.6)
    if p.category == "food" and not p.is_time_honored:
        score = max(score, 0.4)
    return score


def static_scores(pois: list[PlannerPoi]) -> None:
    """计算每个 POI 的 7 个静态维度分（budget_fit/diversity 生成期动态算）。

    结果写入 poi.static 字典；time_density 在候选池内 min-max 归一。
    """
    # time_density 原始值：单位时间满意度 = rating / 时长
    raw_td = [p.rating / max(p.suggest_duration_min, 30) for p in pois]
    td_min, td_max = min(raw_td), max(raw_td)
    td_range = (td_max - td_min) or 1.0

    for p, td in zip(pois, raw_td):
        p.static = {  # type: ignore[attr-defined]
            "quality": p.quality_score,
            "popularity": p.hot_score,
            "landmark": (0.7 if p.is_landmark else 0.0) + 0.3 * p.photospot_weight,
            "cost_efficiency": (1 - p.price_level / 5) * (p.rating / 5),
            "time_density": (td - td_min) / td_range,
            "rest_comfort": _rest_comfort(p),
            "local_flavor": _local_flavor(p),
        }


def score_poi(
    p: PlannerPoi,
    weights: dict[str, float],
    mu: float,
    speed_kmh: float,
    day_remaining_budget: float,
    prev: PlannerPoi | None,
    day_selected_subtypes: set[str],
    budget_fit_threshold: float = 0.3,
    jitter: float = 0.0,
) -> float:
    """综合打分 S(poi|mode, day_ctx)，见方案 4.4。

    S = Σ w_k·f_k(静态) + w_budget_fit·budget_fit
        − λ·overlap_penalty − μ·travel_cost + jitter(换一批扰动)
    """
    static: dict[str, float] = p.static  # type: ignore[attr-defined]
    s = sum(w * static.get(k, 0.0) for k, w in weights.items() if k != "budget_fit")
    s += weights.get("budget_fit", 0.0) * budget_fit(
        p.cost, day_remaining_budget, budget_fit_threshold
    )
    # 多样性惩罚：sub_type 与当日已选重复即罚
    if p.sub_type and p.sub_type in day_selected_subtypes:
        s -= OVERLAP_LAMBDA
    # 通勤代价：分钟数归一到 0~1（120min 封顶）
    travel_min = estimate_travel_min(prev, p, speed_kmh)
    s -= mu * min(1.0, travel_min / 120.0)
    return s + jitter


def budget_fit(cost: float, remaining: float, threshold: float = 0.3) -> float:
    """预算贴合度：ρ = cost/R；吃满当日剩余预算记 0 分（premium 阈值放宽至 0.5）。"""
    if remaining <= 0:
        return 0.0
    rho = cost / remaining
    return 1.0 - min(1.0, max(0.0, (rho - threshold) / (1 - threshold)))


def score_hotel(p: PlannerPoi) -> float:
    """酒店选点：品质与评分优先。"""
    return 0.6 * p.quality_score + 0.4 * (p.rating / 5.0)
