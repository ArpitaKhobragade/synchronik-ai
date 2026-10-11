# Deployment

> **Status:** not deployed yet. The production image was rehearsed locally on 2026-10-09: Docker image →
> fresh PostgreSQL 16 with a Render-style `postgres://` URL → KB crawl through the admin API → live Gemini
> answers → production frontend build calling it cross-origin. Everything below was measured in that rehearsal.

```
Vercel (static React build) ──HTTPS──▶ Render web service (Docker: FastAPI + ONNX models)
                                              ├──▶ Render PostgreSQL (documents, chunks + embeddings, conversations)
                                              └──▶ Gemini API
```

## Before you start

1. **Enable billing on the Gemini key.** A free-tier key is limited to **20 requests/day** for
   the configured model (Google's own error: `generate_content_free_tier_requests, limit: 20`; observed with an
   earlier Flash-Lite model, check the current quota for `gemini-3.5-flash-lite`). One answer can
   use 2 requests (follow-up rewrite + answer). In [Google AI Studio](https://aistudio.google.com) → your project →
   *Billing*, switch to pay-as-you-go. When the quota runs out the app does not fail: it returns the cited
   documentation excerpts, labelled as such.
2. **Put the code in a private GitHub repository.** Render and Vercel both deploy from private repositories. `.env`
   is git-ignored, so keys are never published.

## 1. Backend + database on Render

1. Render → **New → Blueprint** → pick the repository. `render.yaml` creates:
   - `synchronik-ai-api`: Docker web service on the **free** plan (512 MB), health check `/api/health`
   - `synchronik-ai-db`: PostgreSQL on the **free** plan, wired in as `DATABASE_URL`

   The free plan is for a trial: the API sleeps after 15 minutes idle (about a minute to wake on the next request), and
   Render deletes free databases after 30 days. For lasting use, change the plans in `render.yaml` to `starter` (API,
   always on) and `basic-256mb` (database).
2. When prompted, set:

   | Variable | Value |
   |---|---|
   | `GEMINI_API_KEY` | your key (stored only in Render) |
   | `CORS_ORIGINS` | your Vercel URL, e.g. `https://synchronik-ai.vercel.app` (set a placeholder first, update after step 2) |

   Set automatically: `ENVIRONMENT=production`, `DATABASE_URL`, `ADMIN_API_KEY` (generated: copy it from the
   service's *Environment* tab), `RERANKER=none`, `EMBED_BATCH_SIZE=8`.
3. Wait for the deploy, then open `https://<service>.onrender.com/api/health`. On the first deploy it reports
   `"status": "degraded"` with `"vector_index": "empty"`: correct, the database has no documents yet.
4. Load the knowledge base. After the frontend is up (step 2), open **Knowledge Base**, paste the admin key, and click
   **Trigger crawl** (help portal). It takes about a minute (17 pages, ~760 chunks). Without the UI:
   ```bash
   curl -X POST https://<service>.onrender.com/api/admin/crawl -H "X-Admin-Key: <ADMIN_API_KEY>" -H "Content-Type: application/json" -d "{\"source\":\"help_portal\"}"
   ```
   Health then reports `"status": "healthy"`.

### Memory and plan choice (measured, cgroup peak of the container)

| Setting | Peak (crawl + queries) | Plan |
|---|---|---|
| `RERANKER=none` (default in `render.yaml`) | 417 MB | Free or Starter, 512 MB |
| `RERANKER=minilm` (cross-encoder reranking) | 577 MB | Standard, 2 GB |

The reranker improves context precision and refusals (see [EVALUATION.md](EVALUATION.md)). To use it, switch the API
to the Standard plan and set `RERANKER=minilm`.

## 2. Frontend on Vercel

1. Vercel → **Add New → Project** → import the repository. **Root Directory: `frontend`** (framework: Vite).
2. Environment variable: `VITE_API_BASE_URL` = `https://<service>.onrender.com` (no trailing slash).
   Only put the API's public URL here: every `VITE_*` value is shipped to browsers.
3. Deploy. `frontend/vercel.json` rewrites all paths to `index.html` (hash routing).
4. Back on Render, set `CORS_ORIGINS` to the exact Vercel URL (Render redeploys automatically).

## 3. Verify the live app

- `GET /api/health` → `healthy`, `"llm": "configured"`, `"vectors"` ≈ 760.
- In the UI: ask "How do late fine rules work for fee payments?" and expect a streamed answer with a source
  list. Ask "What is the capital of Australia?": with the default `GENERAL_ANSWERS=true` it gets a short
  general-knowledge answer with no sources (with `GENERAL_ANSWERS=false` it is declined).
- `https://<service>.onrender.com/docs` returns 404 (API docs are disabled in production by design).

## Production checklist

- `CORS_ORIGINS` lists only the real frontend origin(s). Plain comma-separated URLs are fine; trailing slashes are ignored.
- `ADMIN_API_KEY` is long and random; rotate by changing the env var.
- Rate limiting is per process and uses the client IP from Render's proxy (`--forwarded-allow-ips` in the
  Dockerfile). Put Redis behind it before running more than one instance.
- Logs are JSON on stdout (request id, query id, per-stage latency, `llm_fallback` when Gemini is unavailable).
- Re-run the evaluation after changing models or thresholds: `python -m backend.evaluation.run`.

## Bugs found and fixed by the rehearsal

These would each have broken the first real deploy; all now have regression tests:

1. `CORS_ORIGINS=https://…` (a plain URL) crashed startup: pydantic-settings JSON-decoded list settings.
2. Render's `postgresql://` URL selected psycopg v3, SQLAlchemy 2.1's new default driver, which isn't installed:
   "database unavailable" on every request.
3. The Dockerfile's recursive `chown` duplicated the image layers (1.45 GB → 1.1 GB after the fix), and the models
   were re-downloaded on every code change (now baked before the code is copied).
4. Without trusted proxy headers, every visitor shared one rate-limit bucket (the proxy's IP).
5. Peak memory during a crawl was ~720 MB: embedding batch 32 → 8 (now `EMBED_BATCH_SIZE`), reranker batch 32 → 4.

## Local Docker

On Windows, if `docker build` fails with `invalid file request Dockerfile`, the files are probably cloud-synced
placeholders (reparse points) that BuildKit cannot read; build from a fresh `git clone` instead.

```bash
docker build -t synchronik-ai .
docker run -p 8000:8000 --env-file .env synchronik-ai
```
