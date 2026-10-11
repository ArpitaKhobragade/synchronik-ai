# Test matrix

Last verified 2026-10-09 on a Windows laptop: Python 3.11, Node 22, SQLite + fake providers in automated tests;
live Gemini and a Docker PostgreSQL 16 rehearsal for the rows marked *live*. Only the "Render / Vercel" row was verified on the public deployment.
**PASS** means it was actually run and passed. Anything else is labelled for what it is.

| Component | Test | How | Result |
|---|---|---|---|
| Backend | Unit + integration + evaluation + safety tests | `pytest`: 89 tests | **PASS** (88 passed, 1 skipped in a fresh checkout without the crawled database, 2026-10-10; 88/88 on the development machine before the startup-config test was added) |
| Backend | Imports / startup | `import backend.main`, `uvicorn backend.main:app` | **PASS** |
| Backend | Health endpoint | Live: `degraded` without a key; `healthy` with the Gemini key; `degraded` + HTTP 200 on an empty PostgreSQL | **PASS** |
| Backend | Health `unhealthy` / 503 | Manual: backend pointed at an unreachable PostgreSQL; UI showed the red "unhealthy" pill | **PASS** (manual; no automated test) |
| RAG | Retrieval on real docs | Live `/api/chat` + evaluation on 17 crawled pages | **PASS** |
| RAG | Hybrid search | Evaluation ablation (92 + 20 queries); re-run 2026-10-09 reproduced every quality metric exactly | **PASS** (see EVALUATION.md) |
| RAG | Reranking | Evaluation ablation + live metadata | **PASS** |
| RAG | Refusal / relevance gate | Live out-of-scope query refused; eval gate accuracy 0.989 dev, 0.95 held-out | **PASS** |
| RAG | Clarification for ambiguous queries | Live "How do I fix it?" → `ambiguous` | **PASS** |
| RAG | Citations | Integration tests (fake LLM), unit test for grouped `[1, 2]`, and live Gemini answers: every cited `[n]` was a returned source | **PASS** (live, 2026-10-09; a small number of answers) |
| RAG | Confidence | Unit test + live (`high` on an FAQ question) | **PASS** |
| RAG | Query rewriting | Integration test + eval follow-up subset (heuristic rewriter) + live Gemini follow-up | **PASS** (LLM rewriter: live spot check only) |
| RAG | Streaming (SSE) | Integration test + live `status/meta/token/done` | **PASS** |
| RAG | Per-stage timings | Live response metadata + eval latency tables | **PASS** |
| Conversations | Persist, search, rename, export, delete, regenerate (JSON + streamed), safe retry, Stop keeps the partial answer | Integration tests + live HTTP-disconnect probe | **PASS** |
| Uploads | Spoofed type (exe renamed .pdf) | Integration test + live → 415 | **PASS** |
| Uploads | Oversized file | Integration test → 413 | **PASS** |
| Uploads | Path traversal / malicious filename | Unit test (`safe_display_name`), upload test (`../../hostel.pdf` → `hostel.pdf`) | **PASS** |
| Uploads | Attachment scoping (no KB poisoning) | Integration test | **PASS** |
| Security | Admin auth | Integration tests: 5 admin endpoints reject missing and wrong keys (401); admin disabled when `ADMIN_API_KEY` is empty; constant-time comparison. Live: 401 without key | **PASS** |
| Security | CORS | Live: unknown origin preflight → 400, allowed origin echoed | **PASS** (not in automated tests) |
| Security | Rate limiting | Integration test → 429 | **PASS** |
| Security | Injected tags/instructions in retrieved context | Unit test (tag neutralization + injection flag) | **PASS** |
| Security | Prompt injection that reaches the LLM | `test_quality_safety.py`: the question passes the gate and a scripted model leaks the system prompt or a secret (also split across stream chunks); neither appears in any streamed token or final answer. Forged `</sources>` / `<source>` / `<system>` tags in questions are stripped. Injection inside an attached document is neutralised and flagged before the model sees it | **PASS** (fake model; not red-teamed against live Gemini) |
| Failure modes | LLM quota exhausted (429) | Integration test + live: real Gemini 429 → cited-excerpt fallback (HTTP 200) | **PASS** |
| RAG | General-knowledge answers (`GENERAL_ANSWERS=true`) | Integration tests: uncited answer from the general prompt, marked intent `general` in the API with no label in the text; undocumented ERP question still refused (incl. curly-apostrophe refusal); quota error → refusal; general-prompt leak blocked; a documentation-path refusal hands over to the general path without showing the refusal; docs-only mode unchanged; describing the assistant is not a leak. Live (Gemini 3.5 Flash-Lite, `RERANKER=none`): "how the erp chatbot works?", "what is an ERP?", "what is OBE?" and a general question answered; "what modules does Synchronik ERP have?" and attendance answered from the docs with citations; a biometric-device question refused | **PASS** |
| RAG | Curated Synchronik FAQ (`backend/knowledge/`) | Integration test: ingested once, unchanged on reload, searchable; every FAQ answer names its source. Live: "What does Synchronik do?", products, biometric support and roles answered from the FAQ with citations | **PASS** |
| RAG | No "not documented" replies in general mode | Tests: a model refusal becomes a helpful support reply; quota errors say the model is unavailable; an answer ending with the support sentence is not blocked by the leak guard. Live: an undocumented payroll question got a general explanation | **PASS** |
| Failure modes | Provider outage before / during an answer, database failure | Outage before any text → cited-excerpt fallback; outage mid-stream → `error` event, no half answer; database error → 503 `database_unavailable` envelope without driver details; health 503 when the database is down | **PASS** (automated) |
| Failure modes | LLM timeout, malformed or empty model response | — | **NOT DONE** (handled in code, no dedicated test) |
| Frontend | Lint | `npm run lint` | **PASS** (0 problems) |
| Frontend | Production build | `npm run build` | **PASS** |
| Frontend | Degraded, unhealthy and backend-offline health states | Manual check in a browser against live backends | **PASS** |
| Frontend | Share button: copies a link that reopens the conversation (fallback message when clipboard access is blocked); quality dashboard and header status badge removed (2026-10-10) | Browser check | **PASS** |
| RAG | Attached documents and images (2026-10-10) | Tests: a document question and a vague follow-up both get the whole attachment with the attachment prompt; an ERP how-to question in the same chat also gets help-portal pages; an image is read first and the answer sees the documentation found for it; vision falls back to the answer model on a 503. Live (sample exam circular + error screenshot): 9 / 9 answers correct, including summary, fee, issuer, deadline consequence (4 / 4 repeated runs), marks-entry steps from the help portal, a WhatsApp draft, and the locked-attendance error with help-portal fix steps | **PASS** |
| Frontend | Admin key and API address removed from Settings (the admin key is entered on the Knowledge Base page) (2026-10-10) | Browser check | **PASS** |
| Frontend | Citation numbers, confidence badge, "General answer" label and "How this answer was generated" panel removed; sources listed without numbers or match scores (2026-10-10) | Browser check: a documentation answer and a general answer, no console errors | **PASS** |
| Frontend | KB empty state (empty database), stage timings | Manual check in a browser | **PASS** |
| Frontend | Layout at 1280 px, 768 px (tablet) and 375 px (mobile drawer); long answer without overflow | Manual check in a browser. Found and fixed a bug where the mobile drawer never opened | **PASS** |
| Frontend | Source cards, feedback 👎 with reason, chat PDF attachment upload | Manual check in a browser | **PASS** |
| Frontend | Redesigned UI: light + dark themes at 1440 / 1280 / 820 / 375 px, no horizontal overflow, no console errors | Manual check in a browser (2026-10-09) | **PASS** |
| Frontend | KB-page drag-drop upload, code blocks/tables in answers, keyboard focus rings | — | NOT MANUALLY VERIFIED |
| Screenshots | README screenshots (9 files) | Recaptured 2026-10-09 after the redesign, with Playwright and Edge; extractive-fallback mode | **ADDED** (`docs/screenshots/`) |
| Gemini | Live generation, streaming, citations, image Q&A, follow-up, regenerate, refusal | 12 live checks, run twice (dev server; production image) | **PASS** (live, 2026-10-09; script not committed) |
| Gemini | Answer-quality evaluation (`evaluation/answers.py`, 23 items, real Gemini, deployed settings) | Run 2026-10-10: 18/18 answerable answered from the docs; key-fact coverage 0.924 (15/18 complete); citations all point to returned sources; 4/4 undocumented handled (+1 retried after a transient model error); 0 leaks. Judge supplementary | **RUN** (small developer-written set; human review pending) |
| PostgreSQL | Live integration | Production Docker image against a fresh PostgreSQL 16 container: startup, KB crawl, live answers | **PASS** (live rehearsal, 2026-10-09) |
| PostgreSQL | `pytest` on PostgreSQL | Locally blocked: Windows Application Control blocks the psycopg2 DLL. CI job configured | **NOT RUN** |
| CI | GitHub Actions workflow | `.github/workflows/ci.yml` | NOT RUN (repo not pushed) |
| Deployment | Production rehearsal | Docker image + PostgreSQL 16 + production frontend build, cross-origin | **PASS** (local); found and fixed 5 deploy bugs |
| Deployment | Render / Vercel | Render Blueprint (Docker + PostgreSQL) and Vercel project from `main`, 2026-10-11: `/api/health` healthy on PostgreSQL, `/docs` returns 404 in production, a question on the live site was answered from the curated FAQ with sources | **PASS** (help-portal crawl on the live instance not yet run) |
