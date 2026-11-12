"""ORM 模型：严格对应设计方案 3.2 核心表结构。"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Index,
    Integer, BigInteger, String, Text,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# POI 类别枚举（study 游学点装箱时按 scenic 入池，见 3.2）
CATEGORY_ENUM = ("scenic", "food", "hotel", "leisure", "study")


class Poi(Base):
    """POI 主表：四类资源共用。"""
    __tablename__ = "poi"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(Enum(*CATEGORY_ENUM), nullable=False, index=True)
    sub_type: Mapped[str] = mapped_column(String(32), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    district: Mapped[str] = mapped_column(String(32), default="花溪区")
    open_time: Mapped[list] = mapped_column(JSON, default=list)          # [["08:00","18:00"]]
    suggest_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    ticket_price: Mapped[float] = mapped_column(Float, default=0)
    price_level: Mapped[int] = mapped_column(Integer, default=1)        # 1~5
    rating: Mapped[float] = mapped_column(Float, default=4.0)           # 0~5
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    hot_score: Mapped[float] = mapped_column(Float, default=0.5)         # 归一化 0~1
    quality_score: Mapped[float] = mapped_column(Float, default=0.5)     # 归一化 0~1
    visitable: Mapped[bool] = mapped_column(Boolean, default=True)      # 上架可推荐
    images: Mapped[list] = mapped_column(JSON, default=list)
    image_meta: Mapped[list] = mapped_column(JSON, default=list)        # 图片授权元信息（与 images 同序）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tags: Mapped[list["PoiTag"]] = relationship(back_populates="poi", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_cat_visitable", "category", "visitable"),
        Index("idx_price_level", "price_level"),
    )


class PoiExtScenic(Base):
    """景点扩展：1:1 挂 poi.id。"""
    __tablename__ = "poi_ext_scenic"
    poi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poi.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[str] = mapped_column(String(16), default="")           # 5A/4A/免费
    need_reservation: Mapped[bool] = mapped_column(Boolean, default=False)
    best_season: Mapped[str] = mapped_column(String(32), default="全季")
    indoor: Mapped[bool] = mapped_column(Boolean, default=False)
    physical_level: Mapped[int] = mapped_column(Integer, default=2)      # 体力消耗 1-5
    is_landmark: Mapped[bool] = mapped_column(Boolean, default=False)    # 打卡地标


class PoiExtFood(Base):
    """美食扩展。"""
    __tablename__ = "poi_ext_food"
    poi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poi.id", ondelete="CASCADE"), primary_key=True
    )
    cuisine: Mapped[str] = mapped_column(String(32), default="黔菜")
    signature: Mapped[list] = mapped_column(JSON, default=list)           # 招牌菜
    avg_price: Mapped[float] = mapped_column(Float, default=30)           # 人均
    meal_period: Mapped[str] = mapped_column(String(32), default="午,晚")  # 早/午/晚/夜宵
    is_time_honored: Mapped[bool] = mapped_column(Boolean, default=False) # 老字号


class PoiExtHotel(Base):
    """酒店扩展。"""
    __tablename__ = "poi_ext_hotel"
    poi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poi.id", ondelete="CASCADE"), primary_key=True
    )
    grade: Mapped[str] = mapped_column(String(16), default="经济")       # 经济/舒适/高端/民宿
    star: Mapped[int] = mapped_column(Integer, default=0)
    facility_tags: Mapped[list] = mapped_column(JSON, default=list)       # 温泉/观景/停车
    price_min: Mapped[float] = mapped_column(Float, default=150)          # 间夜最低价
    with_breakfast: Mapped[bool] = mapped_column(Boolean, default=False)


class PoiExtLeisure(Base):
    """休闲扩展。"""
    __tablename__ = "poi_ext_leisure"
    poi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poi.id", ondelete="CASCADE"), primary_key=True
    )
    play_type: Mapped[str] = mapped_column(String(32), default="")       # 骑行/游船/温泉/夜生活/亲子
    night_open: Mapped[bool] = mapped_column(Boolean, default=False)
    indoor: Mapped[bool] = mapped_column(Boolean, default=False)


class PoiExtStudy(Base):
    """游学点扩展（P1 预留，支撑 G7）。"""
    __tablename__ = "poi_ext_study"
    poi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poi.id", ondelete="CASCADE"), primary_key=True
    )
    org: Mapped[str] = mapped_column(String(64), default="")             # 所属单位/校区
    reservation_channel: Mapped[str] = mapped_column(String(255), default="")
    visit_policy: Mapped[str] = mapped_column(Text, default="")
    season_window: Mapped[str] = mapped_column(String(64), default="")   # 如 "03-15~04-05"
    study_theme: Mapped[str] = mapped_column(String(64), default="")


class Tag(Base):
    """标签字典。"""
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)


class PoiTag(Base):
    """POI-标签多对多，weight 为相关度 0~1。"""
    __tablename__ = "poi_tag"
    poi_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poi.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    poi: Mapped["Poi"] = relationship(back_populates="tags")
    tag: Mapped["Tag"] = relationship()


class TripModeConfig(Base):
    """模式权重配置：权重即配置，不改代码调参（4.2/4.3/11.2）。"""
    __tablename__ = "trip_mode_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    mode_name: Mapped[str] = mapped_column(String(32), nullable=False)
    weights: Mapped[dict] = mapped_column(JSON, nullable=False)          # 9 维权重向量
    hard_rules: Mapped[dict] = mapped_column(JSON, nullable=False)      # 硬约束
    slot_template: Mapped[list] = mapped_column(JSON, nullable=False)    # 每日槽位模板
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class AdminUser(Base):
    """管理后台账号。独立于微信游客 User 表，避免角色混淆。"""
    __tablename__ = "admin_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), default="管理员")
    status: Mapped[int] = mapped_column(Integer, default=1)              # 1 正常 / 0 停用
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdminSession(Base):
    """管理端登录会话：服务端可撤销，退出/改密后旧 token 立即失效。"""
    __tablename__ = "admin_session"

    token: Mapped[str] = mapped_column(String(96), primary_key=True)
    admin_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_user.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    """微信静默建档用户。"""
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    unionid: Mapped[str] = mapped_column(String(64), nullable=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    avatar_url: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(16), default="member")
    status: Mapped[int] = mapped_column(Integer, default=1)              # 1 正常 / 0 禁用
    member_preference: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserAccount(Base):
    """游客账号（PC / 小程序通用）。

    账号与微信身份解耦：仍复用 User 作为行程归属主体，账号只负责登录凭据，
    因此微信 mock / code2session 用户登录后可与账号体系平滑合并。
    """
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), unique=True, index=True
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[int] = mapped_column(Integer, default=1)              # 1 正常 / 0 禁用
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserSession(Base):
    """游客登录会话：存量 `us_` token 的兼容通道，已不再签发新会话。"""
    __tablename__ = "user_session"

    token: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserWechatSession(Base):
    """微信会话密钥（服务端专用，绝不下发）。

    session_key 仅用于服务端解密（二期 getPhoneNumber 等），按 openid 覆盖更新。
    设计方案 7.5：session_key 不写入前端、不进 JWT claims。
    """
    __tablename__ = "user_wechat_session"

    openid: Mapped[str] = mapped_column(String(64), primary_key=True)
    unionid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_key: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TokenDenylist(Base):
    """已撤销 JWT 的 jti 黑名单：让无状态 JWT 支持「退出登录立即失效」。

    记录随 exp 过期自动清理，避免无限膨胀。
    """
    __tablename__ = "token_denylist"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject: Mapped[str] = mapped_column(String(32), default="", index=True)
    kind: Mapped[str] = mapped_column(String(16), default="guest", index=True)
    reason: Mapped[str] = mapped_column(String(64), default="logout")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------- 运营观测（A5 / A6 / T5） ----------------

class AuditLog(Base):
    """管理员操作审计（方案 3.2 audit_log：who/what/before/after）。

    只记录管理端写操作与登录/改密事件；查询走专门接口，不参与业务链路。
    detail 存 before/after 摘要，大对象（如完整权重向量）仅存变化项。
    """
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")           # 快照，防账号改名后对不上
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # login/logout/poi.create/...
    resource_type: Mapped[str] = mapped_column(String(32), default="", index=True)  # poi/tag/trip/...
    resource_id: Mapped[str] = mapped_column(String(64), default="")        # 字符串兼容 trip 短码
    detail: Mapped[dict] = mapped_column(JSON, default=dict)                # {before, after, message}
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True,
    )


class UserVisitLog(Base):
    """游客访问流水（A5 小程序 UV / 留存自建口径）。

    登录成功（微信静默 / 匿名游客 / 账号密码）时各记一行；
    UV = 按日去重 user_id；留存 = 相邻两日活跃集合的交集。
    微信官方 UV/留存仍需在小程序后台查看，本表只是自建补充。
    """
    __tablename__ = "user_visit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="wechat")         # wechat/anonymous/account
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True,
    )


class PoiRemoveLog(Base):
    """行程中被用户删掉/换掉的 POI（A5「热门被删 POI 榜」）。

    触发点：rebalance replace（槽位替换的旧 POI）与 redrop（当日重排删除的旧条目）。
    与 audit_log 区分：这是游客侧行为统计，非管理员审计。
    """
    __tablename__ = "poi_remove_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    poi_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    trip_id: Mapped[str] = mapped_column(String(16), default="", index=True)
    day_index: Mapped[int] = mapped_column(Integer, default=0)
    slot: Mapped[str] = mapped_column(String(16), default="")
    action: Mapped[str] = mapped_column(String(16), default="replace")     # replace/redrop
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True,
    )


class TripShareLog(Base):
    """行程分享流水（T5：海报/分享卡片的次数统计口径）。"""
    __tablename__ = "trip_share_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), default="poster")      # poster/card
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True,
    )


class Trip(Base):
    """行程主表：user_id 可空 = 匿名临时行程。"""
    __tablename__ = "trip"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)        # t_xxxx 短码
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    budget: Mapped[float] = mapped_column(Float, nullable=False)
    preferences: Mapped[list] = mapped_column(JSON, default=list)
    party_type: Mapped[str] = mapped_column(String(32), default="")
    total_cost: Mapped[float] = mapped_column(Float, default=0)
    score: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="draft")      # draft/saved
    seed: Mapped[int] = mapped_column(Integer, default=0)                 # 复现/换一批
    custom_weights: Mapped[dict] = mapped_column(JSON, default=dict)      # 个性化权重（0~1，和为1）；空=用模式默认
    pace_config: Mapped[dict] = mapped_column(JSON, default=dict)         # 节奏微调（点数上限/游玩小时/晚间偏好）
    preset_route_code: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 预设主题路线 code（G7）
    visit_date: Mapped[str | None] = mapped_column(String(10), nullable=True)        # 出行日期 YYYY-MM-DD（date_gate 用）
    relax_log: Mapped[list] = mapped_column(JSON, default=list)            # 松弛提示
    explanation: Mapped[list] = mapped_column(JSON, default=list)          # 模式说明卡
    expire_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    days_plan: Mapped[list["TripDay"]] = relationship(
        back_populates="trip", cascade="all, delete-orphan"
    )


class TripDay(Base):
    __tablename__ = "trip_day"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("trip.id", ondelete="CASCADE"), index=True
    )
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    theme: Mapped[str] = mapped_column(String(64), default="")
    day_budget: Mapped[float] = mapped_column(Float, default=0)
    day_cost: Mapped[float] = mapped_column(Float, default=0)
    day_drift_min: Mapped[int] = mapped_column(Integer, default=0)
    hotel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 全程同店锚点

    trip: Mapped["Trip"] = relationship(back_populates="days_plan")
    items: Mapped[list["TripItem"]] = relationship(
        back_populates="day", cascade="all, delete-orphan"
    )


class TripItem(Base):
    __tablename__ = "trip_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_day_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trip_day.id", ondelete="CASCADE"), index=True
    )
    slot_type: Mapped[str] = mapped_column(String(16), nullable=False)   # morning/lunch/...
    poi_id: Mapped[int] = mapped_column(BigInteger, nullable=True)       # 可空=未填槽
    start_time: Mapped[str] = mapped_column(String(5), default="")      # "09:00"
    duration_min: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # 该点与前一点之间的出行方式（空=按引擎估算）；对话编辑「改成骑行」时写入并参与重算
    transport_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)

    day: Mapped["TripDay"] = relationship(back_populates="items")


# ---------------- 预设主题路线（G7 / T9 / A7，方案 3.2 / 5.8 / 11.4） ----------------

class PresetRoute(Base):
    """官方编排的主题线路主表（首条：贵州大学校园游学线）。

    线路不是另写一套行程引擎，而是把专家编排的站点序列当保底项注入现有流水线（5.8）。
    """
    __tablename__ = "preset_route"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(255), default="")
    theme: Mapped[str] = mapped_column(String(32), default="study_tour")  # study_tour/culture/eco/night
    target_group: Mapped[str] = mapped_column(String(64), default="")     # 亲子/中学团体/家庭/游客
    duration_hours: Mapped[float] = mapped_column(Float, default=4.0)     # 半日精华版时长
    season_window: Mapped[dict] = mapped_column(JSON, default=dict)       # 花期/最佳季 {"start":"03-15","end":"04-05"}
    difficulty: Mapped[str] = mapped_column(String(16), default="轻松")   # 轻松/适中/较高
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)          # A7 季节性开关
    version: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(Text, default="")                # 线路简介
    cover_image: Mapped[str] = mapped_column(String(255), default="")
    reservation_note: Mapped[str] = mapped_column(Text, default="")       # 入校预约政策提示
    transit_note: Mapped[str] = mapped_column(Text, default="")           # 交通与校内规则
    mode_tips: Mapped[dict] = mapped_column(JSON, default=dict)           # 四模式适配口径（11.4）
    sources: Mapped[list] = mapped_column(JSON, default=list)             # 政策/开放时间来源与待核标记
    policy_checked_at: Mapped[str] = mapped_column(String(10), default="")  # A7 周更校验日期
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    stops: Mapped[list["PresetRouteStop"]] = relationship(
        back_populates="route", cascade="all, delete-orphan",
        order_by="PresetRouteStop.seq",
    )


class PresetRouteStop(Base):
    """线路站点：逐站讲解、研学任务卡、步行衔接与 date_gate 日期闸门。

    date_gate 为 list[dict]，支持四类（方案 11.2）：
      weekday_only / season_window / reservation_required / open_hours
    """
    __tablename__ = "preset_route_stop"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("preset_route.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)             # 站点顺序
    poi_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("poi.id"), nullable=False)
    stay_min: Mapped[int] = mapped_column(Integer, default=30)            # 停留时长
    walk_in_min: Mapped[int] = mapped_column(Integer, default=0)          # 与上一站衔接步行（校内实测，不走路径 API）
    narration_title: Mapped[str] = mapped_column(String(128), default="")
    narration_text: Mapped[str] = mapped_column(Text, default="")         # 逐站讲解
    task_card: Mapped[dict] = mapped_column(JSON, default=dict)           # 研学任务 {"title","content","type"}
    photo_tip: Mapped[str] = mapped_column(String(255), default="")
    must_visit: Mapped[bool] = mapped_column(Boolean, default=True)       # 必选 / 可选
    date_gate: Mapped[list] = mapped_column(JSON, default=list)           # 日期闸门列表
    fallback_poi_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 错季替换站
    degrade_text: Mapped[str] = mapped_column(Text, default="")           # 降级后的讲解文案
    degrade_stay_min: Mapped[int] = mapped_column(Integer, default=0)     # 降级后停留（0=原时长）
    slot: Mapped[str] = mapped_column(String(16), default="morning")      # 预占槽位 morning/afternoon
    is_addon: Mapped[bool] = mapped_column(Boolean, default=False)        # 全天深度版加段

    route: Mapped["PresetRoute"] = relationship(back_populates="stops")


# ---------------- P1/P2 扩展（T7 / T8 / A2 / A3 / A4 / 8.1） ----------------

class TripEnrichment(Base):
    """T7 AI 润色与小贴士：按行程缓存，避免重复调用模型。

    scope=trip 时 day_index=0，payload 为整程润色结果；scope=day 时可逐日覆盖。
    provider 记录生成来源（ai / rule），便于前端提示与回归对比。
    """
    __tablename__ = "trip_enrichment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(16), default="trip")        # trip/day
    day_index: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(16), default="rule")     # ai/rule
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_enrich_trip_scope", "trip_id", "scope", "day_index"),
    )


class TripReminder(Base):
    """T8 出行前一日订阅消息提醒：一条行程可有多条（换日期重新订阅）。

    status: pending / sent / skipped / failed；失败保留 last_error 供运维排查。
    """
    __tablename__ = "trip_reminder"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    openid: Mapped[str] = mapped_column(String(64), default="")
    template_id: Mapped[str] = mapped_column(String(64), default="")
    visit_date: Mapped[str] = mapped_column(String(10), default="")
    remind_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    last_error: Mapped[str] = mapped_column(String(255), default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserTripStat(Base):
    """用户行程统计（A5 自建口径补充）：按用户汇总行程数 / 花费 / 最近出行。"""
    __tablename__ = "user_trip_stat"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trip_count: Mapped[int] = mapped_column(Integer, default=0)
    saved_count: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0)
    last_trip_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PriceBandRule(Base):
    """A3 价格分档规则：按票价区间映射 price_level（1~5），管理端可调。"""
    __tablename__ = "price_band_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    min_price: Mapped[float] = mapped_column(Float, default=0)
    max_price: Mapped[float] = mapped_column(Float, nullable=False)
    price_level: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PoiEffectiveRule(Base):
    """A3 价格 / 开放时间「生效时间管理」。

    kind=price: value={"price": 80, "price_level": 4}
    kind=hours: value={"open_time": [["08:00","18:00"]]}
    命中规则 = enabled 且 valid_from<=今天<=valid_to（空表示不限）。
    """
    __tablename__ = "poi_effective_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    poi_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="price")        # price/hours
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    valid_from: Mapped[str] = mapped_column(String(10), default="")
    valid_to: Mapped[str] = mapped_column(String(10), default="")
    note: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TagSynonym(Base):
    """A2 标签同义词归并：alias 统一归到 canonical_code（Tag.code）。"""
    __tablename__ = "tag_synonym"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    canonical_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TripModeConfigVersion(Base):
    """A4 权重配置版本：支持历史回滚与灰度发布。

    status: active / history / candidate
    traffic_pct: 灰度流量百分比（0~100），仅 candidate 生效。
    """
    __tablename__ = "trip_mode_config_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    hard_rules: Mapped[dict] = mapped_column(JSON, nullable=False)
    slot_template: Mapped[list] = mapped_column(JSON, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="history", index=True)
    traffic_pct: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_mode_version", "mode", "version"),
    )


# ---------- 专属问答（AI 助手） ----------

class QaKnowledge(Base):
    """问答知识库：FAQ / 本地贴士 / 运营补录（POI 知识卡由 poi 表实时生成，不落此表）。"""
    __tablename__ = "qa_knowledge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(16), default="faq", index=True)  # faq/tip/policy
    tags: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class QaConversation(Base):
    """问答会话：匿名可用（user_id 为空），登录后按 user_id 归档「我的会话」。"""
    __tablename__ = "qa_conversation"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)        # qc_xxxxxx
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(64), default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    messages: Mapped[list["QaMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class QaMessage(Base):
    """问答消息：assistant 消息记录引用来源与 AIGC 标识，便于审计与合规展示。"""
    __tablename__ = "qa_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("qa_conversation.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)        # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    refs: Mapped[list] = mapped_column(JSON, default=list)               # 引用来源（POI/FAQ/模式）
    aigc: Mapped[bool] = mapped_column(Boolean, default=False)           # 是否为 AI 生成
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)       # 是否走了降级（知识库直出）
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    conversation: Mapped["QaConversation"] = relationship(back_populates="messages")
