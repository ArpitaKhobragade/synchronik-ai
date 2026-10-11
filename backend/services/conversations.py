"""Conversation memory backed by PostgreSQL.

Conversations are database rows (they survive restarts and are separate per
conversation id), and only a bounded window — the last ``history_max_messages`` messages,
trimmed to ``history_max_chars`` — is ever sent to the LLM.
"""
from __future__ import annotations

import re

from sqlalchemy import func, or_, select

from backend.core.config import get_settings
from backend.core.errors import NotFound
from backend.db.models import Conversation, Document, Message, utcnow
from backend.db.session import session_scope


def ensure_conversation(conversation_id: str | None) -> str:
    with session_scope() as db:
        if conversation_id:
            conv = db.get(Conversation, conversation_id)
            if conv is not None:
                return conv.id
        conv = Conversation()
        if conversation_id and len(conversation_id) <= 32 and conversation_id.isalnum():
            conv.id = conversation_id  # honour ids chosen by embedding widgets
        db.add(conv)
        db.flush()
        return conv.id


def history_window(conversation_id: str) -> list[dict]:
    """Recent turns, newest last, bounded by message count and characters."""
    s = get_settings()
    with session_scope() as db:
        rows = db.scalars(
            select(Message).where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc()).limit(s.history_max_messages)
        ).all()
    out, used = [], 0
    for m in rows:  # newest first
        text = m.content[:1500]
        if used + len(text) > s.history_max_chars and out:
            break
        out.append({"role": m.role, "content": text})
        used += len(text)
    return list(reversed(out))


def has_attachments(conversation_id: str) -> bool:
    with session_scope() as db:
        return bool(db.scalar(select(func.count(Document.id)).where(Document.conversation_id == conversation_id)))


def attachment_documents(conversation_id: str) -> list[dict]:
    """The processed documents attached to a conversation, oldest first, with their chunks in reading order."""
    with session_scope() as db:
        docs = db.scalars(select(Document).where(Document.conversation_id == conversation_id,
                                                 Document.status == "ready").order_by(Document.id)).all()
        return [{"id": d.id, "title": d.title,
                 "chunks": [{"id": c.id, "index": c.chunk_index, "text": c.text, "page": c.page}
                            for c in sorted(d.chunks, key=lambda c: c.chunk_index)]}
                for d in docs if d.chunks]


def add_message(conversation_id: str, role: str, content: str, **extra) -> int:
    with session_scope() as db:
        conv = db.get(Conversation, conversation_id)
        if conv is None:
            raise NotFound("Conversation not found.")
        msg = Message(conversation_id=conversation_id, role=role, content=content, **extra)
        db.add(msg)
        conv.updated_at = utcnow()
        if role == "user" and conv.title == "New conversation":
            conv.title = _title_from(content)
        db.flush()
        return msg.id


def _title_from(text: str) -> str:
    # Plain text only: the attachment notice "📎 Attached **name**" becomes "Attached name".
    t = " ".join(re.sub(r"[*_`#>]|📎", " ", text).split())
    return (t[:57] + "…") if len(t) > 60 else t or "New conversation"


def delete_last_assistant(conversation_id: str, expected: str | None = None) -> str | None:
    """For regenerate/retry: drop the last exchange (reply, if any, and its question) and return the question.

    With ``expected``, nothing is deleted unless the last question is exactly that text, so a retry of a
    message the server never stored cannot erase the previous exchange. Nothing is deleted on ``None``.
    """
    with session_scope() as db:
        msgs = db.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(2)
        ).all()
        if not msgs:
            return None
        reply = msgs[0] if msgs[0].role == "assistant" else None
        user = (msgs[1] if len(msgs) > 1 else None) if reply is not None else msgs[0]
        if user is None or user.role != "user":
            return None
        if expected is not None and user.content.strip() != expected.strip():
            return None
        if reply is not None:
            db.delete(reply)
        text = user.content
        db.delete(user)  # the pipeline re-adds it
        return text


def last_message_id(conversation_id: str) -> int | None:
    with session_scope() as db:
        return db.scalar(select(func.max(Message.id)).where(Message.conversation_id == conversation_id))


def list_conversations(q: str | None = None, limit: int = 100) -> list[dict]:
    with session_scope() as db:
        count_sq = (select(Message.conversation_id, func.count(Message.id).label("n"))
                    .group_by(Message.conversation_id).subquery())
        stmt = (select(Conversation, func.coalesce(count_sq.c.n, 0))
                .outerjoin(count_sq, count_sq.c.conversation_id == Conversation.id))
        if q:
            like = f"%{q.strip()[:100]}%"
            matching = select(Message.conversation_id).where(Message.content.ilike(like))
            stmt = stmt.where(or_(Conversation.title.ilike(like), Conversation.id.in_(matching)))
        rows = db.execute(stmt.order_by(Conversation.updated_at.desc()).limit(limit)).all()
        out = []
        for conv, n in rows:
            item = summary(conv, n)
            if q:
                hit = db.scalar(select(Message.content).where(
                    Message.conversation_id == conv.id, Message.content.ilike(f"%{q.strip()[:100]}%")).limit(1))
                if hit:
                    i = hit.lower().find(q.strip().lower())
                    item["match"] = ("…" if i > 40 else "") + hit[max(0, i - 40): i + 80] + "…"
            out.append(item)
        return out


def summary(conv: Conversation, n: int) -> dict:
    return {"id": conv.id, "title": conv.title, "created_at": conv.created_at,
            "updated_at": conv.updated_at, "message_count": n}


def get_conversation(conversation_id: str) -> dict:
    with session_scope() as db:
        conv = db.get(Conversation, conversation_id)
        if conv is None:
            raise NotFound("Conversation not found.")
        msgs = [{
            "id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at,
            "sources": m.sources, "confidence": m.confidence, "metadata": m.meta,
            "attachment": m.attachment, "feedback": m.feedback.rating if m.feedback else None,
        } for m in conv.messages]
        return {"id": conv.id, "title": conv.title, "created_at": conv.created_at,
                "updated_at": conv.updated_at, "messages": msgs}


def rename(conversation_id: str, title: str) -> dict:
    with session_scope() as db:
        conv = db.get(Conversation, conversation_id)
        if conv is None:
            raise NotFound("Conversation not found.")
        conv.title = title.strip()[:200] or conv.title
        return summary(conv, len(conv.messages))


def delete(conversation_id: str) -> None:
    from backend.services.vector_store import knowledge_index

    with session_scope() as db:
        conv = db.get(Conversation, conversation_id)
        if conv is None:
            raise NotFound("Conversation not found.")
        chunk_ids = [c.id for d in db.scalars(select(Document).where(Document.conversation_id == conversation_id))
                     for c in d.chunks]
        for d in db.scalars(select(Document).where(Document.conversation_id == conversation_id)):
            db.delete(d)
        db.delete(conv)
    knowledge_index.remove(chunk_ids)


def export_markdown(conversation_id: str) -> str:
    conv = get_conversation(conversation_id)
    lines = [f"# {conv['title']}", "", f"_Exported from Synchronik AI · {utcnow():%Y-%m-%d %H:%M UTC}_", ""]
    for m in conv["messages"]:
        who = "You" if m["role"] == "user" else "Synchronik AI"
        lines += [f"### {who} · {m['created_at']:%Y-%m-%d %H:%M}", "", m["content"], ""]
        if m.get("sources"):
            lines.append("**Sources**")
            for src in m["sources"]:
                loc = f", p. {src['page']}" if src.get("page") else ""
                link = f" — {src['url']}" if src.get("url") else ""
                lines.append(f"- [{src['id']}] {src['title']}{loc}{link}")
            lines.append("")
    return "\n".join(lines)
