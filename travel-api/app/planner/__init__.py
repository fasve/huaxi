"""planner 包：行程生成算法（纯 Python，无框架依赖，可单测可离线跑）。

四阶段流水线（设计方案 5.1）：
  Stage1 候选筛选（服务层 SQL 完成，传入已过滤候选）
  Stage2 权重打分 scoring.py
  Stage3 日程分配 + 贪心装箱 packing.py（含分级松弛 relax.py）
  Stage4 日内路线排序 ordering.py（最近邻 + 2-opt）
"""
from app.planner.models import (
    DayPlan, PlannerPoi, SlotItem, TripPlan, TripRequest,
)
from app.planner.engine import generate_trip, replan_day, replace_slot

__all__ = [
    "DayPlan", "PlannerPoi", "SlotItem",
    "TripPlan", "TripRequest", "generate_trip", "replan_day", "replace_slot",
]
