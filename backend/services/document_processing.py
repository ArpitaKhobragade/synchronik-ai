"""Text extraction for PDF, DOCX and HTML into location-aware ``Section`` lists.

PDFs keep page numbers, DOCX keeps heading hierarchy and table rows, HTML drops
navigation/scripts and splits on h1–h3 headings. Everything works on bytes in
memory — nothing is written to disk.
"""
from __future__ import annotations

import io
import re

from bs4 import BeautifulSoup

from backend.services.chunking import Section


class ExtractionError(Exception):
    pass


def extract_pdf(data: bytes) -> list[Section]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("Encrypted PDFs are not supported.")
        sections = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                sections.append(Section(text=text, page=i))
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - malformed/malicious PDFs
        raise ExtractionError("The PDF could not be read.") from exc
    if not sections:
        raise ExtractionError("No extractable text found (the PDF may be scanned images).")
    return sections


def extract_docx(data: bytes) -> list[Section]:
    from docx import Document as DocxDocument

    try:
        doc = DocxDocument(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("The DOCX file could not be read.") from exc

    sections: list[Section] = []
    heading: str | None = None
    buf: list[str] = []

    def flush():
        if buf:
            sections.append(Section(text="\n".join(buf), heading=heading))
            buf.clear()

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style is not None else "") or ""
        if style.lower().startswith(("heading", "title")):
            flush()
            heading = text[:300]
        else:
            buf.append(text)
    flush()

    for table in doc.tables:
        rows = []
        for row in table.rows:
            cells = []
            for cell in row.cells:
                t = cell.text.strip()
                if t and (not cells or cells[-1] != t):  # merged cells repeat their text
                    cells.append(t)
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            sections.append(Section(text="\n".join(rows), heading=heading or "Table"))

    if not sections:
        raise ExtractionError("The document contains no text.")
    return sections


_DROP_TAGS = ["script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe"]


def extract_html(html: str) -> tuple[str | None, list[Section]]:
    """Return ``(title, sections)`` for an HTML page, split on h1–h3."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else None
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup

    sections: list[Section] = []
    heading: str | None = None
    buf: list[str] = []
    for el in root.find_all(["h1", "h2", "h3", "p", "li", "td", "th", "pre", "dd", "dt"]):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if not text:
            continue
        if el.name in ("h1", "h2", "h3"):
            if buf:
                sections.append(Section(text="\n".join(buf), heading=heading))
                buf = []
            heading = text[:300]
        elif not buf or buf[-1] != text:
            buf.append(text)
    if buf:
        sections.append(Section(text="\n".join(buf), heading=heading))

    if not sections:  # pages built from bare <div>s
        text = root.get_text(" ", strip=True)
        if text:
            sections = [Section(text=text)]
    return title, sections


def extract(data: bytes, kind: str) -> list[Section]:
    if kind == "pdf":
        return extract_pdf(data)
    if kind == "docx":
        return extract_docx(data)
    raise ExtractionError(f"Unsupported document kind: {kind}")
