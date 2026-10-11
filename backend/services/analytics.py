"""RAG quality analytics computed from stored query logs and feedback (never synthesised)."""
from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import func, select

from backend.db.models import Chunk, Document, Job, MessageFeedback, QueryLog
from backend.db.session import session_scope
from backend.services.vector_store import knowledge_index


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))]


def quality_report(limit_rows: int = 5000) -> dict:
    with session_scope() as db:
        logs = db.scalars(select(QueryLog).order_by(QueryLog.created_at.desc()).limit(limit_rows)).all()
        fb = db.scalars(select(MessageFeedback)).all()
        # Documentation questions only: greetings and clarification requests are neither answers nor refusals.
        answered = [lg for lg in logs if lg.intent not in ("greeting", "ambiguous") and not lg.error]
        latencies = [lg.total_ms for lg in logs if not lg.error]
        confs = [lg.confidence for lg in answered if lg.confidence is not None and lg.grounded]
        pos = sum(1 for f in fb if f.rating == "positive")
        neg = sum(1 for f in fb if f.rating == "negative")
        refused = [lg for lg in answered if not lg.grounded]
        buckets = {"high": 0, "medium": 0, "low": 0, "none": 0}
        for lg in answered:
            c = lg.confidence or 0.0
            key = "none" if not lg.grounded else "high" if c >= 0.70 else "medium" if c >= 0.45 else "low"
            buckets[key] += 1
        stage: dict[str, list[float]] = defaultdict(list)
        for lg in logs:
            for name, ms in (lg.timings or {}).items():
                stage[name].append(ms)
        daily: dict[str, list[float]] = defaultdict(list)
        for lg in logs:
            daily[lg.created_at.strftime("%Y-%m-%d")].append(lg.total_ms)
        return {
            "has_data": bool(logs),
            "total_queries": len(logs),
            "answered_queries": len(answered) - len(refused),
            "refused_queries": len(refused),
            "confidence_distribution": buckets,
            "stage_latency_ms": {name: {"p50": round(_pct(v, 0.5), 1), "p95": round(_pct(v, 0.95), 1), "n": len(v)}
                                 for name, v in sorted(stage.items())},
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            "p95_latency_ms": round(_pct(latencies, 0.95), 1),
            "retrieval_success_rate": round(sum(lg.grounded for lg in answered) / len(answered), 3) if answered else 0.0,
            "avg_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
            "feedback": {"positive": pos, "negative": neg,
                         "positive_rate": round(pos / (pos + neg), 3) if pos + neg else 0.0,
                         "reasons": dict(Counter(f.reason for f in fb if f.reason))},
            "unanswered": [{"query": lg.query[:300], "created_at": lg.created_at}
                           for lg in answered if not lg.grounded][:20],
            "top_queries": [{"query": q, "count": n} for q, n in
                            Counter(lg.query.strip().lower()[:200] for lg in answered).most_common(10)],
            "failed_queries": [{"query": lg.query[:300], "error": lg.error, "created_at": lg.created_at}
                               for lg in logs if lg.error][:20],
            "by_intent": dict(Counter(lg.intent for lg in logs)),
            "daily": [{"date": d, "queries": len(v), "avg_latency_ms": round(sum(v) / len(v), 1)}
                      for d, v in sorted(daily.items())[-30:]],
        }


def kb_stats() -> dict:
    with session_scope() as db:
        docs = db.scalar(select(func.count(Document.id)).where(Document.conversation_id.is_(None))) or 0
        chunks = db.scalar(select(func.count(Chunk.id))) or 0
        embedded = db.scalar(select(func.count(Chunk.id)).where(Chunk.embedding.is_not(None))) or 0
        by_type = dict(db.execute(select(Document.source_type, func.count(Document.id))
                                  .where(Document.conversation_id.is_(None))
                                  .group_by(Document.source_type)).all())
        last_crawl = db.scalar(select(func.max(Document.last_crawled_at)))
        jobs = db.scalars(select(Job).order_by(Job.created_at.desc()).limit(10)).all()
        from datetime import datetime, timezone
        built = knowledge_index.built_at
        return {
            "documents": docs, "chunks": chunks, "embedded_chunks": embedded, "by_source_type": by_type,
            "last_crawl_at": last_crawl,
            "last_index_at": datetime.fromtimestamp(built, timezone.utc) if built else None,
            "index_vectors": knowledge_index.size, "jobs": [job_dict(j) for j in jobs],
        }


def job_dict(j: Job) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "detail": j.detail,
            "started_at": j.started_at, "finished_at": j.finished_at}
