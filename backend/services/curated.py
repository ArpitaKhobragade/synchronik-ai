"""Curated knowledge-base documents kept in the repository (``backend/knowledge/*.html``).

These answer general questions the help portal does not cover well (what Synchronik is, its products, how the
ERP works at a high level). Each file is ingested like a crawled page: split on headings, embedded and indexed,
and skipped when its content hash is unchanged. They are loaded at startup and by the admin crawl, so a fresh
deployment gets them without a manual upload.
"""
from __future__ import annotations

from pathlib import Path

from backend.core.logging import log_event
from backend.services.document_processing import extract_html
from backend.services.ingestion import upsert_web_page

KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "knowledge"


def load_curated() -> dict[str, int]:
    """Ingest every curated document; returns counts per action (created / updated / unchanged)."""
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    for path in sorted(KNOWLEDGE_DIR.glob("*.html")):
        title, sections = extract_html(path.read_text(encoding="utf-8"))
        action, _ = upsert_web_page(f"kb://{path.stem}", title or path.stem, sections, "curated")
        counts[action] += 1
    log_event("curated_loaded", **counts)
    return counts
