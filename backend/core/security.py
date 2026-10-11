"""Security helpers: admin auth, rate limiting, upload validation.

Uploads are validated by size *and* magic bytes (the client-supplied content
type and filename are never trusted) and processed fully in memory, so no
user-controlled path ever touches the filesystem.
"""
from __future__ import annotations

import hmac
import io
import re
import threading
import time
import zipfile
from collections import defaultdict, deque

from fastapi import Header, Request, UploadFile

from backend.core.config import get_settings
from backend.core.errors import FileTooLarge, RateLimited, Unauthorized, UnsupportedFile


# --- Admin -----------------------------------------------------------------

def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    expected = get_settings().admin_api_key
    if not expected:
        raise Unauthorized("Admin features are disabled: ADMIN_API_KEY is not set on the server.")
    if not x_admin_key or not hmac.compare_digest(x_admin_key.encode(), expected.encode()):
        raise Unauthorized()


# --- Rate limiting -----------------------------------------------------------

class SlidingWindowLimiter:
    """In-process sliding-window limiter keyed by client IP.

    Good enough for a single instance; a multi-instance deployment should move
    this to Redis (documented in the README).
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float = 60.0) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                raise RateLimited()
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit_chat(request: Request) -> None:
    limiter.check(f"chat:{_client_ip(request)}", get_settings().rate_limit_chat_per_min)


def rate_limit_upload(request: Request) -> None:
    limiter.check(f"upload:{_client_ip(request)}", get_settings().rate_limit_upload_per_min)


# --- Upload validation -------------------------------------------------------

DOC_KINDS = {"pdf", "docx"}
IMAGE_KINDS = {"png", "jpeg", "webp", "gif"}
IMAGE_MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
DOC_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def sniff_kind(data: bytes) -> str | None:
    """Identify a file from its magic bytes."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                # Zip-bomb guard: refuse archives that expand absurdly.
                if sum(i.file_size for i in zf.infolist()) > 200 * 1024 * 1024:
                    return None
                if "word/document.xml" in names:
                    return "docx"
        except zipfile.BadZipFile:
            return None
    return None


async def read_upload(file: UploadFile, max_mb: int, allowed: set[str]) -> tuple[bytes, str]:
    """Read an upload with a hard size cap and return ``(bytes, kind)``."""
    limit = max_mb * 1024 * 1024
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise FileTooLarge(f"The file exceeds the {max_mb} MB limit.")
    if not buf:
        raise UnsupportedFile("The uploaded file is empty.")
    kind = sniff_kind(bytes(buf))
    if kind not in allowed:
        pretty = ", ".join(sorted(k.upper() for k in allowed))
        raise UnsupportedFile(f"Unsupported file. Allowed types: {pretty}.")
    return bytes(buf), kind


_SAFE_NAME = re.compile(r"[^A-Za-z0-9 ._()\-]+")


def safe_display_name(filename: str | None, fallback: str = "document") -> str:
    """A filename that is safe to store and display (never used as a path)."""
    name = (filename or fallback).replace("\\", "/").rsplit("/", 1)[-1]
    name = _SAFE_NAME.sub("_", name).strip(" .") or fallback
    return name[:150]
