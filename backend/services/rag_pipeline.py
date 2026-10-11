"""The RAG orchestrator.

    query → understand/rewrite → hybrid retrieve → rerank → relevance gate
          → context compression → grounded generation (streamed) → citations
          → evidence-based confidence → persist message + query log

``run_events`` is a generator of (event, payload) tuples; the streaming
endpoint forwards them as SSE and the JSON endpoint just drains them, so both
share one code path and identical behaviour.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import replace

from backend.core.config import get_settings
from backend.core.errors import AppError, LLMUnavailable, RateLimited
from backend.core.logging import fingerprint, log_event
from backend.db.models import QueryLog, new_uuid
from backend.db.session import session_scope
from backend.services import context_builder as cb
from backend.services import conversations as convs
from backend.services.confidence import compute_confidence
from backend.services.llm import ChatTurn, get_llm
from backend.services.query_understanding import analyze
from backend.services.retrieval import Candidate, RetrievalResult, retrieve

STAGES = {
    "understanding": "Understanding your question…",
    "retrieving": "Retrieving documentation…",
    "reranking": "Ranking the most relevant sources…",
    "generating": "Generating answer…",
}


def source_payload(n: int, c: Candidate) -> dict:
    return {
        "id": n, "chunk_id": c.chunk_id, "document_id": c.document_id, "title": c.title,
        "source_type": c.source_type, "url": c.url, "page": c.page, "section": c.section,
        "score": round(c.fused, 3), "rerank_score": round(c.rerank, 3) if c.rerank is not None else None,
        "snippet": c.text[:400],
    }


NO_KEY_NOTE = "_AI-written answers are not enabled on this server, so no answer was generated. "
LLM_DOWN_NOTE = "_The AI model is unavailable right now (its usage limit may have been reached), so no answer was generated. "


OUT_OF_SCOPE_REPLY = (f"{cb.REFUSAL}\n\nI only answer from Synchronik ERP documentation, and nothing "
                      "relevant enough matched this question. Try rephrasing with the module name "
                      "(e.g. *attendance*, *examination*, *library*), or attach a document that covers it.")
# General-answer mode replies when no answer could be generated. They never say "not in the documentation".
NO_ANSWER_REPLY = ("I don't have the exact details for this. Your college administrator or Synchronik support "
                   "(+91 92252 48454, info@synchronik.co.in) can help, or try asking with the module name "
                   "(e.g. *attendance*, *examination*, *library*).")
LLM_DOWN_REPLY = ("The AI model is unavailable right now (its usage limit may have been reached), so I couldn't "
                  "answer this. Please try again in a little while.")
# General answers are shown without a label (product decision, 2026-10-10); the API still marks them
# with intent "general" and no sources, so clients and evaluations can tell them apart.
GENERAL_NOTE = ""


def _norm(text: str) -> str:
    return " ".join(text.replace("’", "'").lower().split())
GENERAL_CONFIDENCE = {
    "score": 0.0, "level": "none", "label": "General knowledge",
    "explanation": "Not from Synchronik documentation",
    "signals": {"top_score": 0.0, "support_chunks": 0, "score_margin": 0.0, "source_agreement": 0.0},
}


def _general_answer(llm, message: str, history: list[dict], conv_id: str, user_msg_id: int,
                    query_id: str) -> Iterator[tuple[str, dict]]:
    """Answer a question that matched no documentation from the model's general knowledge.

    The model is told to reply with the exact refusal sentence for questions about the ERP itself, so undocumented
    ERP features are never invented. The opening text is held back until it is clear whether the reply is that
    refusal (replaced by NO_ANSWER_REPLY) or a real answer (released through the stream guard).
    Returns the final answer text (generator ``return`` value).
    """
    turns = [ChatTurn("user" if m["role"] == "user" else "model", m["content"]) for m in history]
    turns.append(ChatTurn("user", cb.sanitize_untrusted(message)))
    guard = cb.StreamGuard()
    parts: list[str] = []
    started = False  # has any of the answer been released yet?

    def release(text: str) -> Iterator[tuple[str, dict]]:
        safe = guard.feed(text)
        if safe:
            yield "token", {"text": safe}

    refusal = _norm(cb.REFUSAL)[:40]
    try:
        for piece in llm.stream(cb.GENERAL_SYSTEM_PROMPT, turns):
            parts.append(piece)
            if started:
                yield from release(piece)
                continue
            head = _norm("".join(parts))
            if len(head) < len(refusal) and refusal.startswith(head):
                continue  # could still turn into the refusal sentence: wait for more text
            if head.startswith(refusal):
                continue  # the model declined: an ERP question the docs don't cover
            started = True
            yield from release(GENERAL_NOTE + "".join(parts))
        if not started:
            head = _norm("".join(parts))
            if not head or head.startswith(refusal) or refusal.startswith(head):
                yield "token", {"text": NO_ANSWER_REPLY}
                return NO_ANSWER_REPLY
            started = True
            yield from release(GENERAL_NOTE + "".join(parts))
        tail = guard.flush()
        if tail:
            yield "token", {"text": tail}
    except GeneratorExit:
        if started:
            _save_stopped(conv_id, user_msg_id, GENERAL_NOTE + "".join(parts), [], GENERAL_CONFIDENCE, llm.model,
                          query_id)
        raise
    except (RateLimited, LLMUnavailable) as exc:
        if parts:
            raise
        log_event("llm_fallback", query_id=query_id, code=exc.code)
        yield "token", {"text": LLM_DOWN_REPLY}
        return LLM_DOWN_REPLY
    answer = GENERAL_NOTE + "".join(parts).strip()
    if guard.tripped or cb.guard_output(answer) != answer:
        return NO_ANSWER_REPLY  # the leak guard blocked it: never return the blocked text, nor "not documented"
    return answer


# Attachments up to this many characters (all of a conversation's documents together) go to the model whole, so
# summaries and "who issued it?" work; longer ones are cut to their opening and the passages that match the question.
ATTACHMENT_FULL_CHARS = 24_000
ATTACHMENT_EXCERPT_CHARS = 14_000
# Help-portal chunks added next to an attachment, when the question also matches the documentation.
ATTACHMENT_DOC_CHUNKS = 4


def _attachment_sources(conv_id: str, query: str) -> list[Candidate]:
    """One source per attached document, holding its full text or, for long documents, the relevant excerpts."""
    docs = convs.attachment_documents(conv_id)
    if not docs:
        return []
    total = sum(len(c["text"]) for d in docs for c in d["chunks"])
    ranked: list[int] = []
    if total > ATTACHMENT_FULL_CHARS:
        res = retrieve(query, conv_id, rerank=False, top_n=60)
        ranked = [c.chunk_id for c in res.ranked if c.source_type == "attachment"]
    out = []
    budget = ATTACHMENT_EXCERPT_CHARS // len(docs)
    for d in docs:
        chunks = d["chunks"]
        if total > ATTACHMENT_FULL_CHARS:
            by_id = {c["id"]: c for c in chunks}
            keep, used = [], 0
            for cid in [chunks[0]["id"]] + [i for i in ranked if i in by_id]:  # the opening, then best matches
                if cid in keep or used + len(by_id[cid]["text"]) > budget and keep:
                    continue
                keep.append(cid)
                used += len(by_id[cid]["text"])
            chunks = sorted((by_id[i] for i in keep), key=lambda c: c["index"])
        text, prev = "", None
        for c in chunks:
            gap = prev is not None and c["index"] != prev + 1
            text += ("\n[…]\n" if gap else "\n") + c["text"]
            prev = c["index"]
        out.append(Candidate(chunk_id=chunks[0]["id"], text=text.strip(), document_id=d["id"], title=d["title"],
                             source_type="attachment", fused=1.0, page=None))
    return out


def _extractive_answer(cands: list[Candidate], note: str = NO_KEY_NOTE) -> str:
    """Used when the LLM is not configured or is unavailable: show the evidence instead of inventing prose."""
    lines = [note + "Here are the most relevant documentation excerpts:_", ""]
    for n, c in enumerate(cands[:3], start=1):
        excerpt = " ".join(c.text.split())[:350]
        lines.append(f"> {excerpt}… [{n}]")
        lines.append("")
    return "\n".join(lines)


def run_events(message: str, conversation_id: str | None) -> Iterator[tuple[str, dict]]:
    t0 = time.perf_counter()
    query_id = new_uuid()
    conv_id = convs.ensure_conversation(conversation_id)
    history = convs.history_window(conv_id)
    user_msg_id = convs.add_message(conv_id, "user", message)

    yield "status", {"stage": "understanding", "label": STAGES["understanding"]}
    timings: dict[str, float] = {}
    ts = time.perf_counter()
    has_attachments = convs.has_attachments(conv_id)
    qa = analyze(message, history, has_attachments)
    if has_attachments and qa.intent == "ambiguous":
        # With a document attached, a vague "what is it about?" refers to the document: answer, don't ask back.
        qa = replace(qa, intent="attachment_question", needs_retrieval=True)
    timings["understanding_ms"] = (time.perf_counter() - ts) * 1000

    res: RetrievalResult | None = None
    cands: list[Candidate] = []
    attachments: list[Candidate] = []
    grounded = False
    error: str | None = None
    llm_ms = 0.0
    model: str | None = None

    try:
        if qa.needs_retrieval:
            yield "status", {"stage": "retrieving", "label": STAGES["retrieving"]}
            res = retrieve(qa.retrieval_query, conv_id)
            timings.update(res.timings)
            yield "status", {"stage": "reranking", "label": STAGES["reranking"]}
            if res.passed_gate:
                cands = cb.select_context(res.candidates, qa.retrieval_query)
                grounded = True
        if has_attachments and qa.intent != "greeting":
            # Every question in a conversation with a document sees that document, whether or not retrieval
            # matched it; help-portal pages are added when the question also matches them (not for questions that
            # explicitly point at the document, like "summarise this document").
            attachments = _attachment_sources(conv_id, qa.retrieval_query)
            if attachments:
                docs = [] if qa.intent == "attachment_question" else [
                    c for c in cands if c.source_type != "attachment"][:ATTACHMENT_DOC_CHUNKS]
                cands, grounded = attachments + docs, True

        all_sources = [source_payload(n, c) for n, c in enumerate(cands, start=1)]
        confidence = compute_confidence(res, grounded)
        intent = qa.intent if (grounded or qa.intent in ("greeting", "ambiguous")) else "out_of_scope"
        if attachments:
            intent = "attachment_question"
        # No documentation match: answer from the model's general knowledge (labelled, uncited) when enabled.
        general_llm = get_llm(required=False) if (not grounded and intent == "out_of_scope"
                                                  and get_settings().general_answers) else None
        if general_llm is not None:
            intent, confidence = "general", GENERAL_CONFIDENCE
        yield "meta", {"conversation_id": conv_id, "query_id": query_id, "sources": all_sources,
                       "confidence": confidence, "retrieval_count": len(cands), "intent": intent,
                       "rewritten_query": qa.retrieval_query if qa.rewritten else None, "grounded": grounded}

        if qa.intent == "greeting":
            answer = cb.GREETING_REPLY
            yield "token", {"text": answer}
        elif qa.intent == "ambiguous":
            answer = cb.CLARIFY_REPLY
            yield "token", {"text": answer}
        elif general_llm is not None:
            yield "status", {"stage": "generating", "label": STAGES["generating"]}
            model = general_llm.model
            t1 = time.perf_counter()
            answer = yield from _general_answer(general_llm, message, history, conv_id, user_msg_id, query_id)
            llm_ms = (time.perf_counter() - t1) * 1000
            timings["llm_ms"] = llm_ms
            if answer in (NO_ANSWER_REPLY, LLM_DOWN_REPLY):  # no general answer was generated
                intent, confidence = "out_of_scope", compute_confidence(res, False)
        elif not grounded:
            answer = OUT_OF_SCOPE_REPLY
            yield "token", {"text": answer}
        else:
            yield "status", {"stage": "generating", "label": STAGES["generating"]}
            llm = get_llm(required=False)
            if llm is None:
                answer = _extractive_answer(cands)
                model = "extractive-fallback"
                yield "token", {"text": answer}
            else:
                model = llm.model
                turns = [ChatTurn("user" if m["role"] == "user" else "model", m["content"]) for m in history]
                ts = time.perf_counter()
                question = message if not qa.rewritten else f"{message}\n(Interpreted as: {qa.retrieval_query})"
                if attachments:
                    # The user's own words, not the rewrite: the model sees the conversation and the whole document,
                    # and a rewrite can pin "it" to the wrong thing ("who issued it?" → "who issues hall tickets?").
                    system = cb.ATTACHMENT_SYSTEM_PROMPT
                    block = cb.build_mixed_sources_block(attachments, cands[len(attachments):], qa.retrieval_query)
                    turns.append(ChatTurn("user", f"{block}\n\nQuestion: {cb.sanitize_untrusted(message)}"))
                else:
                    system = cb.SYSTEM_PROMPT
                    turns.append(ChatTurn("user", cb.build_user_turn(
                        question, cb.build_sources_block(cands, qa.retrieval_query))))
                timings["context_ms"] = (time.perf_counter() - ts) * 1000
                t1 = time.perf_counter()
                parts: list[str] = []
                guard = cb.StreamGuard()  # tokens reach the client only after the leak check has seen them
                # With general answers on, a reply that turns out to be the refusal sentence is never shown: the
                # question is handed to the general path instead. So hold the opening text until it's clear.
                # (The attachment prompt has no refusal sentence: it answers from general knowledge itself.)
                deciding = get_settings().general_answers and not attachments
                declined = False
                refusal = _norm(cb.REFUSAL)[:40]
                try:
                    for piece in llm.stream(system, turns):
                        if not parts:
                            timings["llm_first_token_ms"] = (time.perf_counter() - t1) * 1000
                        parts.append(piece)
                        if deciding:
                            head = _norm("".join(parts))
                            if refusal.startswith(head) or head.startswith(refusal):
                                continue  # still undecided, or declining
                            deciding = False
                            piece = "".join(parts)
                        safe = guard.feed(piece)
                        if safe:
                            yield "token", {"text": safe}
                    if deciding:  # the stream ended while still looking like the refusal
                        declined = True
                    else:
                        tail = guard.flush()
                        if tail:
                            yield "token", {"text": tail}
                except GeneratorExit:
                    # The client pressed Stop (disconnected): keep what was generated so history matches the UI.
                    _save_stopped(conv_id, user_msg_id, "".join(parts), all_sources[:3], confidence, model, query_id)
                    raise
                except (RateLimited, LLMUnavailable) as exc:
                    if parts:  # failed mid-answer: surface the error rather than return half an answer
                        raise
                    # Quota exhausted / provider down before any text: the retrieved evidence is still valid,
                    # so return it as clearly labelled excerpts instead of failing the whole request.
                    log_event("llm_fallback", query_id=query_id, code=exc.code)
                    model = "extractive-fallback"
                    parts = [_extractive_answer(cands, LLM_DOWN_NOTE)]
                    yield "token", {"text": parts[0]}
                if declined:
                    # The documents matched loosely but don't answer the question (e.g. "how does this chatbot
                    # work?"): answer it like any question without a documentation match.
                    grounded, intent, confidence = False, "general", GENERAL_CONFIDENCE
                    answer = yield from _general_answer(llm, message, history, conv_id, user_msg_id, query_id)
                    if answer in (NO_ANSWER_REPLY, LLM_DOWN_REPLY):  # no general answer was generated
                        intent, confidence = "out_of_scope", compute_confidence(res, False)
                    llm_ms = (time.perf_counter() - t1) * 1000
                    timings["llm_ms"] = llm_ms
                else:
                    llm_ms = (time.perf_counter() - t1) * 1000
                    timings["llm_ms"] = llm_ms
                    answer = cb.guard_output(cb.strip_invalid_citations("".join(parts).strip(), len(cands)))
                    if not answer or cb.is_refusal(answer):
                        grounded = False
                        answer = answer or cb.REFUSAL

        # Only sources the answer actually cites are returned; if the model cited none,
        # the context sources are shown (they are what the answer was generated from).
        if grounded:
            ids = cb.cited_ids(answer, len(cands))
            if ids:
                sources = [all_sources[i - 1] for i in ids]
            else:  # with an attachment, an uncited answer came from general knowledge (e.g. a drafted message)
                sources = [] if attachments else all_sources[:3]
        else:
            sources = []
        if intent != "general":  # a general answer keeps its "General knowledge" label
            confidence = compute_confidence(res, grounded)
        if not grounded and qa.intent not in ("greeting", "ambiguous") and intent != "general":
            intent = "out_of_scope"
    except AppError as exc:
        error = exc.code
        log_event("chat_failed", query_id=query_id, code=exc.code)
        _log_query(query_id, conv_id, None, message, qa, res, grounded=False, llm_ms=llm_ms,
                   total_ms=(time.perf_counter() - t0) * 1000, model=model, error=error)
        yield "error", {"code": exc.code, "message": exc.message}
        return

    total_ms = (time.perf_counter() - t0) * 1000
    timings["total_ms"] = total_ms
    timings = {k: round(v, 1) for k, v in timings.items()}
    metadata = {
        "model": model, "retrieval_ms": round(res.retrieval_ms if res else 0, 1),
        "rerank_ms": round(res.rerank_ms if res else 0, 1), "llm_ms": round(llm_ms, 1),
        "candidates": res.considered if res else 0, "reranker": res.reranker if res else "none",
        "documents_considered": len({c.document_id for c in cands}),
        "timings": timings,
    }
    msg_id = convs.add_message(conv_id, "assistant", answer, sources=sources, confidence=confidence,
                               meta={**metadata, "intent": intent, "latency_ms": round(total_ms),
                                     "rewritten_query": qa.retrieval_query if qa.rewritten else None,
                                     "retrieval_count": len(cands), "grounded": grounded},
                               query_id=query_id)
    _log_query(query_id, conv_id, msg_id, message, qa, res, grounded=grounded, llm_ms=llm_ms,
               total_ms=total_ms, model=model, confidence=confidence["score"], chunk_ids=[c.chunk_id for c in cands],
               timings=timings)
    log_event("chat_answered", query_id=query_id, conversation_id=conv_id, intent=intent, grounded=grounded,
              q_hash=fingerprint(message), q_len=len(message), chunks=[c.chunk_id for c in cands],
              retrieval_ms=metadata["retrieval_ms"], rerank_ms=metadata["rerank_ms"],
              llm_ms=metadata["llm_ms"], total_ms=round(total_ms, 1), model=model)
    yield "done", {
        "answer": answer, "response": answer, "sources": sources, "confidence": confidence,
        "retrieval_count": len(cands), "latency_ms": round(total_ms), "conversation_id": conv_id,
        "session_id": conv_id, "query_id": query_id, "message_id": msg_id, "intent": intent,
        "rewritten_query": qa.retrieval_query if qa.rewritten else None, "grounded": grounded,
        "metadata": metadata,
    }


def answer(message: str, conversation_id: str | None) -> dict:
    """Non-streaming variant: drain the event stream and return the final payload."""
    for event, payload in run_events(message, conversation_id):
        if event == "done":
            return payload
        if event == "error":
            raise AppError(payload["message"], code=payload["code"],
                           status_code=429 if payload["code"] == "rate_limited" else 503)
    raise AppError()


STOPPED_NOTE = "\n\n_Generation stopped._"


def _save_stopped(conv_id, user_msg_id, partial, sources, confidence, model, query_id) -> None:
    """Persist a partial answer after Stop, unless the exchange was already replaced (e.g. by a regenerate)."""
    partial = cb.guard_output(partial.strip())
    try:
        if not partial or convs.last_message_id(conv_id) != user_msg_id:
            return
        convs.add_message(conv_id, "assistant", partial + STOPPED_NOTE, sources=sources, confidence=confidence,
                          meta={"model": model, "stopped": True, "grounded": True}, query_id=query_id)
        log_event("chat_stopped", query_id=query_id, conversation_id=conv_id, chars=len(partial))
    except Exception as exc:  # noqa: BLE001 - runs during generator close; must never raise
        log_event("chat_stop_save_failed", error=type(exc).__name__)


def _log_query(query_id, conv_id, msg_id, message, qa, res, *, grounded, llm_ms, total_ms, model,
               confidence=None, chunk_ids=None, error=None, timings=None) -> None:
    try:
        with session_scope() as db:
            db.add(QueryLog(
                id=query_id, conversation_id=conv_id, message_id=msg_id, query=message[:2000],
                rewritten_query=qa.retrieval_query if qa.rewritten else None,
                intent=qa.intent if (grounded or qa.intent in ("greeting", "ambiguous")) else "out_of_scope",
                grounded=grounded, retrieval_count=len(chunk_ids or []),
                top_score=res.candidates[0].relevance if res and res.candidates else None,
                confidence=confidence, retrieval_ms=res.retrieval_ms if res else 0,
                rerank_ms=res.rerank_ms if res else 0, llm_ms=llm_ms, total_ms=total_ms,
                model=model, chunk_ids=chunk_ids, error=error, timings=timings))
    except Exception as exc:  # noqa: BLE001 - analytics must never break chat
        log_event("query_log_failed", error=type(exc).__name__)
