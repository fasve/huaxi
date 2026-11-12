"""游客侧行为统计：访问流水（UV/留存）、被删 POI 榜、分享流水（A5 / T5）。

设计口径（方案 A5：运营统计「自建 + 微信官方数据」）：
- 本表是**自建口径**，从部署/升级之日起累计；
- 微信官方 UV / 留存（新增/活跃/次日留存）仍需在小程序后台「统计分析」查看；
- 记录动作全部旁路化：失败只打日志，不影响登录 / 重排 / 分享主流程。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import Poi, PoiRemoveLog, TripShareLog, UserVisitLog


def ensure_tables() -> None:
    from app.database import Base, engine

    Base.metadata.create_all(engine, tables=[
        UserVisitLog.__table__, PoiRemoveLog.__table__, TripShareLog.__table__,
    ])


# ---------------- 写入 ----------------

def log_visit(db: Session, user_id: int, kind: str) -> None:
    """登录成功记一行访问流水（微信静默/匿名游客/账号密码均记）。"""
    try:
        db.add(UserVisitLog(user_id=user_id, kind=kind))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        print(f"[travel-api][STATS] 访问流水记录失败（不影响登录）：{exc}")


def log_poi_removed(db: Session, *, poi_id: int | None, trip_id: str = "",
                    day_index: int = 0, slot: str = "", action: str = "replace",
                    user_id: int | None = None) -> None:
    """行程中被用户删/换的 POI。poi_id 为空（未填槽）不记。"""
    if not poi_id:
        return
    try:
        db.add(PoiRemoveLog(
            poi_id=poi_id, trip_id=trip_id, day_index=day_index,
            slot=slot, action=action, user_id=user_id,
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        print(f"[travel-api][STATS] 被删 POI 记录失败（不影响重排）：{exc}")


def log_share(db: Session, *, trip_id: str, channel: str = "poster",
              user_id: int | None = None) -> None:
    """分享流水：channel = poster（生成海报）/ card（转发卡片）。"""
    try:
        db.add(TripShareLog(trip_id=trip_id, channel=channel, user_id=user_id))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        print(f"[travel-api][STATS] 分享流水记录失败（不影响分享）：{exc}")


# ---------------- 读取（A5 统计） ----------------

def top_removed_pois(db: Session, limit: int = 8, days: int = 30) -> list[dict]:
    """热门被删 POI 榜：近 N 天被用户从行程中换掉/删掉最多的资源点。

    反映「算法强推但用户不买账」的点位，是权重调参（4.3）的重要输入。
    """
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            PoiRemoveLog.poi_id,
            func.count(PoiRemoveLog.id).label("cnt"),
            func.sum(case((PoiRemoveLog.action == "replace", 1), else_=0)).label("n_replace"),
            func.sum(case((PoiRemoveLog.action == "redrop", 1), else_=0)).label("n_redrop"),
        )
        .filter(PoiRemoveLog.created_at >= since)
        .group_by(PoiRemoveLog.poi_id)
        .order_by(func.count(PoiRemoveLog.id).desc())
        .limit(limit)
        .all()
    )
    names = {pid: (name, cat) for pid, name, cat in
             db.query(Poi.id, Poi.name, Poi.category).all()}
    out = []
    for pid, cnt, n_replace, n_redrop in rows:
        name, cat = names.get(pid, (f"#{pid}", ""))
        out.append(dict(
            poi_id=pid, name=name, category=cat, count=int(cnt),
            replace_count=int(n_replace or 0), redrop_count=int(n_redrop or 0),
        ))
    return out


def visitor_stats(db: Session, days: int = 7) -> dict:
    """小程序/游客端 UV 与次日留存（自建口径）。

    - daily_uv：当日去重活跃游客数（含微信/匿名/账号三种身份）；
    - new_users：当日首次出现的游客（按访问流水口径）；
    - retention：当日新增游客次日仍活跃的比例（留存率，百分数一位小数）；
    - 数据从访问流水启用之日起累计，历史登录无回填。
    """
    today = datetime.utcnow().date()
    since = today - timedelta(days=days - 1)
    since_dt = datetime.combine(since, datetime.min.time())

    visits = (
        db.query(UserVisitLog.user_id, UserVisitLog.created_at)
        .filter(UserVisitLog.created_at >= since_dt)
        .all()
    )
    # 按"游客×日期"聚合活跃集合
    active_by_day: dict[str, set[int]] = {}
    for uid, created in visits:
        if not created:
            continue
        key = created.date().isoformat()
        active_by_day.setdefault(key, set()).add(uid)

    daily = []
    retention = []
    ordered_dates = [(since + timedelta(days=i)).isoformat() for i in range(days)]
    for i, key in enumerate(ordered_dates):
        today_set = active_by_day.get(key, set())
        # 新增 = 当日活跃但此前（窗口内）从未出现
        prev = set()
        for j in range(i):
            prev |= active_by_day.get(ordered_dates[j], set())
        new_users = len(today_set - prev)
        daily.append(dict(date=key, uv=len(today_set), new_users=new_users))

        # 次日留存：昨日新增游客中今日仍活跃的比例
        if i == 0:
            retention.append(dict(date=key, rate=None,
                                 note="留存量需前一日数据"))
            continue
        y_key = ordered_dates[i - 1]
        y_set = active_by_day.get(y_key, set())
        y_prev = set()
        for j in range(i - 1):
            y_prev |= active_by_day.get(ordered_dates[j], set())
        y_new = y_set - y_prev
        if y_new:
            stayed = len(y_new & today_set)
            rate = round(stayed / len(y_new) * 100, 1)
            retention.append(dict(date=key, rate=rate,
                                  base=len(y_new), stayed=stayed))
        else:
            retention.append(dict(date=key, rate=None, base=0, stayed=0))

    total_visits = db.query(func.count(UserVisitLog.id)).scalar() or 0
    total_uv = db.query(func.count(func.distinct(UserVisitLog.user_id))).scalar() or 0
    return dict(
        daily=daily,
        retention=retention,
        total_uv=int(total_uv),
        total_visits=int(total_visits),
        window_days=days,
        source="visit_log",
        note="自建口径（访问流水）；微信官方 UV/留存请在小程序后台「统计分析」查看",
    )


def share_stats(db: Session, days: int = 7) -> dict:
    """近 N 日分享次数（T5 分享卡片可统计）。"""
    today = datetime.utcnow().date()
    since = today - timedelta(days=days - 1)
    since_dt = datetime.combine(since, datetime.min.time())
    rows = (
        db.query(TripShareLog.channel, func.count(TripShareLog.id))
        .filter(TripShareLog.created_at >= since_dt)
        .group_by(TripShareLog.channel).all()
    )
    by_channel = {c: int(n) for c, n in rows}
    total_trips = db.query(func.count(func.distinct(TripShareLog.trip_id))).scalar() or 0
    return dict(
        total=sum(by_channel.values()),
        poster=by_channel.get("poster", 0),
        card=by_channel.get("card", 0),
        shared_trips=int(total_trips),
    )
