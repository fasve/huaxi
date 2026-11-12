"""预设主题路线的「日期感知闸门」纯逻辑（方案 5.8 / 11.2 / 11.4）。

设计要点：本模块不依赖数据库与 Web 框架，可离线单测。
生成行程或渲染线路详情时，把 `date_gate` 规则 + 出行日期喂进来，
返回「该站今天能不能按原样走、不能的话怎么降级」的结论。

四类闸门：
  - weekday_only          仅工作日开放（校史馆），周末/节假日/寒暑假 → 馆外讲解 + 缩短时长
  - season_window         花期类（樱花 3/15–4/5），错季 → 替换同类常绿站点
  - reservation_required  入校预约 → 强制挂预约提醒任务卡，不阻断行程
  - open_hours            开放时段 → 给出到站时刻建议
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅供类型检查，避免 planner 层依赖 ORM
    from app.planner.models import PlannerPoi

# ---------------------------------------------------------------------------
# 法定节假日口径（方案 11.4 标注「单源待校验」）
# 公历固定节日可安全内置；春节/清明/端午/中秋按农历逐年变动，
# 不硬编码，统一由 A7 后台按当年《国务院办公厅关于节假日安排的通知》维护。
# 演示口径：仅保证周末 + 寒暑假 + 固定公历节日的判定不误判。
# ---------------------------------------------------------------------------
FIXED_PUBLIC_HOLIDAYS: set[str] = {
    "01-01",  # 元旦
    "05-01", "05-02", "05-03",  # 劳动节（核心假日）
    "10-01", "10-02", "10-03",  # 国庆节（核心假日）
}

# 可由部署方扩展的完整放假日期（YYYY-MM-DD），例如春节、清明、端午、中秋
EXTRA_HOLIDAYS: set[str] = set()

# 寒暑假月份（近似口径：高校通常 1–2 月、7–8 月；校史馆该时段闭馆）
SCHOOL_BREAK_MONTHS: set[int] = {1, 2, 7, 8}

GATE_LABELS = {
    "weekday_only": "仅工作日开放",
    "season_window": "季节性窗口",
    "reservation_required": "需预约",
    "open_hours": "开放时段",
}


def parse_visit_date(value: str | date | None) -> date:
    """解析出行日期；为空/非法时回落到今天（保证接口永不因日期报错）。"""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            pass
    return datetime.now().date()


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def is_public_holiday(d: date) -> bool:
    md = d.strftime("%m-%d")
    return md in FIXED_PUBLIC_HOLIDAYS or d.isoformat() in EXTRA_HOLIDAYS


def is_school_break(d: date) -> bool:
    return d.month in SCHOOL_BREAK_MONTHS


def is_business_day(d: date) -> bool:
    """「可进馆的工作日」= 非周末 且 非节假日 且 非寒暑假。"""
    return not is_weekend(d) and not is_public_holiday(d) and not is_school_break(d)


def in_season_window(d: date, start: str, end: str) -> bool:
    """MM-DD 窗口判定，支持跨年窗口（如 12-20 ~ 01-10）。"""
    try:
        s, e = str(start), str(end)
        md = d.strftime("%m-%d")
        if s <= e:
            return s <= md <= e
        return md >= s or md <= e
    except (TypeError, ValueError):
        return True  # 规则写坏时不误伤行程


@dataclass
class GateVerdict:
    """单个站点经日期闸门判定后的最终口径。"""
    status: str = "open"                 # open / degraded / replaced / reminder
    notes: list[str] = field(default_factory=list)        # 给用户看的结论（也进 relax_log）
    actions: list[str] = field(default_factory=list)      # 追加的任务卡（如预约提醒）
    effective_poi_id: int | None = None                   # 替换后的站点 id
    effective_stay_min: int | None = None                 # 降级后的停留时长
    effective_narration: str | None = None                # 降级后的讲解文案
    suggest_arrival: str | None = None                    # 建议到站时刻
    reservation: dict | None = None                       # 预约渠道信息
    gate_details: list[dict] = field(default_factory=list)  # 每条闸门的原始判定，供前端展示

    @property
    def blocked(self) -> bool:
        """是否需要降级/替换（用于汇总线路级状态）。"""
        return self.status in ("degraded", "replaced")


def evaluate_gates(
    gates: list[dict] | dict | None,
    visit_date: str | date | None,
    *,
    stay_min: int = 30,
    poi_id: int | None = None,
    fallback_poi_id: int | None = None,
    degrade_text: str = "",
    degrade_stay_min: int = 0,
    narration_text: str = "",
) -> GateVerdict:
    """评估一个站点的全部 date_gate，合并成一份最终口径。

    合并优先级：replaced > degraded > reminder > open。
    多条闸门同时命中时，notes/actions 全部保留（不吞信息）。
    """
    d = parse_visit_date(visit_date)
    rules: list[dict] = []
    if isinstance(gates, dict):
        rules = [gates]
    elif isinstance(gates, list):
        rules = [g for g in gates if isinstance(g, dict)]
    if not rules:
        return GateVerdict(status="open", effective_poi_id=poi_id,
                           effective_stay_min=stay_min,
                           effective_narration=narration_text)

    v = GateVerdict(effective_poi_id=poi_id, effective_stay_min=stay_min,
                    effective_narration=narration_text)
    rank = {"open": 0, "reminder": 1, "degraded": 2, "replaced": 3}

    for g in rules:
        gtype = str(g.get("type", "")).strip()
        detail: dict = {
            "type": gtype,
            "label": GATE_LABELS.get(gtype, gtype or "未知规则"),
            "passed": True,
            "message": "",
        }

        if gtype == "weekday_only":
            ok = is_business_day(d)
            detail["passed"] = ok
            if not ok:
                reason = ("周末" if is_weekend(d) else
                          "法定节假日" if is_public_holiday(d) else
                          "寒暑假期间")
                detail["message"] = f"{reason}闭馆，改为馆外讲解牌"
                v.notes.append(
                    f"{reason}：{g.get('name', '室内场馆')}不开放，已降级为馆外讲解 + 外观参观"
                )
                v.effective_stay_min = degrade_stay_min or min(stay_min, 20)
                v.effective_narration = degrade_text or (
                    "该场馆仅工作日开放，今日在馆外展板完成校史/建筑讲解，不进入室内。"
                )
                if rank["degraded"] > rank[v.status]:
                    v.status = "degraded"

        elif gtype == "season_window":
            s, e = g.get("start", "03-15"), g.get("end", "04-05")
            ok = in_season_window(d, s, e)
            detail["passed"] = ok
            detail["window"] = f"{s} ~ {e}"
            if not ok:
                fb = g.get("fallback_poi_id") or fallback_poi_id
                detail["message"] = "非当季，已替换常年景观站点" if fb else "非当季，提示当季无常景"
                v.notes.append(
                    f"当季非花期（窗口 {s}–{e}），已替换为常年景观站点：{g.get('fallback_name', '贤正湖 / 松林坡绿道')}"
                    if fb else f"当季非花期（窗口 {s}–{e}），此站改为常绿植被观察"
                )
                if fb:
                    v.effective_poi_id = int(fb)
                    if rank["replaced"] > rank[v.status]:
                        v.status = "replaced"
                else:
                    if rank["degraded"] > rank[v.status]:
                        v.status = "degraded"
                v.effective_narration = degrade_text or (
                    "非花期改为辨识校园常绿树种与喀斯特水循环，观察对象同样丰富。"
                )

        elif gtype == "reservation_required":
            # 预约类闸门不改变站点，只强制追加任务卡（方案 5.8：自动处理而非报错）
            channel = g.get("channel", "")
            detail["message"] = "需提前预约"
            v.reservation = dict(
                channel=channel,
                lead_days=int(g.get("lead_days", 1) or 1),
                policy=g.get("note", ""),
            )
            v.notes.append(f"入校需预约：{channel or '请按校方官方渠道办理'}（建议出行前 1 天完成）")
            v.actions.append(g.get("task", "出行前完成访客预约，随身携带身份证 / 预约码"))
            if rank["reminder"] > rank[v.status]:
                v.status = "reminder"

        elif gtype == "open_hours":
            windows = g.get("windows") or []
            if windows:
                v.suggest_arrival = str(windows[0][0]) if isinstance(windows[0], (list, tuple)) else str(windows[0])
                detail["message"] = f"开放时段 {windows}，建议 {v.suggest_arrival} 前到站"
                v.notes.append(f"开放时段 {windows}，建议 {v.suggest_arrival} 前后到站")
            detail["passed"] = True

        else:
            detail["passed"] = True
            detail["message"] = "未识别规则，按原样通过"

        v.gate_details.append(detail)

    return v


def route_day_summary(d: date) -> dict:
    """线路级日期概览：给前端顶部横条用。"""
    weekend = is_weekend(d)
    holiday = is_public_holiday(d)
    vacation = is_school_break(d)
    if holiday:
        label, tone = "法定节假日", "warn"
    elif vacation:
        label, tone = "寒暑假期间", "warn"
    elif weekend:
        label, tone = "周末", "warn"
    else:
        label, tone = "工作日", "ok"
    return dict(
        date=d.isoformat(),
        weekday="一二三四五六日"[d.weekday()],
        day_type=label,
        tone=tone,
        indoor_venues_open=is_business_day(d),
        note=("校史馆等室内场馆仅工作日开放，今日自动降级为馆外讲解" if not is_business_day(d)
              else "室内场馆正常开放，可按完整线路走完"),
    )


def as_dict(v: GateVerdict) -> dict:
    """序列化为接口响应字段。"""
    return dict(
        status=v.status, notes=v.notes, actions=v.actions,
        effective_poi_id=v.effective_poi_id,
        effective_stay_min=v.effective_stay_min,
        effective_narration=v.effective_narration,
        suggest_arrival=v.suggest_arrival,
        reservation=v.reservation,
        gate_details=v.gate_details,
    )


@dataclass
class InjectedStop:
    """经 date_gate 判定后、准备注入装箱引擎的站点（方案 5.8 第 1 条）。

    `poi` 是已经归一为 scenic 类别的 PlannerPoi；`walk_in_min` 是校内实测步行衔接，
    注入时直接用它，不走 Haversine / 外部路径 API（5.8 第 5 条）。
    """
    poi: "PlannerPoi"
    seq: int
    stay_min: int
    walk_in_min: int
    slot: str = "morning"
    narration_title: str = ""
    narration_text: str = ""
    task_card: dict = field(default_factory=dict)
    photo_tip: str = ""
    gate_status: str = "open"
    gate_notes: list[str] = field(default_factory=list)
    must_visit: bool = True
    is_addon: bool = False
