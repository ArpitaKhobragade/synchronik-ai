"""Knowledge-base documents (public read, admin write) and retrieval-only search."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select

from backend.api.schemas import DocumentOut
from backend.core.config import get_settings
from backend.core.errors import BadRequest, NotFound
from backend.core.security import DOC_KINDS, DOC_MIME, rate_limit_chat, read_upload, require_admin, safe_display_name
from backend.db.models import Chunk, Document
from backend.db.session import session_scope
from backend.services.document_processing import ExtractionError
from backend.services.ingestion import delete_document, ingest_file, reprocess_document
from backend.services.rag_pipeline import source_payload
from backend.services.retrieval import retrieve

router = APIRouter(prefix="/api", tags=["knowledge base"])


def _out(doc: Document, n: int) -> dict:
    return {"id": doc.id, "title": doc.title, "source_type": doc.source_type, "source_url": doc.source_url,
            "status": doc.status, "error": doc.error, "chunk_count": n, "mime_type": doc.mime_type,
            "created_at": doc.created_at, "updated_at": doc.updated_at, "last_crawled_at": doc.last_crawled_at}


def document_out(doc_id: int) -> dict:
    with session_scope() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            raise NotFound("Document not found.")
        n = db.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == doc_id)) or 0
        return _out(doc, n)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents():
    with session_scope() as db:
        counts = (select(Chunk.document_id, func.count(Chunk.id).label("n")).group_by(Chunk.document_id).subquery())
        rows = db.execute(
            select(Document, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.document_id == Document.id)
            .where(Document.conversation_id.is_(None)).order_by(Document.updated_at.desc())
        ).all()
        return [_out(d, n) for d, n in rows]


@router.post("/documents", dependencies=[Depends(require_admin)], status_code=201)
async def upload_document(file: UploadFile = File(...)):
    data, kind = await read_upload(file, get_settings().max_document_mb, DOC_KINDS)
    try:
        doc_id, chunks = await run_in_threadpool(ingest_file, data, kind, safe_display_name(file.filename),
                                                 DOC_MIME[kind], source_type="upload")
    except ExtractionError as exc:
        raise BadRequest(str(exc), code="extraction_failed") from exc
    return {"document": document_out(doc_id), "chunks": chunks,
            "message": "Document processed successfully and added to the knowledge base."}


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_admin)], status_code=204)
def remove_document(doc_id: int):
    if not delete_document(doc_id):
        raise NotFound("Document not found.")
    return Response(status_code=204)


@router.post("/documents/{doc_id}/reprocess", dependencies=[Depends(require_admin)])
def reprocess(doc_id: int):
    try:
        chunks = reprocess_document(doc_id)
    except ValueError as exc:
        raise NotFound("Document not found.") from exc
    except ExtractionError as exc:
        raise BadRequest(str(exc), code="extraction_failed") from exc
    return {"document": document_out(doc_id), "chunks": chunks}


@router.get("/search", dependencies=[Depends(rate_limit_chat)])
def search(q: str = Query(..., min_length=1, max_length=500), k: int = Query(5, ge=1, le=20)):
    """Retrieval only (no LLM) — useful for debugging relevance."""
    t0 = time.perf_counter()
    res = retrieve(q, None, top_n=k)
    return {"query": q, "passed_gate": res.passed_gate,
            "results": [source_payload(i, c) for i, c in enumerate(res.candidates, start=1)],
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
