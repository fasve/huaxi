"""管理端 · 问答模块运维接口（知识库 CRUD / 对话审计 / 模型配置）。

挂载前缀：`/api/v1/admin/qa`，全部需要管理员 Bearer Token（`require_admin`）。

- 知识库：FAQ / 运营贴士的增删改查；任何变更都会 `qa_retrieval.invalidate()`，
  让游客端问答的知识卡缓存立即失效（不用等 120s TTL）；
- 对话审计：会话列表/详情/删除 + 概览统计（降级率、平均时延等）；
- 模型配置：读取/保存运行时大模型配置（热生效 + 写回 .env，Key 只回掩码），
  以及一键测试连通性。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import QaConversation, QaKnowledge, QaMessage
from app.services import llm_client, llm_config, qa_retrieval
from app.services.admin_auth import require_admin

router = APIRouter(prefix="/api/v1/admin/qa", tags=["admin-qa"])

CATEGORIES = ("faq", "tip", "policy")


def _fmt(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None


# ---------- 请求模型 ----------

class KnowledgeIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=5000)
    category: str = Field("faq", pattern="^(faq|tip|policy)$")
    tags: list[str] = Field(default_factory=list, max_length=10)
    enabled: bool = True


class KnowledgePatch(BaseModel):
    """部分更新：只传需要修改的字段。"""
    title: str | None = Field(None, min_length=1, max_length=64)
    content: str | None = Field(None, min_length=1, max_length=5000)
    category: str | None = Field(None, pattern="^(faq|tip|policy)$")
    tags: list[str] | None = None
    enabled: bool | None = None


def _knowledge_out(k: QaKnowledge) -> dict:
    return dict(
        id=k.id, title=k.title, content=k.content, category=k.category,
        tags=list(k.tags or []), enabled=bool(k.enabled),
        created_at=_fmt(k.created_at), updated_at=_fmt(k.updated_at),
    )


# ---------- ① 知识库 CRUD ----------

@router.get("/knowledge")
def list_knowledge(
    keyword: str | None = None,
    category: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    q = db.query(QaKnowledge)
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(QaKnowledge.title.like(like) | QaKnowledge.content.like(like))
    if category in CATEGORIES:
        q = q.filter(QaKnowledge.category == category)
    if enabled is not None:
        q = q.filter(QaKnowledge.enabled.is_(enabled))
    total = q.count()
    rows = (
        q.order_by(QaKnowledge.updated_at.desc(), QaKnowledge.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return dict(total=total, page=page, page_size=page_size,
                items=[_knowledge_out(k) for k in rows])


@router.post("/knowledge")
def create_knowledge(
    body: KnowledgeIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    k = QaKnowledge(
        title=body.title.strip(), content=body.content.strip(),
        category=body.category, tags=[t.strip() for t in body.tags if t.strip()][:10],
        enabled=body.enabled,
    )
    db.add(k)
    db.commit()
    db.refresh(k)
    qa_retrieval.invalidate()
    return dict(id=k.id, message="已新增")


@router.put("/knowledge/{knowledge_id}")
def update_knowledge(
    knowledge_id: int,
    body: KnowledgePatch,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    k = db.get(QaKnowledge, knowledge_id)
    if not k:
        raise HTTPException(404, "知识条目不存在")
    if body.title is not None:
        k.title = body.title.strip()
    if body.content is not None:
        k.content = body.content.strip()
    if body.category is not None:
        k.category = body.category
    if body.tags is not None:
        k.tags = [t.strip() for t in body.tags if t.strip()][:10]
    if body.enabled is not None:
        k.enabled = body.enabled
    db.commit()
    qa_retrieval.invalidate()
    return dict(id=k.id, message="已保存")


@router.delete("/knowledge/{knowledge_id}")
def delete_knowledge(
    knowledge_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    k = db.get(QaKnowledge, knowledge_id)
    if not k:
        raise HTTPException(404, "知识条目不存在")
    db.delete(k)
    db.commit()
    qa_retrieval.invalidate()
    return dict(message="已删除")


# ---------- ② 对话审计 ----------

@router.get("/conversations")
def list_conversations(
    keyword: str | None = None,
    only_degraded: bool = False,
    user_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    q = db.query(QaConversation)
    if keyword:
        q = q.filter(QaConversation.title.like(f"%{keyword.strip()}%"))
    if user_id:
        q = q.filter(QaConversation.user_id == user_id)
    if only_degraded:
        q = q.join(QaMessage, QaMessage.conversation_id == QaConversation.id) \
             .filter(QaMessage.degraded.is_(True)).distinct()
    total = q.count()
    rows = (
        q.order_by(QaConversation.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    ids = [c.id for c in rows]
    msg_counts: dict[str, int] = {}
    degraded_counts: dict[str, int] = {}
    if ids:
        for cid, cnt in (
            db.query(QaMessage.conversation_id, func.count(QaMessage.id))
            .filter(QaMessage.conversation_id.in_(ids))
            .group_by(QaMessage.conversation_id).all()
        ):
            msg_counts[cid] = int(cnt)
        for cid, cnt in (
            db.query(QaMessage.conversation_id, func.count(QaMessage.id))
            .filter(QaMessage.conversation_id.in_(ids), QaMessage.degraded.is_(True))
            .group_by(QaMessage.conversation_id).all()
        ):
            degraded_counts[cid] = int(cnt)
    items = [dict(
        id=c.id, title=c.title, user_id=c.user_id, is_anonymous=c.user_id is None,
        message_count=msg_counts.get(c.id, 0),
        degraded_count=degraded_counts.get(c.id, 0),
        created_at=_fmt(c.created_at), updated_at=_fmt(c.updated_at),
    ) for c in rows]
    return dict(total=total, page=page, page_size=page_size, items=items)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    conv = db.get(QaConversation, conversation_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    msgs = (
        db.query(QaMessage)
        .filter(QaMessage.conversation_id == conversation_id)
        .order_by(QaMessage.id.asc()).all()
    )
    return dict(
        id=conv.id, title=conv.title, user_id=conv.user_id,
        is_anonymous=conv.user_id is None,
        created_at=_fmt(conv.created_at), updated_at=_fmt(conv.updated_at),
        messages=[dict(
            id=m.id, role=m.role, content=m.content, refs=list(m.refs or []),
            aigc=bool(m.aigc), degraded=bool(m.degraded),
            latency_ms=int(m.latency_ms or 0), created_at=_fmt(m.created_at),
        ) for m in msgs],
    )


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    conv = db.get(QaConversation, conversation_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    db.delete(conv)
    db.commit()
    return dict(message="已删除")


@router.get("/stats")
def stats(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """问答运营概览：会话/消息/降级率/平均时延/知识库数量/最近提问。"""
    conv_total = db.query(func.count(QaConversation.id)).scalar() or 0
    msg_total = db.query(func.count(QaMessage.id)).scalar() or 0
    question_total = (
        db.query(func.count(QaMessage.id))
        .filter(QaMessage.role == "user").scalar() or 0
    )
    assistant_q = db.query(QaMessage).filter(QaMessage.role == "assistant")
    assistant_total = assistant_q.count()
    degraded_total = assistant_q.filter(QaMessage.degraded.is_(True)).count()
    aigc_total = assistant_q.filter(QaMessage.aigc.is_(True)).count()
    avg_latency = (
        db.query(func.avg(QaMessage.latency_ms))
        .filter(QaMessage.role == "assistant", QaMessage.latency_ms > 0)
        .scalar() or 0
    )
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_questions = (
        db.query(func.count(QaMessage.id))
        .filter(QaMessage.role == "user", QaMessage.created_at >= today_start)
        .scalar() or 0
    )
    knowledge_total = db.query(func.count(QaKnowledge.id)).scalar() or 0
    knowledge_enabled = (
        db.query(func.count(QaKnowledge.id))
        .filter(QaKnowledge.enabled.is_(True)).scalar() or 0
    )
    recent = (
        db.query(QaMessage)
        .filter(QaMessage.role == "user")
        .order_by(QaMessage.id.desc()).limit(10).all()
    )
    return dict(
        conversations=int(conv_total),
        messages=int(msg_total),
        questions=int(question_total),
        assistant_messages=int(assistant_total),
        degraded=int(degraded_total),
        degraded_rate=round(degraded_total / assistant_total, 4) if assistant_total else 0.0,
        aigc=int(aigc_total),
        avg_latency_ms=int(avg_latency or 0),
        today_questions=int(today_questions),
        knowledge_total=int(knowledge_total),
        knowledge_enabled=int(knowledge_enabled),
        recent_questions=[dict(
            conversation_id=m.conversation_id,
            question=(m.content or "")[:80],
            created_at=_fmt(m.created_at),
        ) for m in recent],
    )


# ---------- ③ 模型配置（运行时 + 热生效） ----------

@router.get("/config")
def get_config(_: None = Depends(require_admin)):
    return llm_config.snapshot()


@router.put("/config")
def update_config(body: dict, _: None = Depends(require_admin)):
    try:
        return llm_config.update(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/config/test")
def test_config(_: None = Depends(require_admin)):
    """用当前配置发一条最小请求，验证 Key / BaseURL / 模型是否可用。"""
    started = datetime.now()
    try:
        result = llm_client.chat(
            [
                {"role": "system", "content": "你是连通性测试助手。"},
                {"role": "user", "content": "请只回复两个字：正常"},
            ],
            max_tokens=20,
            temperature=0,
            force=True,
        )
        elapsed = int((datetime.now() - started).total_seconds() * 1000)
        return dict(
            ok=True, model=settings.LLM_MODEL, latency_ms=elapsed,
            answer=result.get("answer", ""), usage=result.get("usage") or {},
            message="连接正常",
        )
    except llm_client.LlmError as exc:
        elapsed = int((datetime.now() - started).total_seconds() * 1000)
        return dict(
            ok=False, model=settings.LLM_MODEL, latency_ms=elapsed,
            error_code=exc.code, message=exc.message,
        )
    except Exception as exc:  # 兜底：任何异常都按失败返回，不抛 500
        return dict(ok=False, model=settings.LLM_MODEL, latency_ms=0,
                    error_code="unknown", message=str(exc)[:200])
