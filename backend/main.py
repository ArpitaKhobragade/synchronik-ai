"""FastAPI application factory.

Run:  uvicorn backend.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import chat, documents, misc
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.logging import configure_logging, log_event, request_id_var
from backend.db.session import init_db
from backend.services import jobs
from backend.services.vector_store import knowledge_index


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    _warn_missing_config(s)
    try:
        init_db()
        knowledge_index.load_or_build()  # once per process — never per request
    except Exception as exc:  # noqa: BLE001 - start degraded; /api/health reports it
        log_event("startup_degraded", level=logging.ERROR, error=type(exc).__name__, detail=str(exc)[:200])
    try:
        if s.load_curated_docs:
            from backend.services.curated import load_curated

            load_curated()  # repository FAQ documents; skipped when unchanged
    except Exception as exc:  # noqa: BLE001 - the app works without them
        log_event("curated_load_failed", level=logging.ERROR, error=type(exc).__name__)
    if s.admin_api_key == "" and s.is_production:
        log_event("admin_disabled", level=logging.WARNING)
    jobs.start_scheduler(s.crawl_interval_hours)
    log_event("startup", version=s.app_version, env=s.environment, llm=s.llm_configured, vectors=knowledge_index.size)
    yield


# What happens when each variable is missing; logged once at startup (see .env.example).
_REQUIRED_VARS = {
    "DATABASE_URL": "no database configured: falls back to PostgreSQL on localhost (set a sqlite:/// URL for local use)",
    "GEMINI_API_KEY": "answers are documentation excerpts only; image questions return 503 llm_not_configured",
    "ADMIN_API_KEY": "admin endpoints (upload, crawl, reindex) are disabled",
}


def _warn_missing_config(s) -> None:
    missing = {name: effect for name, effect in _REQUIRED_VARS.items() if not getattr(s, name.lower())}
    if missing:
        log_event("config_incomplete", level=logging.WARNING, missing=sorted(missing), effects=missing,
                  hint="Copy .env.example to .env and set these variables, then restart.")


def _error(status: int, code: str, message: str, rid: str | None, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": rid}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Synchronik AI API",
        version=s.app_version,
        description="Enterprise ERP knowledge assistant: hybrid RAG with reranking, citations and evaluation.",
        lifespan=lifespan,
        docs_url=None if s.is_production else "/docs",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,  # explicit allow-list, never "*"
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Admin-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = (request.headers.get("x-request-id") or uuid.uuid4().hex)[:64]
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            log_event("http_request", request_id=rid, method=request.method, path=request.url.path,
                      status=response.status_code, ms=round((time.perf_counter() - t0) * 1000, 1))
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return _error(exc.status_code, exc.code, exc.message, request_id_var.get())

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return _error(422, "validation_error", "The request is invalid.", request_id_var.get(), details)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log_event("unhandled_error", level=logging.ERROR, path=request.url.path, error=type(exc).__name__)
        logging.getLogger("synchronik").exception("unhandled")
        code, msg, status = "internal_error", "Something went wrong. Please try again.", 500
        if type(exc).__module__.startswith(("sqlalchemy", "psycopg2")):
            code, msg, status = "database_unavailable", "The database is temporarily unavailable.", 503
        return _error(status, code, msg, request_id_var.get())

    for r in (chat.router, documents.router, misc.conversations, misc.feedback, misc.ops, misc.admin):
        app.include_router(r)

    @app.get("/", include_in_schema=False)
    def root():
        return {"message": "Synchronik AI backend running", "docs": "/docs", "health": "/api/health"}

    # Aliases for older clients (embedded widget, scripts) that post to the original paths
    app.add_api_route("/chat", chat.chat, methods=["POST"], include_in_schema=False)
    app.add_api_route("/feedback", misc.submit_feedback, methods=["POST"], include_in_schema=False)
    return app


app = create_app()
