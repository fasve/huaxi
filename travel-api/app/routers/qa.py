"""专属问答路由（游客端 / PC 端 / 小程序共用）。

接口：
- GET  /api/v1/qa/status                 模块状态（开关、模型、Key 是否配置；不回传明文 Key）
- POST /api/v1/qa/chat                   SSE 流式问答（事件：meta / delta / done）
- POST /api/v1/qa/chat/sync              非流式问答（小程序兜底、简单集成）
- GET  /api/v1/qa/suggestions            首屏推荐问题
- GET  /api/v1/qa/conversations          我的会话列表（需登录）
- GET  /api/v1/qa/conversations/{id}     会话消息（匿名会话凭随机 ID 可读）
- DEL  /api/v1/qa/conversations/{id}     删除会话（需登录且本人）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import QaChatIn, QaChatOut, QaJudgeIn
from app.services import llm_client, qa_service
from app.services.user_auth import resolve_token

router = APIRouter(prefix="/api/v1/qa", tags=["qa"])


def optional_user_id(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> int | None:
    """可选鉴权：匿名也能问；带 token 时把会话归档到账号。"""
    if not authorization:
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    try:
        return resolve_token(db, token)
    except HTTPException:
        return None


def _require_user(user_id: int | None = Depends(optional_user_id)) -> int:
    if user_id is None:
        raise HTTPException(401, "请先登录")
    return user_id


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _ensure_enabled() -> None:
    if not settings.FEATURE_QA_CHAT:
        raise HTTPException(503, "专属问答功能未启用")
    # 未配置大模型 Key 时不拦截：qa_service 会自动降级为「知识库直出」
    # （degraded=true / aigc=false），前端如实标注，不影响检索与引用卡片。


# ---------- 模块状态 ----------

@router.get("/status")
def qa_status():
    """前端据此决定是否展示问答入口；Key 只回掩码。"""
    return dict(
        enabled=bool(settings.FEATURE_QA_CHAT),
        configured=llm_client.configured(),
        provider=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        masked_key=llm_client.mask_key(settings.LLM_API_KEY),
        aigc_label="内容由 AI 生成，仅供参考",
    )


# ---------- 问答 ----------

@router.post("/chat")
def chat(
    body: QaChatIn,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(optional_user_id),
):
    """SSE 流式问答：先发 meta（会话 + 引用来源），再逐段 delta，最后 done。"""
    _ensure_enabled()
    stream = qa_service.chat_stream(
        db, body.message,
        conversation_id=body.conversation_id,
        user_id=user_id,
        trip_id=body.trip_id,
        ip=_client_ip(request),
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # 反向代理下仍保持流式
        },
    )


@router.post("/chat/sync", response_model=QaChatOut)
def chat_sync(
    body: QaChatIn,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(optional_user_id),
):
    """非流式问答：小程序低版本基础库、或调用方不需要打字机效果时使用。"""
    _ensure_enabled()
    out = qa_service.chat_once(
        db, body.message,
        conversation_id=body.conversation_id,
        user_id=user_id,
        trip_id=body.trip_id,
        ip=_client_ip(request),
    )
    return out


@router.get("/suggestions")
def qa_suggestions(db: Session = Depends(get_db)):
    """首屏推荐问题（与知识库/热门资源联动）。"""
    return dict(items=qa_service.suggestions(db))


# ---------- 会话 ----------

@router.get("/conversations")
def list_conversations(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user_id: int = Depends(_require_user),
):
    page = max(1, page)
    page_size = max(1, min(page_size, 50))
    return qa_service.list_conversations(db, user_id, page, page_size)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(optional_user_id),
):
    return qa_service.get_conversation_messages(db, conversation_id, user_id)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(_require_user),
):
    return qa_service.delete_conversation(db, conversation_id, user_id)


# ---------- 行程判官（问答内直接检查行程） ----------

@router.post("/judge")
def qa_judge(
    body: QaJudgeIn,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(optional_user_id),
):
    """在「问小旅」里直接对某个行程做判官检查，并把过程写入会话历史。

    返回判官结构化结果（前端渲染卡片）+ 自然语言摘要（落库用于历史会话）。
    """
    from app.services import trip_edit

    diag = trip_edit.diagnose(db, body.trip_id)
    overall = diag["overall"]
    lines = [
        f"行程判官：{overall['level']}（{overall['stars']} 星）",
        overall["summary"],
    ]
    for ds in diag["day_summaries"]:
        date_part = f"{ds.get('date') or ''} {ds.get('week') or ''}".strip()
        lines.append(
            f"Day{ds['day_index']} {date_part} {ds['theme']}：{ds['play_count']} 个游玩点 · "
            f"{ds['play_hours']}h，通勤 {ds['commute_km']}km/{ds['commute_min']}分钟"
            + (f" · 打车约 ¥{ds['taxi_cost']}" if ds["taxi_cost"] else "")
        )
    for s in (diag.get("suggestions") or [])[:5]:
        lines.append(f"建议：{s['title']} — {s['detail']}")
    for it in (diag.get("issues") or [])[:6]:
        lines.append(f"· [{it['level']}] {it['title']}：{it['detail']}")
    answer = "\n".join(lines)

    recorded = qa_service.record_exchange(
        db, f"【行程判官】帮我检查行程 {body.trip_id}", answer,
        conversation_id=body.conversation_id, user_id=user_id,
    )
    return dict(
        conversation_id=recorded["conversation_id"],
        message_id=recorded["message_id"],
        answer=answer,
        diagnose=diag,
    )
