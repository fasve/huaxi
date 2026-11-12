"""Pydantic 请求/响应模型（接口契约，对应方案第 9 章）。"""
from pydantic import BaseModel, Field


# ---------- 认证 ----------

class WechatLoginIn(BaseModel):
    code: str = Field(..., description="wx.login 所得 code，交给服务端 code2session 换取 openid")
    device_id: str | None = Field(
        None, max_length=128,
        description="本地 dev mock 分支用的稳定设备标识；生产 code2session 忽略此字段",
    )


class AnonymousLoginIn(BaseModel):
    device_id: str | None = Field(
        None, max_length=128,
        description="PC 游客模式稳定设备标识；同一标识重登仍为同一游客身份",
    )


class TokenOut(BaseModel):
    """统一登录响应：标准 JWT + Bearer + 有效秒数（设计方案 7.5 滑动续期）。"""
    token: str
    token_type: str = "Bearer"
    expires_in: int = 0
    user_id: int
    is_new: bool
    device_id: str | None = None


class AdminLoginIn(BaseModel):
    username: str
    password: str


# ---------- POI ----------

class PoiOut(BaseModel):
    id: int
    poi_id: int = 0        # 与 id 同值，供管理端按 poi_id 操作
    name: str
    category: str
    sub_type: str
    address: str
    longitude: float
    latitude: float
    district: str
    open_time: list
    suggest_duration_min: int
    ticket_price: float
    price_level: int
    rating: float
    review_count: int
    hot_score: float
    quality_score: float
    visitable: bool
    images: list[str] = []
    image_meta: list[dict] = []   # 图片授权元信息，与 images 同序对应
    tags: list[str] = []
    ext: dict = {}


class PoiPageOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[PoiOut]


class ProviderKeyIn(BaseModel):
    """管理端配置图片源 API Key。"""
    name: str        # pixabay / pexels
    value: str = ""  # 传空串表示清除


class PoiWriteIn(BaseModel):
    """管理端新增/编辑。"""
    name: str
    category: str
    sub_type: str = ""
    address: str = ""
    longitude: float
    latitude: float
    suggest_duration_min: int
    ticket_price: float = 0
    price_level: int = 1
    rating: float = 4.0
    review_count: int = 0
    visitable: bool = True
    open_time: list = [["09:00", "18:00"]]
    images: list[str] = []
    image_meta: list[dict] = []
    ext: dict = {}
    tags: list[str] = []


# ---------- 行程 ----------

class TripGenerateIn(BaseModel):
    days: int = Field(2, ge=1, le=7)
    budget: float = Field(..., gt=0, description="全程总预算（元，含住宿）")
    mode: str = Field("leisure", pattern="^(leisure|blitz|premium|checkin)$")
    preferences: list[str] = []
    party_type: str = ""
    seed: int | None = Field(None, ge=0, description="同参数复现；换一批=seed+1")
    # ---- 个性化 ----
    weights: dict[str, float] = Field(
        default_factory=dict,
        description="8 维关注度（0~100 原始滑块值）；为空=沿用模式默认权重",
    )
    pace: dict = Field(
        default_factory=dict,
        description="节奏微调：daily_poi_max / play_hours_max / evening",
    )
    # ---- 开销偏好（整体开销由这些"小部件"驱动；可逐项修改） ----
    cost_prefs: dict = Field(
        default_factory=dict,
        description=(
            "开销偏好：hotel_tier(0~5 住宿档次下限) / "
            "transport(self_drive|taxi|transit|walk_bike 出行方式)"
        ),
    )
    # ---- 预设主题路线（G7 / 5.8 / 接口 #15）----
    preset_route_code: str | None = Field(
        None,
        description="预设主题路线 code（如 gzu_campus_study_tour）；命中时站点按 seq 预占第 1 天，剩余槽位按 mode 自由补全",
    )
    visit_date: str | None = Field(
        None, description="出行日期 YYYY-MM-DD；驱动 date_gate（开放日 / 花期 / 预约提醒）判定，缺省按今天",
    )
    include_addon: bool = Field(
        False, description="是否并入全天深度版加段站点（默认仅半日精华版）",
    )


class TripItemOut(BaseModel):
    slot: str
    slot_name: str
    poi_id: int | None
    name: str
    category: str
    start_time: str
    duration_min: int
    cost: float
    travel_from_prev_min: int = 0
    longitude: float | None = None
    latitude: float | None = None
    ticket_price: float = 0
    preset: dict = {}          # 游学保底站的逐站讲解 / 任务卡 / date_gate 结论；空=普通点位


class TripDayOut(BaseModel):
    day_index: int
    theme: str
    day_budget: float
    day_cost: float
    underfilled: bool
    items: list[TripItemOut]


class TripOut(BaseModel):
    trip_id: str
    mode: str
    mode_name: str
    days: int
    budget: float
    total_cost: float
    budget_usage: float
    score: float
    hotel: dict | None = None
    hotel_nights: int = 0
    days_plan: list[TripDayOut]
    relax_log: list[dict]
    explanation: list[str]
    custom_weights: dict = {}
    weight_profile: list[dict] = []
    is_personalized: bool = False
    pace_config: dict = {}
    preset_route: dict | None = None   # 本次行程注入的预设主题路线详情（含逐站讲解与 date_gate 结论）
    visit_date: str | None = None


# ---------- 个性化 ----------

class WeightPreviewIn(BaseModel):
    """权重预览：不落库，仅返回新权重下的候选排序。"""
    mode: str = Field("leisure", pattern="^(leisure|blitz|premium|checkin)$")
    weights: dict[str, float] = Field(default_factory=dict)
    preferences: list[str] = []
    pace: dict = Field(default_factory=dict)
    top_k: int = Field(12, ge=1, le=30)


class ReweightIn(BaseModel):
    """按新权重重排既有行程。"""
    weights: dict[str, float] = Field(default_factory=dict)
    pace: dict = Field(default_factory=dict)


class WeightMetaOut(BaseModel):
    """权重维度元数据（前端滑块由该结构驱动）。"""
    dimensions: list[dict]
    presets: list[dict]
    evening_preferences: list[dict]
    modes: dict[str, dict]


class RebalanceIn(BaseModel):
    day_index: int = Field(..., ge=1, le=7)
    action: str = Field(..., pattern="^(redrop|replace)$")
    slot: str | None = Field(None, description="replace 时必填：槽位名")
    poi_id: int | None = Field(None, description="replace 时可选：指定替换 POI；缺省自动换同类最优")


class SaveIn(BaseModel):
    pass  # 需登录后调用；P0 简化为绑定当前用户


# ---------- 模式 ----------

class ModeOut(BaseModel):
    mode: str
    mode_name: str
    description: str
    weights: dict
    hard_rules_brief: dict
    budget_hint: str


# ---------- 管理端 ----------

class ModeConfigOut(BaseModel):
    mode: str
    mode_name: str
    weights: dict
    hard_rules: dict
    slot_template: list
    description: str
    version: int


class ModeConfigIn(BaseModel):
    """模式配置更新：支持部分字段（不传即保持不变）。"""
    weights: dict | None = None
    hard_rules: dict | None = None
    description: str | None = None
    slot_template: list | None = None


class ImportResultOut(BaseModel):
    total: int
    success: int
    failed: list[dict] = []


class MessageOut(BaseModel):
    message: str


# ---------- P1/P2 扩展 ----------

class TripReplanIn(BaseModel):
    """T4 增量重算：只传需要变化的字段。"""
    days: int | None = Field(None, ge=1, le=10)
    budget: float | None = Field(None, gt=0)
    weights: dict | None = None
    pace: dict | None = None


class EnrichmentIn(BaseModel):
    force: bool = False


class SubscribeIn(BaseModel):
    visit_date: str | None = Field(None, max_length=10, description="出行日期 YYYY-MM-DD")
    openid: str | None = Field(None, max_length=64, description="仅管理端/联调使用；小程序由登录态解析")
    template_id: str | None = Field(None, max_length=64)


class TagSynonymIn(BaseModel):
    alias: str = Field(..., max_length=64)
    canonical_code: str = Field(..., max_length=64)
    note: str = ""


class TagMergeIn(BaseModel):
    from_code: str = Field(..., max_length=64)
    to_code: str = Field(..., max_length=64)


class PriceBandIn(BaseModel):
    name: str = ""
    min_price: float = Field(0, ge=0)
    max_price: float = Field(..., gt=0)
    price_level: int = Field(..., ge=1, le=5)
    enabled: bool = True
    description: str = ""


class PriceBandApplyIn(BaseModel):
    category: str | None = Field(None, description="限定类别；空=全部非酒店/餐饮")


class EffectiveRuleIn(BaseModel):
    poi_id: int
    kind: str = Field("price", pattern="^(price|hours)$")
    value: dict
    valid_from: str = ""
    valid_to: str = ""
    note: str = ""
    enabled: bool = True


class GrayReleaseIn(BaseModel):
    weights: dict
    hard_rules: dict | None = None
    slot_template: list | None = None
    description: str | None = None
    traffic_pct: int = Field(..., ge=1, le=100)
    note: str = ""

# ---------- 行程编辑（待计划篮子 / 移动 / 复制 / 替换） ----------

class ItemMoveIn(BaseModel):
    target_day: int = Field(..., ge=1, le=7, description="移动到的目标天（从 1 开始）")
    target_index: int | None = Field(None, ge=0, description="目标天内的插入位置；空=追加到末尾")


class ItemCopyIn(BaseModel):
    target_day: int = Field(..., ge=1, le=7, description="复制到的目标天")


class ItemReplaceIn(BaseModel):
    poi_id: int = Field(..., ge=1, description="替换后的点位 id")


class ItemAddIn(BaseModel):
    poi_id: int = Field(..., ge=1, description="要排入行程的点位 id")
    day: int = Field(1, ge=1, le=7, description="排入第几天")

class QaChatIn(BaseModel):
    """提问入参：匿名可用；conversation_id 为空则新建会话。"""
    message: str = Field(..., min_length=1, max_length=300, description="用户问题（≤300 字）")
    conversation_id: str | None = Field(None, max_length=24, description="会话 ID，缺省新建")
    trip_id: str | None = Field(None, max_length=16, description="可选：携带当前行程上下文")


class QaRefOut(BaseModel):
    """回答引用来源：前端渲染为可点的 POI/知识卡片。"""
    kind: str                     # poi / faq / mode / weather
    ref_id: str
    name: str
    summary: str = ""
    poi_id: int | None = None


class QaChatOut(BaseModel):
    conversation_id: str
    message_id: int | None = None
    answer: str
    refs: list[QaRefOut] = []
    aigc: bool = True             # AI 生成 → 前端必须展示 AIGC 标识
    degraded: bool = False        # 模型不可用时的知识库直出
    usage: dict = {}
    latency_ms: int = 0
    error_code: str | None = None
    trip: dict | None = None      # 当问题意图是"创建行程"时，返回内嵌行程卡数据


class QaMessageOut(BaseModel):
    id: int
    role: str
    content: str
    refs: list[dict] = []
    aigc: bool = False
    degraded: bool = False
    created_at: str | None = None


class QaConversationOut(BaseModel):
    id: str
    title: str
    created_at: str | None = None
    updated_at: str | None = None
    message_count: int = 0


class QaJudgeIn(BaseModel):
    trip_id: str = Field(..., min_length=3, max_length=24)
    conversation_id: str | None = Field(None, max_length=24, description='可选：写入同一问答会话')


class ChatEditIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=300, description="自然语言编辑指令，如最后一段改成骑行")


class ParseGuideIn(BaseModel):
    text: str = Field(..., min_length=10, max_length=6000, description="用户粘贴的攻略正文（不抓链接）")
    start_date: str | None = Field(None, max_length=10)
    mode: str = Field("leisure", pattern="^(leisure|blitz|premium|checkin)$")
    budget: float | None = Field(None, gt=0, description="可选：总预算；空=按匹配点位估算")