"""Pydantic request/response schemas (also drive the OpenAPI docs at /docs)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = Field(None, max_length=64)
    # Older clients send {"session_id": "...", "message": "..."}
    session_id: str | None = Field(None, max_length=64, exclude=True)

    @model_validator(mode="after")
    def _compat(self):
        self.message = self.message.strip()
        if not self.message:
            raise ValueError("message must not be blank")
        if not self.conversation_id and self.session_id:
            self.conversation_id = self.session_id
        return self


class RegenerateRequest(BaseModel):
    conversation_id: str = Field(..., max_length=64)
    # Retry: the question the client expects to be last. If the server never stored it
    # (e.g. the network failed first), it is answered fresh instead of replacing the previous exchange.
    message: str | None = Field(None, min_length=1, max_length=4000)


class Source(BaseModel):
    id: int
    chunk_id: int
    document_id: int
    title: str
    source_type: str
    url: str | None
    page: int | None
    section: str | None
    score: float
    rerank_score: float | None
    snippet: str


class Confidence(BaseModel):
    score: float
    level: Literal["high", "medium", "low", "none"]
    label: str
    explanation: str
    signals: dict[str, float]


class ChatResponse(BaseModel):
    answer: str
    response: str
    sources: list[Source]
    confidence: Confidence
    retrieval_count: int
    latency_ms: int
    conversation_id: str
    session_id: str
    query_id: str
    message_id: int
    intent: str
    rewritten_query: str | None
    grounded: bool
    metadata: dict


class FeedbackRequest(BaseModel):
    message_id: int | None = None
    rating: Literal["positive", "negative"] | None = None
    reason: Literal["incorrect", "not_relevant", "missing_info", "poor_explanation", "other"] | None = None
    comment: str | None = Field(None, max_length=1000)
    # Older clients send question/answer pairs without a message id
    question: str | None = Field(None, max_length=4000)
    answer: str | None = Field(None, max_length=20000)
    feedback_type: Literal["positive", "negative"] | None = None

    @model_validator(mode="after")
    def _check(self):
        self.rating = self.rating or self.feedback_type
        if self.rating is None:
            raise ValueError("rating is required")
        if self.message_id is None and self.answer is None:
            raise ValueError("message_id is required")
        return self


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    match: str | None = None


class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class DocumentOut(BaseModel):
    id: int
    title: str
    source_type: str
    source_url: str | None
    status: str
    error: str | None
    chunk_count: int
    mime_type: str | None
    created_at: datetime
    updated_at: datetime
    last_crawled_at: datetime | None


class CrawlRequest(BaseModel):
    source: Literal["help_portal", "website", "curated", "all"] = "all"
