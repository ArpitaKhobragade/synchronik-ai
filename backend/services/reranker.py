"""Second-stage reranking.

Why: the bi-encoder (MiniLM) embeds query and chunk *separately*, so its
similarity is a coarse proxy. A cross-encoder reads (query, chunk) *together*
and scores real relevance, which reliably reorders the 20 hybrid candidates
so the 5–6 chunks sent to the LLM are the best ones. ``ms-marco-MiniLM-L-6-v2``
is ~90 MB (run via ONNX Runtime by default) and scores 20 pairs in tens of milliseconds on CPU, so it is
realistic for a small deployment. ``RERANKER=none`` disables it (e.g. on
memory-constrained hosts) without code changes.
"""
from __future__ import annotations

import math
import threading
from abc import ABC, abstractmethod

from backend.core.config import get_settings


class Reranker(ABC):
    name: str

    @abstractmethod
    def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance in [0, 1] per passage."""


class CrossEncoderReranker(Reranker):
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder

        self.name = model_name
        self._model = CrossEncoder(model_name, device="cpu", max_length=512)

    def score(self, query, passages):
        if not passages:
            return []
        logits = self._model.predict([(query, p) for p in passages], batch_size=32, show_progress_bar=False)
        # ms-marco cross-encoders output raw logits; a sigmoid maps them to a usable 0..1 relevance.
        return [1.0 / (1.0 + math.exp(-float(x))) for x in logits]


class FastEmbedCrossEncoder(Reranker):
    """The same ms-marco cross-encoder, ONNX-exported (no PyTorch)."""

    def __init__(self, model_name: str, cache_dir: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.name = model_name
        self._model = TextCrossEncoder(model_name, cache_dir=cache_dir)

    def score(self, query, passages):
        if not passages:
            return []
        # batch_size=4: ~70 MB less ONNX Runtime memory than 32 for the usual 12 candidates (fits small hosts)
        return [1.0 / (1.0 + math.exp(-float(x))) for x in self._model.rerank(query, passages, batch_size=4)]


class NoopReranker(Reranker):
    """Keeps the hybrid order; returns no scores (the gate then uses semantic scores only)."""

    name = "none"

    def score(self, query, passages):
        return []


_lock = threading.Lock()
_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    global _reranker
    with _lock:
        if _reranker is None:
            s = get_settings()
            if s.reranker == "none":
                _reranker = NoopReranker()
            elif s.embedding_provider == "sentence-transformers":
                _reranker = CrossEncoderReranker(s.reranker_model.replace("Xenova/", "cross-encoder/"))
            else:
                _reranker = FastEmbedCrossEncoder(s.reranker_model, str(s.models_dir))
        return _reranker


def set_reranker(r: Reranker | None) -> None:
    global _reranker
    with _lock:
        _reranker = r
