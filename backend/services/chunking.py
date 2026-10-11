"""Structure-aware chunking.

Fixed-size cuts split words and sentences and lose position information. This splitter:

* respects paragraph → sentence → word boundaries (recursive splitting),
* adds a configurable overlap so facts on a boundary survive in one chunk,
* keeps the page number (PDF) and nearest heading (DOCX/HTML) per chunk so
  citations can point at "p. 4" or "Attendance › Configuration".
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Section:
    """A unit of extracted text with its location metadata."""

    text: str
    page: int | None = None
    heading: str | None = None


@dataclass
class ChunkDraft:
    text: str
    page: int | None
    section: str | None


_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]


def _normalise(text: str) -> str:
    # NUL bytes (seen in some PDF extractions) are rejected by PostgreSQL text columns.
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\u00a0", " ")  # NBSP -> space
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split(text: str, size: int, seps: list[str]) -> list[str]:
    if len(text) <= size:
        return [text]
    for i, sep in enumerate(seps):
        if sep in text:
            parts = text.split(sep)
            out: list[str] = []
            for j, p in enumerate(parts):
                piece = p + (sep if j < len(parts) - 1 else "")
                if len(piece) > size:
                    out.extend(_split(piece, size, seps[i + 1:]))
                elif piece:
                    out.append(piece)
            return out
    return [text[k:k + size] for k in range(0, len(text), size)]  # no separator at all


def split_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    """Pack boundary-respecting pieces into chunks of ~chunk_size with overlap."""
    text = _normalise(text)
    if not text:
        return []
    pieces = _split(text, chunk_size, _SEPARATORS)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > chunk_size:
            chunks.append(current.strip())
            tail = current[-overlap:] if overlap else ""
            # start the overlap on a word boundary
            if " " in tail:
                tail = tail[tail.index(" ") + 1:]
            current = tail + piece
        else:
            current += piece
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if len(c) >= 20 or len(chunks) == 1]


def chunk_sections(sections: list[Section], chunk_size: int = 900, overlap: int = 150) -> list[ChunkDraft]:
    """Chunk each section independently so a chunk never spans two pages/headings."""
    drafts: list[ChunkDraft] = []
    for sec in sections:
        for piece in split_text(sec.text, chunk_size, overlap):
            body = f"{sec.heading}\n{piece}" if sec.heading and not piece.startswith(sec.heading) else piece
            drafts.append(ChunkDraft(text=body, page=sec.page, section=sec.heading))
    return drafts
