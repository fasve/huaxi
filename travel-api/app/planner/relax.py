"""分级松弛策略（方案 5.4 回填与松弛 / 5.6 约束满足策略）。

顺序（relax_log 依序记录）：
  L0 无松弛
  L1 放宽多样性（overlap 惩罚忽略）
  L2 放宽价格上限（仅非 blitz；blitz/premium 禁超支口径不可破）
  L3 引入轻量槽（≤30min 免费打卡/小吃）
  L4 次日借调
  L5 仍不足 → underfilled 标记，前端提示调整天数或预算
"""
from dataclasses import dataclass


@dataclass
class RelaxLevel:
    level: int
    label: str


LEVELS = {
    0: RelaxLevel(0, "按标准约束生成"),
    1: RelaxLevel(1, "已放宽同类多样性约束"),
    2: RelaxLevel(2, "已放宽候选价格上限"),
    3: RelaxLevel(3, "已补充轻量打卡点"),
    4: RelaxLevel(4, "已从次日借调 POI"),
    5: RelaxLevel(5, "当日未达推荐下限，建议调整天数或预算"),
    6: RelaxLevel(6, "预算节余提示（非异常，仅供调参参考）"),
}


def log_relax(relax_log: list[dict], day_index: int, level: int, detail: str = "") -> None:
    """追加一条松弛日志（前端以提示条展示）。"""
    relax_log.append({
        "day": day_index,
        "level": level,
        "label": LEVELS[level].label,
        "detail": detail,
    })
