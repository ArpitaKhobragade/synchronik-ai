"""Chat endpoints: JSON, real SSE streaming, regenerate, image Q&A, conversation attachments."""
from __future__ import annotations

import json
import threading
import time

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import iterate_in_threadpool, run_in_threadpool
from fastapi.responses import StreamingResponse

from backend.api.schemas import ChatRequest, ChatResponse, RegenerateRequest
from backend.core.config import get_settings
from backend.core.errors import AppError, BadRequest, NotFound
from backend.core.logging import log_event
from backend.core.security import (DOC_KINDS, DOC_MIME, IMAGE_KINDS, rate_limit_chat, rate_limit_upload,
                                   read_upload, safe_display_name)
from backend.services import conversations as convs
from backend.services import rag_pipeline
from backend.services.document_processing import ExtractionError
from backend.services.image_qa import answer_image
from backend.services.ingestion import ingest_file

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, dependencies=[Depends(rate_limit_chat)])
def chat(req: ChatRequest):
    return rag_pipeline.answer(req.message, req.conversation_id)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/stream", dependencies=[Depends(rate_limit_chat)],
             responses={200: {"content": {"text/event-stream": {}}}})
def chat_stream(req: ChatRequest):
    """Server-Sent Events: status → meta → token* → done (or error). Tokens are real Gemini stream chunks."""
    return _stream(req.message, req.conversation_id)


def _stream(message: str, conversation_id: str | None) -> StreamingResponse:
    def gen():
        try:
            for event, payload in rag_pipeline.run_events(message, conversation_id):
                yield _sse(event, payload)
        except AppError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except Exception as exc:  # noqa: BLE001 - a broken stream must still end cleanly
            log_event("stream_failed", error=type(exc).__name__)
            yield _sse("error", {"code": "internal_error", "message": "Something went wrong. Please retry."})

    return StreamingResponse(_closing(gen()), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _close_when_idle(it) -> None:
    """Close a sync generator once its worker thread has finished the in-flight step."""
    for _ in range(1200):  # ~60 s upper bound (one LLM chunk can be slow)
        try:
            it.close()
            return
        except ValueError:  # "generator already executing" — wait for the current token
            time.sleep(0.05)


async def _closing(it):
    """Iterate a sync generator off the event loop and close it as soon as the client disconnects (Stop),
    so the pipeline's GeneratorExit handler saves the partial answer immediately rather than at GC time."""
    try:
        async for chunk in iterate_in_threadpool(it):
            yield chunk
    finally:
        threading.Thread(target=_close_when_idle, args=(it,), daemon=True).start()


def _regenerate_question(req: RegenerateRequest) -> str:
    question = convs.delete_last_assistant(req.conversation_id, expected=req.message)
    if question is None:
        if req.message and req.message.strip():
            return req.message.strip()  # retry of a question the server never stored: answer it fresh
        raise NotFound("Nothing to regenerate in this conversation.")
    return question


@router.post("/regenerate", response_model=ChatResponse, dependencies=[Depends(rate_limit_chat)])
def regenerate(req: RegenerateRequest):
    return rag_pipeline.answer(_regenerate_question(req), req.conversation_id)


@router.post("/regenerate/stream", dependencies=[Depends(rate_limit_chat)],
             responses={200: {"content": {"text/event-stream": {}}}})
def regenerate_stream(req: RegenerateRequest):
    """Streamed regenerate/retry: replaces the last exchange, then streams like ``/stream``."""
    return _stream(_regenerate_question(req), req.conversation_id)


@router.post("/image", response_model=ChatResponse, dependencies=[Depends(rate_limit_upload)])
async def image_chat(file: UploadFile = File(...), question: str = Form(..., min_length=1, max_length=2000),
                     conversation_id: str | None = Form(None)):
    data, kind = await read_upload(file, get_settings().max_image_mb, IMAGE_KINDS)
    return await run_in_threadpool(answer_image, data, kind, safe_display_name(file.filename, "image"),
                                   question.strip(), conversation_id)


@router.post("/attachments", dependencies=[Depends(rate_limit_upload)])
async def attach_document(file: UploadFile = File(...), conversation_id: str | None = Form(None)):
    """Attach a PDF/DOCX to one conversation (searchable only there — no shared-KB poisoning)."""
    data, kind = await read_upload(file, get_settings().max_document_mb, DOC_KINDS)
    name = safe_display_name(file.filename)
    conv_id = convs.ensure_conversation(conversation_id)
    try:
        doc_id, chunks = await run_in_threadpool(ingest_file, data, kind, name, DOC_MIME[kind],
                                                 source_type="attachment", conversation_id=conv_id)
    except ExtractionError as exc:
        raise BadRequest(str(exc), code="extraction_failed") from exc
    convs.add_message(conv_id, "user", f"📎 Attached **{name}**", attachment={"name": name, "kind": kind})
    from backend.api.routes.documents import document_out
    return {"conversation_id": conv_id, "document": document_out(doc_id), "chunks": chunks,
            "message": f"Document processed successfully: {chunks} sections indexed for this conversation."}
