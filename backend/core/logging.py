"""Structured (JSON) logging with request/query correlation ids.

Use ``log_event("event_name", **fields)`` for anything worth querying later;
the current request id is attached automatically via a ContextVar.
User message text is never logged in full — only its length and a short hash.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

logger = logging.getLogger("synchronik")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        payload.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", as_json: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if as_json else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "urllib3", "sentence_transformers", "faiss", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": {"event": event, **fields}})


def fingerprint(text: str) -> str:
    """Short, non-reversible fingerprint so logs can group identical queries without storing them."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
