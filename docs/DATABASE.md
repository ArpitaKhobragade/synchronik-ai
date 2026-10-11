# Database

## Setup (PostgreSQL)

```bash
createdb synchronik_ai
# .env
DATABASE_URL=postgresql+psycopg2://postgres:<password>@localhost:5432/synchronik_ai
```

Tables are created on API startup (`Base.metadata.create_all`, idempotent). For local
experiments without PostgreSQL, `DATABASE_URL=sqlite:///./data/synchronik.db` works too
(tests use SQLite).

## Schema

```mermaid
erDiagram
    kb_documents ||--o{ kb_chunks : has
    conversations ||--o{ messages : has
    conversations ||--o{ kb_documents : "attachments (conversation_id)"
    messages ||--o| message_feedback : rated
    kb_documents {
        int id PK
        string title
        string source_type
        string source_url
        string content_hash
        string status
        string conversation_id FK
        bytes raw_bytes
        datetime last_crawled_at
    }
    kb_chunks {
        int id PK
        int document_id FK
        int chunk_index
        text text
        int page
        string section
        bytes embedding
        string embedding_model
    }
    conversations {
        string id PK
        string title
        datetime updated_at
    }
    messages {
        int id PK
        string conversation_id FK
        string role
        text content
        json sources
        json confidence
        json meta
        json attachment
        string query_id
    }
    message_feedback {
        int id PK
        int message_id FK
        string rating
        string reason
        text comment
    }
    query_logs {
        string id PK
        string conversation_id
        string intent
        bool grounded
        float top_score
        float confidence
        float retrieval_ms
        float rerank_ms
        float llm_ms
        float total_ms
        json chunk_ids
        json timings
        string error
    }
    jobs {
        string id PK
        string kind
        string status
        text detail
    }
```

* There is no users table: admin access is a single `ADMIN_API_KEY` header, and end users are anonymous per conversation.
* Evaluation data is **not** in the database. Datasets and reports are version-controlled JSONL/JSON under `backend/evaluation/`.
* `query_logs.timings` holds per-stage milliseconds (embed, semantic, keyword, fusion, rerank, context, llm_first_token, llm, total). It is added to existing databases by the idempotent `ALTER TABLE` in `init_db()`.
* `kb_documents.conversation_id IS NULL` → global knowledge base; otherwise a private chat attachment.
* `content_hash` (SHA-256 of extracted text) drives crawler change detection.
* `kb_chunks.embedding` is float32 bytes + the model name, so a model change is detected and
  stale vectors are excluded from the index until re-embedded (`/reprocess`).

## Schema changes

Additive column changes are applied by `init_db()` (`_ADDED_COLUMNS`). Anything beyond that
(renames, type changes) would need Alembic, which is the intended next step.

PostgreSQL compatibility: the ORM uses only portable types (JSON, LargeBinary→`bytea`,
timezone-aware DateTime). NUL bytes are stripped from extracted text because PostgreSQL
rejects them. CI runs the full test suite against a PostgreSQL 16 container
(`.github/workflows/ci.yml`). **That CI job has not run yet.** It runs on the first push to GitHub.
