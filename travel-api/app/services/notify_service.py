"""T8 出行前一日订阅消息提醒。

链路：
1. 小程序在用户点击「提醒我」时调用 `wx.requestSubscribeMessage` 授权，并把结果交给
   `POST /trips/{id}/subscribe` 落库（openid 由服务端登录态解析，前端无需传）；
2. 本模块后台线程按周期扫描到期的 pending 提醒；
3. 开启 `FEATURE_SUBSCRIBE_MSG` 且微信凭据 / 模板齐全时调用订阅消息发送接口；
   未配置时保持 pending 并在管理端返回明确原因，绝不因外部依赖缺失而抛错。
"""
from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Trip, TripReminder
from app.services.cache import TTLCache

CST = timedelta(hours=8)
_token_cache = TTLCache(ttl_seconds=7000, max_items=2)   # access_token 约 7200s 有效

_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _wechat_configured() -> bool:
    return bool(settings.WECHAT_APPID.strip() and settings.WECHAT_SECRET.strip())


def compute_remind_at(visit_date: str) -> datetime | None:
    """出行日 09:00（CST）提前 N 小时，转成与 created_at 一致的 naive UTC。"""
    try:
        local = datetime.strptime((visit_date or "").strip()[:10], "%Y-%m-%d").replace(hour=9)
    except ValueError:
        return None
    utc = local - CST
    return utc - timedelta(hours=max(0, int(settings.SUBSCRIBE_REMINDER_LEAD_HOURS)))


def create_reminder(
    db: Session, trip: Trip, user_id: int | None, openid: str,
    visit_date: str | None = None, template_id: str | None = None,
) -> dict:
    """登记一条提醒；同一行程同一出行日只保留一条 pending。"""
    day = (visit_date or trip.visit_date or "").strip()[:10]
    remind_at = compute_remind_at(day)
    if remind_at is None:
        raise ValueError("出行日期格式应为 YYYY-MM-DD")
    template = (template_id or settings.WECHAT_TEMPLATE_TRIP_REMINDER).strip()

    existing = (
        db.query(TripReminder)
        .filter(
            TripReminder.trip_id == trip.id,
            TripReminder.visit_date == day,
            TripReminder.status == "pending",
        )
        .order_by(TripReminder.id.desc())
        .first()
    )
    if existing is not None:
        existing.openid = openid or existing.openid
        existing.user_id = user_id if user_id is not None else existing.user_id
        existing.template_id = template or existing.template_id
        db.commit()
        return _out(existing, message="提醒已更新")

    row = TripReminder(
        trip_id=trip.id, user_id=user_id, openid=(openid or "").strip(),
        template_id=template, visit_date=day, remind_at=remind_at,
        status="pending",
    )
    db.add(row)
    db.commit()
    return _out(row, message="提醒已登记，将于出行前一日推送")


def _out(row: TripReminder, message: str = "") -> dict:
    return dict(
        id=row.id, trip_id=row.trip_id, visit_date=row.visit_date,
        remind_at=(row.remind_at + CST).isoformat(timespec="minutes") if row.remind_at else "",
        status=row.status, openid=(row.openid[:6] + "***") if row.openid else "",
        last_error=row.last_error or "", message=message,
    )


def list_reminders(db: Session, status: str | None = None, limit: int = 100) -> dict:
    q = db.query(TripReminder)
    if status:
        q = q.filter(TripReminder.status == status)
    rows = q.order_by(TripReminder.remind_at.desc()).limit(limit).all()
    counts = {s: db.query(TripReminder).filter(TripReminder.status == s).count()
              for s in ("pending", "sent", "skipped", "failed")}
    return dict(total=len(rows), counts=counts, items=[_out(r) for r in rows])


def _access_token() -> str:
    token = _token_cache.get("access_token")
    if token:
        return token
    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = urllib.parse.urlencode({
        "grant_type": "client_credential",
        "appid": settings.WECHAT_APPID.strip(),
        "secret": settings.WECHAT_SECRET.strip(),
    })
    req = urllib.request.Request(url + "?" + params, headers={"User-Agent": "huaxi-travel/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"获取 access_token 失败: {data.get('errmsg') or data}")
    _token_cache.set("access_token", token)
    return token


def _send(row: TripReminder, trip_name: str) -> None:
    token = _access_token()
    url = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"
    body = dict(
        touser=row.openid,
        template_id=row.template_id,
        page=f"pages/trip/trip?id={row.trip_id}",
        miniprogram_state="formal" if settings.is_prod else "developer",
        data=dict(
            thing1={"value": trip_name[:20] or "花溪行程"},
            time2={"value": row.visit_date},
            thing3={"value": "出行前一日提醒：请确认交通与预约"},
        ),
    )
    req = urllib.request.Request(
        url + "?" + urllib.parse.urlencode({"access_token": token}),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if int(data.get("errcode", 0)) != 0:
        raise RuntimeError(f"{data.get('errmsg') or '发送失败'} (errcode={data.get('errcode')})")


def run_due(db: Session, limit: int = 50) -> dict:
    """扫描并发送到期提醒；返回统计。外部依赖缺失时不改变 pending 状态。"""
    if not (settings.FEATURE_SUBSCRIBE_MSG and settings.subscribe_configured):
        due = (
            db.query(TripReminder)
            .filter(TripReminder.status == "pending",
                    TripReminder.remind_at <= datetime.utcnow())
            .count()
        )
        return dict(sent=0, failed=0, skipped=0, due=due,
                    message="FEATURE_SUBSCRIBE_MSG 或微信模板未配置，提醒保持待发送")

    rows = (
        db.query(TripReminder)
        .filter(TripReminder.status == "pending",
                TripReminder.remind_at <= datetime.utcnow())
        .order_by(TripReminder.remind_at.asc())
        .limit(limit)
        .all()
    )
    sent = failed = skipped = 0
    for row in rows:
        if not row.openid or not row.template_id:
            row.status = "skipped"
            row.last_error = "缺少 openid 或模板 ID"
            skipped += 1
            continue
        trip = db.get(Trip, row.trip_id)
        if trip is None:
            row.status = "skipped"
            row.last_error = "行程已删除"
            skipped += 1
            continue
        try:
            _send(row, trip.id)
            row.status = "sent"
            row.sent_at = datetime.utcnow()
            row.last_error = ""
            sent += 1
        except Exception as exc:  # noqa: BLE001
            row.status = "failed"
            row.last_error = str(exc)[:240]
            failed += 1
    db.commit()
    return dict(sent=sent, failed=failed, skipped=skipped,
                due=sent + failed + skipped, message="扫描完成")


def _loop() -> None:
    interval = max(5, int(settings.REMINDER_SCAN_INTERVAL_MIN)) * 60
    while not _stop_event.wait(interval):
        db = SessionLocal()
        try:
            run_due(db)
        except Exception as exc:  # noqa: BLE001
            print(f"[travel-api][REMINDER] 扫描失败：{exc}")
        finally:
            db.close()


def start_scheduler() -> None:
    """仅在开启订阅消息时启动后台线程（daemon，不阻塞进程退出）。"""
    global _thread
    if not settings.FEATURE_SUBSCRIBE_MSG:
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, name="trip-reminder", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    global _thread
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=2)
        _thread = None
