"""Multimodal Q&A over an uploaded image (screenshots of ERP screens, notices, timetables).

The image is validated (magic bytes, size, Pillow decode check) and handled in memory: it is never
written to disk.

The model first reads the image (visible text and the kind of screen). That reading plus the question is searched
in the documentation, so "what does this error mean and how do I fix it?" gets the help-portal steps for the error
on screen; the final answer sees the image and those pages together.
"""
from __future__ import annotations

import io
import time

from PIL import Image

from backend.core.errors import UnsupportedFile
from backend.core.logging import log_event
from backend.core.security import IMAGE_MIME
from backend.services import context_builder as cb
from backend.services import conversations as convs
from backend.services.llm import get_llm
from backend.services.retrieval import retrieve

IMAGE_DOC_CHUNKS = 4


def verify_image(data: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedFile("The image could not be decoded.") from exc
    if w * h > 40_000_000:
        raise UnsupportedFile("The image resolution is too large.")
    return w, h


def answer_image(data: bytes, kind: str, filename: str, question: str, conversation_id: str | None) -> dict:
    from backend.services.rag_pipeline import source_payload

    t0 = time.perf_counter()
    verify_image(data)
    llm = get_llm(required=True)
    conv_id = convs.ensure_conversation(conversation_id)
    convs.add_message(conv_id, "user", question, attachment={"name": filename, "kind": "image"})
    mime = IMAGE_MIME[kind]

    # 1. Read the image, 2. find documentation for what it shows, 3. answer with both.
    reading = llm.describe_image(cb.IMAGE_SYSTEM_PROMPT, cb.IMAGE_READ_PROMPT, data, mime)
    res = retrieve(f"{question}\n{reading[:800]}", conv_id)
    cands = cb.select_context(res.candidates, question)[:IMAGE_DOC_CHUNKS] if res.passed_gate else []
    prompt = cb.sanitize_untrusted(question)
    if cands:
        prompt = f"{cb.build_sources_block(cands, question)}\n\nQuestion about the image: {prompt}"
    text = llm.describe_image(cb.IMAGE_SYSTEM_PROMPT, prompt, data, mime)
    text = cb.guard_output(cb.strip_invalid_citations(text, len(cands)))
    ids = cb.cited_ids(text, len(cands))
    sources = [source_payload(i, cands[i - 1]) for i in ids]
    llm_ms = (time.perf_counter() - t0) * 1000
    log_event("image_answered", conversation_id=conv_id, doc_chunks=len(cands), cited=len(ids),
              llm_ms=round(llm_ms, 1))

    confidence = {"score": 0.0, "level": "none", "label": "Image analysis",
                  "explanation": "Answer is based on the uploaded image" + (" and documentation." if ids else "."),
                  "signals": {"top_score": 0.0, "support_chunks": len(ids), "score_margin": 0.0,
                              "source_agreement": 0.0}}
    metadata = {"model": llm.vision_model if hasattr(llm, "vision_model") else llm.model,
                "retrieval_ms": round(res.retrieval_ms, 1), "rerank_ms": round(res.rerank_ms, 1),
                "llm_ms": round(llm_ms, 1), "candidates": res.considered, "reranker": res.reranker,
                "documents_considered": len({c.document_id for c in cands})}
    msg_id = convs.add_message(conv_id, "assistant", text, sources=sources, confidence=confidence,
                               meta={**metadata, "intent": "image_question", "latency_ms": round(llm_ms),
                                     "grounded": bool(ids)})
    return {"answer": text, "response": text, "sources": sources, "confidence": confidence,
            "retrieval_count": len(cands), "latency_ms": round(llm_ms), "conversation_id": conv_id,
            "session_id": conv_id, "query_id": "", "message_id": msg_id, "intent": "image_question",
            "rewritten_query": None, "grounded": bool(ids), "metadata": metadata}
