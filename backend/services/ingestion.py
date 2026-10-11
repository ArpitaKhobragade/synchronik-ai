"""Document ingestion: extract → chunk → embed → store → index.

Shared by uploads, chat attachments, the crawler and reprocessing so every
source goes through exactly the same pipeline. Status transitions
(pending → processing → ready | failed) are persisted so the admin UI never
claims success before the vectors are actually searchable.
"""
from __future__ import annotations

import hashlib
import time

from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.logging import log_event
from backend.db.models import Chunk, Document, utcnow
from backend.db.session import session_scope
from backend.services.chunking import Section, chunk_sections
from backend.services.document_processing import ExtractionError, extract
from backend.services.embeddings import get_embedder, to_bytes
from backend.services.vector_store import knowledge_index


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sections_text(sections: list[Section]) -> str:
    return "\n\n".join(s.text for s in sections).replace("\x00", "")


def index_document(document_id: int, sections: list[Section]) -> int:
    """(Re)build chunks + embeddings for a document and update the live index."""
    s = get_settings()
    t0 = time.perf_counter()
    embedder = get_embedder()
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            raise ValueError(f"document {document_id} not found")
        doc.status = "processing"
        old_ids = [c.id for c in doc.chunks]
        title = doc.title
    knowledge_index.remove(old_ids)

    try:
        drafts = chunk_sections(sections, s.chunk_size, s.chunk_overlap)
        if not drafts:
            raise ExtractionError("No text could be extracted from this document.")
        # The title is prepended for embedding only: it disambiguates short help-page chunks.
        vectors = embedder.embed([f"{title}\n{d.text}" for d in drafts])
        with session_scope() as db:
            doc = db.get(Document, document_id)
            for c in list(doc.chunks):
                db.delete(c)
            db.flush()
            new_chunks = [
                Chunk(document_id=document_id, chunk_index=i, text=d.text, page=d.page,
                      section=d.section, embedding=to_bytes(vectors[i]), embedding_model=embedder.name)
                for i, d in enumerate(drafts)
            ]
            db.add_all(new_chunks)
            db.flush()
            ids = [c.id for c in new_chunks]
            doc.status, doc.error, doc.updated_at = "ready", None, utcnow()
        knowledge_index.add(ids, vectors)
    except Exception as exc:
        with session_scope() as db:
            doc = db.get(Document, document_id)
            if doc is not None:
                doc.status = "failed"
                doc.error = str(exc) if isinstance(exc, ExtractionError) else "Processing failed."
        log_event("ingest_failed", document_id=document_id, error=type(exc).__name__)
        raise
    log_event("ingest_done", document_id=document_id, chunks=len(ids),
              ms=round((time.perf_counter() - t0) * 1000, 1))
    return len(ids)


def ingest_file(data: bytes, kind: str, title: str, mime: str, *, source_type: str = "upload",
                conversation_id: str | None = None) -> tuple[int, int]:
    """Create a document from an uploaded file. Returns ``(document_id, chunk_count)``."""
    sections = extract(data, kind)  # raises ExtractionError before anything is stored
    text = _sections_text(sections)
    with session_scope() as db:
        doc = Document(title=title, source_type=source_type, mime_type=mime, content=text,
                       content_hash=content_hash(text), status="pending", conversation_id=conversation_id,
                       raw_bytes=data)
        db.add(doc)
        db.flush()
        doc_id = doc.id
    return doc_id, index_document(doc_id, sections)


def upsert_web_page(url: str, title: str, sections: list[Section], source_type: str) -> tuple[str, int | None]:
    """Insert or update a crawled page. Unchanged pages (same content hash) are skipped.

    Returns ``(action, document_id)`` where action is created | updated | unchanged.
    """
    text = _sections_text(sections)
    digest = content_hash(text)
    with session_scope() as db:
        doc = db.scalar(select(Document).where(Document.source_url == url, Document.conversation_id.is_(None)))
        if doc is not None and doc.content_hash == digest and doc.status == "ready":
            doc.last_crawled_at = utcnow()
            return "unchanged", doc.id
        action = "updated" if doc is not None else "created"
        if doc is None:
            doc = Document(source_url=url, source_type=source_type, mime_type="text/html")
            db.add(doc)
        doc.title, doc.content, doc.content_hash = title[:300], text, digest
        doc.status, doc.last_crawled_at = "pending", utcnow()
        db.flush()
        doc_id = doc.id
    index_document(doc_id, sections)
    return action, doc_id


def reprocess_document(document_id: int) -> int:
    """Re-chunk and re-embed a document (e.g. after changing chunk size or embedding model)."""
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            raise ValueError("not found")
        raw, mime, content = doc.raw_bytes, doc.mime_type, doc.content
    if raw is not None and mime:
        kind = "pdf" if "pdf" in mime else "docx"
        sections = extract(raw, kind)
    elif mime == "text/html":
        sections = [Section(text=p) for p in content.split("\n\n") if p.strip()]
    else:
        sections = [Section(text=content)]
    return index_document(document_id, sections)


def delete_document(document_id: int) -> bool:
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return False
        ids = [c.id for c in doc.chunks]
        db.delete(doc)
    knowledge_index.remove(ids)
    return True
