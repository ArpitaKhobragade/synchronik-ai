"""Embedding provider abstraction.

``EmbeddingProvider`` is the only interface the rest of the system sees, so the
model can be swapped (e.g. for a hosted embedding API) by adding one class.
Vectors are L2-normalised, which makes FAISS inner product == cosine similarity.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod

import numpy as np

from backend.core.config import get_settings


class EmbeddingProvider(ABC):
    name: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n, dim) float32 array of unit vectors."""

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


class FastEmbedEmbedder(EmbeddingProvider):
    """MiniLM exported to ONNX and run with ONNX Runtime (default provider).

    No PyTorch: ~1.5 GB lighter deployment and faster cold starts on small hosts,
    with the same 384-d all-MiniLM-L6-v2 embeddings.
    """

    def __init__(self, model_name: str, cache_dir: str) -> None:
        from fastembed import TextEmbedding

        self.name = model_name
        self._model = TextEmbedding(model_name, cache_dir=cache_dir)
        self.dim = int(next(iter(self._model.embed(["dim probe"]))).shape[0])

    def embed(self, texts: list[str]) -> np.ndarray:
        batch = get_settings().embed_batch_size  # small batches cap ONNX Runtime memory during ingestion
        vecs = np.asarray(list(self._model.embed(texts, batch_size=batch)), dtype="float32")
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.clip(norms, 1e-12, None)


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Optional PyTorch provider (``EMBEDDING_PROVIDER=sentence-transformers``)."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self._model = SentenceTransformer(model_name, device="cpu")
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(
            texts, batch_size=32, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        return np.asarray(vecs, dtype="float32")


_lock = threading.Lock()
_provider: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    global _provider
    with _lock:
        if _provider is None:
            s = get_settings()
            if s.embedding_provider == "sentence-transformers":
                _provider = SentenceTransformerEmbedder(s.embedding_model)
            else:
                _provider = FastEmbedEmbedder(s.embedding_model, str(s.models_dir))
        return _provider


def set_embedder(provider: EmbeddingProvider | None) -> None:
    """Inject a provider (tests use a deterministic fake)."""
    global _provider
    with _lock:
        _provider = provider


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype="float32").tobytes()


def from_bytes(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="float32")
