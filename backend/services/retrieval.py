"""Hybrid retrieval: semantic (FAISS) + keyword (BM25) → fusion → rerank → gate.

1. Semantic: top ``semantic_top_k`` chunks by cosine similarity.
2. Keyword:  top ``keyword_top_k`` chunks by BM25 (exact ERP terms like "OBE",
   "CO-PO", "hall ticket" that embeddings blur).
3. Metadata filter: only global KB chunks + attachments of *this* conversation.
4. Fusion: ``w_sem * cosine + w_kw * bm25/max(bm25)`` (weights from config).
5. Rerank: cross-encoder over the best ``rerank_candidates`` fused candidates, keep ``rerank_top_n``.
6. Relevance gate: if the best evidence is below thresholds the pipeline
   refuses instead of letting the LLM improvise.
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select

from backend.core.config import get_settings
from backend.db.models import Chunk, Document
from backend.db.session import session_scope
from backend.services.embeddings import get_embedder
from backend.services.reranker import get_reranker
from backend.services.vector_store import knowledge_index


@dataclass
class Candidate:
    chunk_id: int
    semantic: float = 0.0
    keyword: float = 0.0  # normalised 0..1
    fused: float = 0.0
    rerank: float | None = None
    # filled from the DB
    text: str = ""
    document_id: int = 0
    title: str = ""
    source_type: str = ""
    url: str | None = None
    page: int | None = None
    section: str | None = None

    @property
    def relevance(self) -> float:
        """Best available relevance estimate: rerank if present, else fused."""
        return self.rerank if self.rerank is not None else self.fused


@dataclass
class RetrievalResult:
    query: str
    candidates: list[Candidate] = field(default_factory=list)  # final, ranked
    considered: int = 0
    retrieval_ms: float = 0.0
    rerank_ms: float = 0.0
    passed_gate: bool = False
    gate_reason: str = ""
    reranker: str = "none"
    ranked: list[Candidate] = field(default_factory=list)  # top_n before the gate
    timings: dict[str, float] = field(default_factory=dict)


def _allowed(chunk_id: int, conversation_id: str | None) -> bool:
    scope = knowledge_index.chunk_scope.get(chunk_id, "__missing__")
    if scope == "__missing__":
        return False  # chunk not ready / deleted
    return scope is None or scope == conversation_id


def _hydrate(cands: dict[int, Candidate]) -> None:
    if not cands:
        return
    with session_scope() as db:
        rows = db.execute(
            select(Chunk.id, Chunk.text, Chunk.page, Chunk.section, Document.id, Document.title,
                   Document.source_type, Document.source_url)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(list(cands)))
        ).all()
    for cid, text, page, section, did, title, stype, url in rows:
        c = cands[cid]
        c.text, c.page, c.section, c.document_id = text, page, section, did
        c.title, c.source_type, c.url = title, stype, url if (url or "").startswith("http") else None
    for cid in [cid for cid, c in cands.items() if not c.text]:  # vanished between search and hydrate
        cands.pop(cid)


def retrieve(query: str, conversation_id: str | None = None, *, mode: str = "hybrid",
             rerank: bool = True, top_n: int | None = None) -> RetrievalResult:
    """Run the retrieval pipeline. ``mode`` in {hybrid, semantic, keyword} supports ablations.

    ``res.timings`` holds per-stage wall-clock milliseconds (embed, semantic, keyword,
    fusion incl. DB hydration, rerank); ``res.ranked`` keeps the full ranked list
    before the relevance gate trims it, so ranking and filtering can be evaluated separately.
    """
    s = get_settings()
    top_n = top_n or s.rerank_top_n
    res = RetrievalResult(query=query)
    t = res.timings
    clock = time.perf_counter
    t0 = clock()
    knowledge_index.refresh_keyword_index()

    cands: dict[int, Candidate] = {}
    if mode in ("hybrid", "semantic") and knowledge_index.size:
        ts = clock()
        qv = get_embedder().embed_query(query)
        t["embed_ms"] = (clock() - ts) * 1000
        ts = clock()
        # Over-fetch so the scope filter can't starve the candidate list.
        n_sem = 0
        for cid, score in knowledge_index.faiss.search(qv, s.semantic_top_k * 3):
            if _allowed(cid, conversation_id):
                cands.setdefault(cid, Candidate(cid)).semantic = max(0.0, score)
                n_sem += 1
                if n_sem >= s.semantic_top_k:
                    break
        t["semantic_ms"] = (clock() - ts) * 1000
    if mode in ("hybrid", "keyword"):
        ts = clock()
        bm25, scope = knowledge_index.bm25, knowledge_index.chunk_scope  # consistent snapshot
        allowed = {cid for cid, conv in scope.items() if conv is None or conv == conversation_id}
        hits = bm25.search(query, s.keyword_top_k, allowed)
        top = hits[0][1] if hits else 1.0
        for cid, score in hits:
            cands.setdefault(cid, Candidate(cid)).keyword = score / top
        t["keyword_ms"] = (clock() - ts) * 1000

    ts = clock()
    w_sem, w_kw = s.hybrid_semantic_weight, s.hybrid_keyword_weight
    if mode == "semantic":
        w_sem, w_kw = 1.0, 0.0
    elif mode == "keyword":
        w_sem, w_kw = 0.0, 1.0
    for c in cands.values():
        c.fused = w_sem * c.semantic + w_kw * c.keyword
    _hydrate(cands)
    ranked = sorted(cands.values(), key=lambda c: c.fused, reverse=True)
    t["fusion_ms"] = (clock() - ts) * 1000
    res.considered = len(ranked)
    res.retrieval_ms = (clock() - t0) * 1000

    if rerank and ranked:
        rr = get_reranker()
        res.reranker = rr.name
        ts = clock()
        pool = ranked[:s.rerank_candidates]
        scores = rr.score(query, [c.text[:s.rerank_max_chars] for c in pool])
        res.rerank_ms = (clock() - ts) * 1000
        if scores:
            t["rerank_ms"] = res.rerank_ms
            for c, sc in zip(pool, scores):
                c.rerank = sc
            ranked = sorted(pool, key=lambda c: c.rerank, reverse=True)

    res.ranked = _diversify(ranked, s.max_chunks_per_section)[:top_n]
    res.candidates = list(res.ranked)
    _apply_gate(res, mode)
    return res


def _diversify(ranked: list[Candidate], cap: int) -> list[Candidate]:
    """Let at most ``cap`` chunks of one (document, section) through before other sections get a turn.

    Long sections (e.g. a 30-row report table) are split into many chunks that rank next to each other and can
    fill every top-k slot, crowding out the other places a broad question is answered. Extra chunks are
    deferred, never dropped, so a single-section answer still gets its full context. ``cap <= 0`` disables it.
    """
    if cap <= 0:
        return ranked
    seen: Counter = Counter()
    first, deferred = [], []
    for c in ranked:
        key = (c.document_id, c.section)
        (first if seen[key] < cap else deferred).append(c)
        seen[key] += 1
    return first + deferred


def _apply_gate(res: RetrievalResult, mode: str) -> None:
    """Decide whether the evidence is strong enough to answer at all."""
    s = get_settings()
    if not res.candidates:
        res.passed_gate, res.gate_reason = False, "no_candidates"
        return
    best = res.candidates[0]
    best_sem = max(c.semantic for c in res.candidates)
    if best.rerank is not None:
        supporting = [c for c in res.candidates if (c.rerank or 0) >= s.min_context_rerank_score]
        ok = best.rerank >= s.min_rerank_score and best_sem >= s.min_semantic_score * 0.5
        reason = "low_rerank_score"
    elif mode == "keyword":
        supporting = [c for c in res.candidates if c.keyword > 0]
        ok, reason = bool(supporting), "no_keyword_match"
    else:
        supporting = [c for c in res.candidates if c.semantic >= s.min_semantic_score]
        ok, reason = best_sem >= s.min_semantic_score, "low_semantic_score"
    if ok and len(supporting) < s.min_support_chunks:
        ok, reason = False, "insufficient_support"
    res.passed_gate = ok
    res.gate_reason = "" if ok else reason
    if ok:
        # Drop chunks that individually fail the bar: they would only add noise to the prompt.
        res.candidates = supporting
