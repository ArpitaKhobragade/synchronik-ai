# API reference

Base URL: `http://127.0.0.1:8000` locally. Interactive OpenAPI docs are at `/docs`, and are disabled when `ENVIRONMENT=production`.

All responses are JSON unless noted otherwise. Every response carries an `X-Request-ID` header.

## Conventions

**Authentication.** Endpoints marked 🔒 need the header `X-Admin-Key: <ADMIN_API_KEY>`, compared in constant time. When `ADMIN_API_KEY` is empty, every 🔒 endpoint returns 401.

**Rate limits.** These are per client IP, per minute:

| Group | Endpoints | Default |
|---|---|---|
| chat | `/api/chat*`, `/api/search` | 30 (`RATE_LIMIT_CHAT_PER_MIN`) |
| upload | `/api/chat/image`, `/api/chat/attachments` | 10 (`RATE_LIMIT_UPLOAD_PER_MIN`) |

**Error envelope.** Every error has the same shape:

```json
{ "error": { "code": "rate_limited", "message": "Too many requests. Please wait a moment and try again.", "request_id": "…" } }
```

| Code | HTTP | When |
|---|---|---|
| `validation_error` | 422 | Bad body or params. `details` lists the fields |
| `bad_request` / `extraction_failed` | 400 | E.g. a scanned PDF with no text |
| `unauthorized` | 401 | Missing or wrong admin key |
| `not_found` | 404 | Unknown conversation, document or message |
| `file_too_large` | 413 | Over `MAX_DOCUMENT_MB` / `MAX_IMAGE_MB` |
| `unsupported_file` | 415 | Magic bytes are not an allowed type |
| `rate_limited` | 429 | Our limiter or the LLM provider's quota |
| `llm_unavailable` / `llm_not_configured` | 503 | Gemini error/timeout, or no key (image Q&A only; chat falls back to excerpts) |
| `database_unavailable` | 503 | SQLAlchemy or driver errors |
| `internal_error` | 500 | Anything else. Details stay in the server logs |

## Chat

### `POST /api/chat`

Answer a question.

- **Body:** `{ "message": string (1–4000), "conversation_id"?: string }`. `session_id` is accepted as an alias of `conversation_id`.
- **Response `ChatResponse`:**

```json
{
  "answer": "Markdown with [1] citations", "response": "(same as answer, for older clients)",
  "sources": [{ "id": 1, "chunk_id": 412, "document_id": 3, "title": "How-To Guides · SackNova Help",
                "source_type": "help_portal", "url": "http://help.synchronik.co.in/help/how-to.html",
                "page": null, "section": "Mark daily attendance", "score": 0.61, "rerank_score": 0.97,
                "snippet": "…" }],
  "confidence": { "score": 0.86, "level": "high", "label": "High confidence",
                  "explanation": "Good documentation match",
                  "signals": { "top_score": 0.97, "support_chunks": 4, "score_margin": 0.1, "source_agreement": 1.0 } },
  "retrieval_count": 4, "latency_ms": 1350, "conversation_id": "…", "session_id": "…",
  "query_id": "…", "message_id": 57,
  "intent": "document_question | follow_up | greeting | ambiguous | out_of_scope | general | attachment_question",
  "rewritten_query": null, "grounded": true,
  "metadata": { "model": "gemini-3.5-flash-lite | extractive-fallback", "retrieval_ms": 21.4, "rerank_ms": 1040.2,
                "llm_ms": 0, "candidates": 31, "reranker": "Xenova/ms-marco-MiniLM-L-6-v2",
                "documents_considered": 2, "timings": { "embed_ms": 12.0, "rerank_ms": 1040.2, "total_ms": 1350.0 } }
}
```

- **Errors:** 422, 429, 503.

### `POST /api/chat/stream`

Same body as `/api/chat`; the response is `text/event-stream`. Events, in order:

1. `status`: `{stage, label}`, one per pipeline stage.
2. `meta`: sources, confidence and intent, sent before generation starts.
3. `token`: `{text}`, real Gemini stream chunks.
4. `done`: the full `ChatResponse`, or `error`: `{code, message}` if something fails.

### `POST /api/chat/regenerate`

Replaces the last exchange: removes the last answer (including a partial answer saved after Stop) and its question,
then answers that question again.

- **Body:** `{ "conversation_id": string, "message"?: string }`
- **`message` (retry):** the question the client expects to be last. If it matches, that exchange is replaced. If it
  doesn't (the question never reached the server), nothing is deleted and `message` is answered as a new turn, so a
  retry can neither duplicate a question nor erase the previous exchange.
- **Response:** `ChatResponse`
- **Errors:** 404 if there's nothing to regenerate and no `message` was given.

### `POST /api/chat/regenerate/stream`

Same as `/api/chat/regenerate`, streamed with the same SSE events as `/api/chat/stream`.

### Stopping a stream

Closing the SSE connection stops generation. Whatever the model produced so far is saved as the assistant message,
followed by *Generation stopped.*, so the history matches what the user saw. It isn't saved if the exchange was
already replaced (for example by a regenerate).

### `POST /api/chat/image`

Image Q&A using Gemini vision. The model first reads the image (visible text and the kind of screen); that reading
and the question are searched in the documentation, and the answer sees the image together with the matching pages.
If the vision model is unavailable, the answer model reads the image instead.

- **Body:** multipart with `file` (png, jpeg, webp or gif, up to 8 MB), `question`, and optional `conversation_id`.
- **Response:** `ChatResponse` with intent `image_question`; `sources` lists the documentation pages the answer cites
  (empty when none were used).
- **Errors:** 413, 415, 429, 503.

### `POST /api/chat/attachments`

Attaches a document to one conversation. Every later question in that conversation is answered with the document
in context (the whole text, or for long documents its opening plus the passages matching the question), plus matching
help-portal pages for questions that are not explicitly about the document. Answers use intent `attachment_question`.

- **Body:** multipart with `file` (pdf or docx, up to 20 MB) and optional `conversation_id`.
- **Response:** `{ conversation_id, document, chunks, message }`
- **Errors:** 400, 413, 415, 429.

## Conversations

| Method | Path | Purpose | Response |
|---|---|---|---|
| GET | `/api/conversations?q=` | List, newest first. `q` searches titles and message text | `[{id, title, created_at, updated_at, message_count, match?}]` |
| POST | `/api/conversations` | Create an empty conversation | summary (201) |
| GET | `/api/conversations/{id}` | The conversation with its messages (each with stored sources, confidence, metadata and feedback) | conversation |
| PATCH | `/api/conversations/{id}` | Rename. Body `{title}` | summary |
| DELETE | `/api/conversations/{id}` | Delete it, with its messages and attachments (vectors are removed from the index too) | 204 |
| GET | `/api/conversations/{id}/export?format=markdown` | Download as Markdown | `text/markdown` |

Errors: 404 for an unknown id.

## Feedback

### `POST /api/feedback`

- **Body:** `{ message_id, rating: "positive"|"negative", reason?: "incorrect"|"not_relevant"|"missing_info"|"poor_explanation"|"other", comment?: string (≤1000) }`
- Older clients may send `{question, answer, feedback_type}` instead.
- **Response:** `{ "ok": true, "message": "Feedback Saved Successfully" }`
- **Errors:** 404 for an unknown or non-assistant message, 422.

## Knowledge base

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/documents` | public | Global KB documents: `{id, title, source_type, source_url, status, error, chunk_count, mime_type, created_at, updated_at, last_crawled_at}` |
| POST | `/api/documents` | 🔒 | Upload a PDF/DOCX to the global KB. Responds 201 with `{document, chunks, message}` |
| DELETE | `/api/documents/{id}` | 🔒 | Delete a document and its vectors (204) |
| POST | `/api/documents/{id}/reprocess` | 🔒 | Re-chunk and re-embed. Returns `{document, chunks}` |
| GET | `/api/search?q=&k=5` | public, rate-limited | Retrieval only, no LLM: `{query, passed_gate, results: Source[], latency_ms}` |

## Operations

### `GET /api/health`

```json
{ "status": "healthy | degraded | unhealthy", "version": "2.0.0", "environment": "development",
  "database": "ok | unavailable", "vector_index": "ok | empty | unavailable", "llm": "configured | not_configured",
  "checks": { "database": {"ok": true, "detail": "postgresql"}, "vector_index": {"ok": true, "vectors": 713, "built_at": 1791115926.2},
              "llm": {"ok": false, "configured": false, "model": "gemini-3.5-flash-lite"}, "embeddings": {"ok": true, "model": "…"} } }
```

- `unhealthy` (HTTP 503): the database or vector index is unavailable.
- `degraded`: no LLM key, or the knowledge base is empty.
- The response never contains secrets.

### Admin endpoints 🔒

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/admin/verify` | Check an admin key. Returns `{"ok": true}` |
| GET | `/api/admin/stats` | Document, chunk and embedded counts, counts by source type, last crawl/index time, index size, recent jobs |
| POST | `/api/admin/reindex` | Background job that rebuilds FAISS from stored vectors (202, `Job`) |
| POST | `/api/admin/crawl` | Background crawl. Body `{source: "help_portal"\|"website"\|"curated"\|"all"}` (202, `Job`) |
| GET | `/api/admin/jobs` | The last 25 jobs `{id, kind, status, detail, started_at, finished_at}` |
| GET | `/api/admin/analytics` | Metrics computed from `query_logs` and `message_feedback`: `has_data`, totals, answered/refused counts, confidence distribution, latency avg/p95, per-stage p50/p95, feedback rates/reasons, unanswered/top/failed queries, `by_intent`, daily volume |
| GET | `/api/admin/evaluation` | The latest development-split evaluation report (404 if none has been run) |

## Aliases for older clients

`POST /chat` and `POST /feedback` (hidden from OpenAPI) are aliases of `POST /api/chat` and `POST /api/feedback`.
