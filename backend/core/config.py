"""Centralised, environment-driven configuration.

Every tunable of the RAG pipeline lives here so retrieval behaviour can be
changed per environment (``.env`` locally, dashboard env vars in production)
without touching code. See ``.env.example`` for documentation of each value.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]

# List settings arrive from the environment as plain "a,b" strings (e.g. CORS_ORIGINS=https://app.vercel.app).
# NoDecode stops pydantic-settings from JSON-decoding them first, which crashed startup on a plain URL.
CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App -------------------------------------------------------------
    app_name: str = "Synchronik AI"
    app_version: str = "2.0.0"
    environment: str = Field("development", description="development | production | test")
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: CsvList = ["http://localhost:5173", "http://127.0.0.1:5173"]
    admin_api_key: str = ""  # empty => admin endpoints are disabled entirely

    # --- Database --------------------------------------------------------
    database_url: str = ""
    # Individual connection variables, used only when DATABASE_URL is not set.
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "synchronik_chatbot"
    db_user: str = "postgres"
    db_password: str = ""

    # --- Storage ---------------------------------------------------------
    data_dir: Path = ROOT_DIR / "data"
    model_cache_dir: Path | None = None  # defaults to <data_dir>/models

    # --- Models ----------------------------------------------------------
    gemini_api_key: str = ""
    llm_model: str = "gemini-3.5-flash-lite"  # 2.5 models are not offered to new API keys
    vision_model: str = "gemini-3.8-flash"
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 1024
    llm_timeout_s: float = 45.0
    embedding_provider: str = "fastembed"  # fastembed (ONNX, no torch) | sentence-transformers
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_batch_size: int = 8  # ONNX memory grows with batch: peak RSS 293 MB at 8 vs 541 MB at 32 (fits 512 MB hosts)
    reranker: str = "minilm"  # minilm (cross-encoder, alias: cross-encoder) | none
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    # --- Chunking --------------------------------------------------------
    chunk_size: int = 900  # characters
    chunk_overlap: int = 150

    # --- Retrieval -------------------------------------------------------
    semantic_top_k: int = 20
    keyword_top_k: int = 20
    hybrid_semantic_weight: float = 0.65
    hybrid_keyword_weight: float = 0.35
    rerank_candidates: int = 12  # only the best fused candidates are cross-encoded (latency ~ linear)
    rerank_max_chars: int = 700
    rerank_top_n: int = 6
    load_curated_docs: bool = True  # ingest backend/knowledge/*.html at startup (skipped when unchanged)
    general_answers: bool = True  # no documentation match: answer from general knowledge (False = decline)
    max_chunks_per_section: int = 0  # section diversity in the final ranking; 0 = off (see EVALUATION.md, experiments)
    # Relevance gate: answer only when evidence clears these bars.
    min_semantic_score: float = 0.30  # cosine similarity of the best chunk
    min_rerank_score: float = 0.10  # sigmoid(cross-encoder logit) of the best chunk: answer vs refuse
    # Per-chunk bar for staying in the prompt once the gate passed. Lower than the gate on purpose:
    # 0.02 (logit < -3.9) only drops chunks the cross-encoder considers clearly irrelevant.
    # Measured: 0.10 → context recall 0.658 / precision 0.705; 0.02 → 0.681 / 0.675.
    min_context_rerank_score: float = 0.02
    min_support_chunks: int = 1
    context_max_chars: int = 7000

    # --- Memory ----------------------------------------------------------
    history_max_messages: int = 6
    history_max_chars: int = 3000

    # --- Uploads & abuse protection -------------------------------------
    max_document_mb: int = 20
    max_image_mb: int = 8
    rate_limit_chat_per_min: int = 30
    rate_limit_upload_per_min: int = 10

    # --- Crawler ---------------------------------------------------------
    crawl_allowed_hosts: CsvList = ["help.synchronik.co.in", "synchronik.co.in", "www.synchronik.co.in"]
    crawl_seeds: dict[str, str] = {
        "help_portal": "http://help.synchronik.co.in",
        "website": "https://synchronik.co.in",
    }
    # Honest, identifying UA. synchronik.co.in currently resets non-browser clients; get it allow-listed
    # rather than impersonating a browser.
    crawl_user_agent: str = "SynchronikAI-DocsCrawler/2.0 (+https://synchronik.co.in)"
    crawl_max_pages: int = 200
    crawl_delay_s: float = 1.0
    crawl_timeout_s: float = 20.0
    crawl_interval_hours: float = 0  # 0 disables scheduled refresh

    @field_validator("cors_origins", "crawl_allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, v):
        """Accept "a,b", a JSON list '["a","b"]', or a real list. Trailing slashes are dropped from origins,
        because browsers send Origin without one and CORS matching is exact."""
        if isinstance(v, str):
            v = json.loads(v) if v.strip().startswith("[") else v.split(",")
        return [str(s).strip().rstrip("/") for s in v if str(s).strip()]

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            # Render/Heroku give "postgres://" or "postgresql://" with no driver. SQLAlchemy 2.1 made psycopg (v3)
            # the default driver for a bare "postgresql://", but this app ships psycopg2 — so name it explicitly.
            url = self.database_url
            for bare in ("postgres://", "postgresql://"):
                if url.startswith(bare):
                    return "postgresql+psycopg2://" + url[len(bare):]
            return url
        return (
            f"postgresql+psycopg2://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def models_dir(self) -> Path:
        return self.model_cache_dir or self.data_dir / "models"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def llm_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
