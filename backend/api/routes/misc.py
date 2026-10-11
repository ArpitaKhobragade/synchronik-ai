"""Conversations, feedback, health and admin/ops endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from backend.api.schemas import ConversationSummary, CrawlRequest, FeedbackRequest, RenameRequest
from backend.core.config import ROOT_DIR, get_settings
from backend.core.errors import NotFound
from backend.core.security import require_admin
from backend.db.models import Message, MessageFeedback
from backend.db.session import ping, session_scope
from backend.services import conversations as convs
from backend.services import jobs
from backend.services.analytics import job_dict, kb_stats, quality_report
from backend.services.vector_store import knowledge_index

conversations = APIRouter(prefix="/api/conversations", tags=["conversations"])
feedback = APIRouter(prefix="/api", tags=["feedback"])
ops = APIRouter(prefix="/api", tags=["ops"])
admin = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# --- Conversations -------------------------------------------------------------

@conversations.get("", response_model=list[ConversationSummary])
def list_conversations(q: str | None = Query(None, max_length=100)):
    return convs.list_conversations(q)


@conversations.post("", response_model=ConversationSummary, status_code=201)
def create_conversation():
    cid = convs.ensure_conversation(None)
    return next(c for c in convs.list_conversations() if c["id"] == cid)


@conversations.get("/{cid}")
def get_conversation(cid: str):
    return convs.get_conversation(cid)


@conversations.patch("/{cid}", response_model=ConversationSummary)
def rename_conversation(cid: str, body: RenameRequest):
    return convs.rename(cid, body.title)


@conversations.delete("/{cid}", status_code=204)
def delete_conversation(cid: str):
    convs.delete(cid)
    return Response(status_code=204)


@conversations.get("/{cid}/export")
def export_conversation(cid: str, format: str = Query("markdown", pattern="^(markdown|md)$")):
    md = convs.export_markdown(cid)
    return Response(md, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="synchronik-chat-{cid[:8]}.md"'})


# --- Feedback ------------------------------------------------------------------

@feedback.post("/feedback")
def submit_feedback(body: FeedbackRequest):
    with session_scope() as db:
        if body.message_id is not None:
            msg = db.get(Message, body.message_id)
            if msg is None or msg.role != "assistant":
                raise NotFound("Message not found.")
            fb = db.scalar(select(MessageFeedback).where(MessageFeedback.message_id == msg.id))
            if fb is None:
                fb = MessageFeedback(message_id=msg.id, rating=body.rating)
                db.add(fb)
            fb.rating = body.rating
            fb.reason = body.reason if body.rating == "negative" else None
            fb.comment = body.comment if body.rating == "negative" else None
        else:  # older clients: question/answer pair without a message id
            db.add(MessageFeedback(rating=body.rating, question=body.question, answer=body.answer))
    return {"ok": True, "message": "Feedback Saved Successfully"}


# --- Health --------------------------------------------------------------------

@ops.get("/health")
def health(response: Response):
    """healthy: everything up · degraded: answers still work but without generation (no LLM key)
    or with an empty knowledge base · unhealthy: database or vector index unavailable (HTTP 503)."""
    s = get_settings()
    db_ok, db_detail = ping()
    idx_ok = knowledge_index.faiss is not None
    checks = {
        "database": {"ok": db_ok, "detail": db_detail},
        "vector_index": {"ok": idx_ok, "vectors": knowledge_index.size, "built_at": knowledge_index.built_at},
        "llm": {"ok": s.llm_configured, "configured": s.llm_configured, "model": s.llm_model},
        "embeddings": {"ok": idx_ok, "model": s.embedding_model},
    }
    if not (db_ok and idx_ok):
        status = "unhealthy"
        response.status_code = 503
    elif not s.llm_configured or knowledge_index.size == 0:
        status = "degraded"
    else:
        status = "healthy"
    return {
        "status": status, "version": s.app_version, "environment": s.environment,
        "database": "ok" if db_ok else "unavailable",
        "vector_index": "ok" if idx_ok and knowledge_index.size else ("empty" if idx_ok else "unavailable"),
        "llm": "configured" if s.llm_configured else "not_configured",
        "checks": checks,
    }


# --- Admin ---------------------------------------------------------------------

@admin.post("/verify")
def verify():
    return {"ok": True}


@admin.get("/stats")
def stats():
    return kb_stats()


@admin.post("/reindex", status_code=202)
def reindex():
    return jobs.submit("reindex", lambda: f"{knowledge_index.rebuild()} vectors indexed")


@admin.post("/crawl", status_code=202)
def crawl(body: CrawlRequest | None = None):
    from backend.crawler.crawler import crawl_all

    source = (body or CrawlRequest()).source
    return jobs.submit("crawl", lambda: crawl_all(source))


@admin.get("/jobs")
def list_jobs():
    from backend.db.models import Job

    with session_scope() as db:
        return [job_dict(j) for j in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(25))]


@admin.get("/analytics")
def analytics():
    return quality_report()


@admin.get("/evaluation")
def evaluation():
    path = ROOT_DIR / "backend" / "evaluation" / "reports" / "latest.json"
    if not path.exists():
        raise NotFound("No evaluation has been run yet. Run `python -m backend.evaluation.run`.")
    return json.loads(path.read_text(encoding="utf-8"))
