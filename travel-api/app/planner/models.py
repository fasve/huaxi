"""planner 数据结构与默认模式配置（对应方案 4.2 / 4.3 / 11.2）。"""
from dataclasses import dataclass, field


# ---------------- 模式权重向量（4.2，和为 1.0；diversity 为乘法惩罚不入静态权重） ----------

DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "leisure": {
        "quality": 0.25, "popularity": 0.10, "landmark": 0.05,
        "cost_efficiency": 0.20, "budget_fit": 0.20, "time_density": 0.05,
        "rest_comfort": 0.15, "local_flavor": 0.00,
    },
    "blitz": {
        "quality": 0.10, "popularity": 0.15, "landmark": 0.10,
        "cost_efficiency": 0.30, "budget_fit": 0.15, "time_density": 0.20,
        "rest_comfort": 0.00, "local_flavor": 0.00,
    },
    "premium": {
        "quality": 0.35, "popularity": 0.15, "landmark": 0.10,
        "cost_efficiency": 0.05, "budget_fit": 0.15, "time_density": 0.10,
        "rest_comfort": 0.00, "local_flavor": 0.10,
    },
    "checkin": {
        "quality": 0.15, "popularity": 0.30, "landmark": 0.30,
        "cost_efficiency": 0.10, "budget_fit": 0.10, "time_density": 0.10,
        "rest_comfort": 0.00, "local_flavor": 0.00,
    },
}


# ---------------- 硬约束（4.3） ----------

DEFAULT_HARD_RULES: dict[str, dict] = {
    "leisure": {
        "daily_poi_min": 2, "daily_poi_max": 3,       # 单日景点/休闲 POI 数
        "daily_play_hours_max": 6,                    # 单日最大游玩时长
        "budget_utilization_min": 0.60,               # 预算利用率
        "budget_elasticity_min": 0.90, "budget_elasticity_max": 1.10,
        "hotel_price_level_min": 0,                   # 酒店档次下限
        "hotel_price_level_max": 5,
        "price_level_cap": 4,                         # 候选价格档上限
        "require_dinner": True, "require_lunch": True,
        "evening_slot": "rest",                       # none/rest/dine_night/landmark_night
        "landmark_must_cover_topn": 0,
        "day_start": "09:30", "day_end": "21:00",     # 时间窗（含晚间）
        "lunch_window": ["11:30", "13:30"],
        "mu_travel_cost": 0.10,                       # 通勤代价系数 μ
        "speed_kmh": 22.0,                            # 打车/公交混合速度假设
        "transit_desc": "宽松",
    },
    "blitz": {
        "daily_poi_min": 4, "daily_poi_max": 6,
        "daily_play_hours_max": 14,
        "budget_utilization_min": 0.85,
        "budget_elasticity_min": 0.95, "budget_elasticity_max": 1.00,  # 禁止超支
        "hotel_price_level_min": 0,
        "hotel_price_level_max": 2,                   # 可推青旅/经济
        "price_level_cap": 3,
        "require_dinner": True, "require_lunch": True,
        "evening_slot": "none",                       # 夜游可省
        "landmark_must_cover_topn": 0,
        "day_start": "08:00", "day_end": "22:00",
        "lunch_window": ["11:30", "13:30"],
        "mu_travel_cost": 0.05,
        "speed_kmh": 20.0,                            # 高强度公交+步行
        "transit_desc": "高（允许公交换乘）",
    },
    "premium": {
        "daily_poi_min": 2, "daily_poi_max": 3,
        "daily_play_hours_max": 6,
        "budget_utilization_min": 0.90,
        "budget_elasticity_min": 0.95, "budget_elasticity_max": 1.20,  # 允许上浮提示
        "hotel_price_level_min": 3,
        "hotel_price_level_max": 5,
        "price_level_cap": 5,
        "require_dinner": True, "require_lunch": True,
        "evening_slot": "dine_night",                 # 强制晚间（观景餐厅/温泉）
        "landmark_must_cover_topn": 0,
        "day_start": "10:00", "day_end": "22:00",
        "lunch_window": ["12:00", "14:00"],
        "budget_fit_threshold": 0.5,                  # budget_fit ρ 阈值放宽（4.4）
        "mu_travel_cost": 0.08,
        "speed_kmh": 30.0,                            # ≤2 段打车
        "transit_desc": "≤2 段打车",
    },
    "checkin": {
        "daily_poi_min": 3, "daily_poi_max": 5,
        "daily_play_hours_max": 9,
        "budget_utilization_min": 0.75,
        "budget_elasticity_min": 0.90, "budget_elasticity_max": 1.10,
        "hotel_price_level_min": 2,
        "hotel_price_level_max": 5,
        "price_level_cap": 4,
        "require_dinner": True, "require_lunch": True,
        "require_snack": True,                         # 每日必含 1 次小吃探店
        "evening_slot": "landmark_night",              # 强制（夜市/灯光打卡）
        "landmark_must_cover_topn": 3,                 # Top 地标必入程
        "day_start": "09:00", "day_end": "21:30",
        "lunch_window": ["11:30", "13:30"],
        "mu_travel_cost": 0.12,
        "speed_kmh": 22.0,
        "transit_desc": "中（允许步行串联古镇）",
    },
}

MODE_NAMES = {
    "leisure": "休闲游", "blitz": "特种兵游",
    "premium": "高端游", "checkin": "打卡游",
}

MODE_DESCRIPTIONS = {
    "leisure": "节奏舒缓，优选可坐可歇的亲水公园与古镇，午后留白，晚上泡汤早休——把假期真正过成假期。",
    "blitz": "单位花费与单位时间的满意度拉满：免费高分景点全串起来，快餐粉面快速补给，一天当两天用。",
    "premium": "只选品质最高的那一批：高分景区、老字号黔菜、高端酒店与温泉，节奏慢但处处讲究。",
    "checkin": "必去地标一个不落：青岩古镇、夜郎谷出大片，夜市灯光收尾，朋友圈素材一条龙。",
}

# 槽位模板：morning→lunch→afternoon→dinner→evening（5.4）
SLOT_TEMPLATE = ["morning", "lunch", "afternoon", "dinner", "evening"]

SLOT_NAMES = {
    "morning": "上午", "lunch": "午餐", "afternoon": "下午",
    "dinner": "晚餐", "evening": "晚间", "hotel": "住宿",
}


# ---------------- planner 数据结构 ----------

@dataclass
class PlannerPoi:
    """参与装箱的 POI 快照（与 ORM 解耦，纯数据）。"""
    id: int
    name: str
    category: str            # scenic/food/hotel/leisure（study 已在服务层并入 scenic）
    sub_type: str = ""
    longitude: float = 0.0
    latitude: float = 0.0
    suggest_duration_min: int = 60
    ticket_price: float = 0.0
    price_level: int = 1
    rating: float = 4.0
    review_count: int = 0
    hot_score: float = 0.5
    quality_score: float = 0.5
    is_landmark: bool = False
    photospot_weight: float = 0.0   # photospot 标签相关度
    indoor: bool = False
    physical_level: int = 2         # 体力消耗 1-5
    is_time_honored: bool = False
    cuisine: str = ""
    meal_period: str = "午,晚"
    avg_price: float = 30.0
    grade: str = ""                 # 酒店档次
    night_open: bool = False        # 休闲场所夜间开放
    night_only: bool = False       # 仅夜间营业（如夜市），只能进晚间槽
    play_type: str = ""
    pref_tags: set[str] = field(default_factory=set)   # 命中的偏好标签
    images: list[str] = field(default_factory=list)    # 封面图（相对 /static/poi/...）
    static: dict = field(default_factory=dict)         # 9 维静态评分（scoring 计算后写入）

    @property
    def cost(self) -> float:
        """参与预算扣减的费用口径：门票/人均/间夜。"""
        if self.category == "hotel":
            return self.avg_price if self.avg_price else self.ticket_price
        return self.ticket_price


@dataclass(eq=False)
class SlotItem:
    """一个已填的行程槽位（eq=False：按对象身份比较，避免排序时误删）。"""
    slot: str
    poi: PlannerPoi | None
    start_time: str = ""
    duration_min: int = 0
    cost: float = 0.0
    travel_from_prev_min: int = 0    # 与前一 POI 的通勤分钟（估算）
    estimated: bool = True           # 通勤为估算值
    # ---- 预设主题路线保底站点（方案 5.8）----
    preset_seq: int = 0              # >0 表示游学保底站，携带站点序号
    preset_meta: dict = field(default_factory=dict)   # 逐站讲解 / 任务卡 / date_gate 结论
    travel_override_min: int | None = None  # 校内实测步行衔接，覆盖 Haversine 估算
    locked: bool = False             # 免于 2-opt 重排、预算降级与时间窗置空


@dataclass
class DayPlan:
    day_index: int
    theme: str = ""
    day_budget: float = 0.0
    day_cost: float = 0.0
    items: list[SlotItem] = field(default_factory=list)
    underfilled: bool = False

    @property
    def play_minutes(self) -> int:
        """游玩总时长（不含用餐/住宿）。"""
        return sum(
            it.duration_min for it in self.items
            if it.poi and it.slot in ("morning", "afternoon", "evening")
        )


@dataclass
class TripRequest:
    """生成请求。"""
    days: int = 2
    budget: float = 1000.0
    mode: str = "leisure"
    preferences: list[str] = field(default_factory=list)
    party_type: str = ""
    seed: int = 0


@dataclass
class TripPlan:
    """生成结果：天数计划 + 全局费用 + 松弛日志。"""
    mode: str
    days: int
    budget: float
    days_plan: list[DayPlan] = field(default_factory=list)
    hotel: PlannerPoi | None = None
    hotel_nights: int = 0
    hotel_total_cost: float = 0.0
    total_cost: float = 0.0
    budget_usage: float = 0.0
    score: float = 0.0
    relax_log: list[dict] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
