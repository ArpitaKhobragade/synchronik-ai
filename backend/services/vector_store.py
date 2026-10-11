"""FAISS vector store + BM25 keyword index, cached in memory and on disk.

The index is never rebuilt per request:

* the index is built once (or loaded from ``data/index``) at startup,
* ingestion adds/removes vectors incrementally (``IndexIDMap2`` keyed by chunk id),
* a ``version`` counter lets other caches (BM25) know when to refresh.

``VectorStore`` is an interface; moving to a hosted vector DB (pgvector,
Qdrant…) means implementing ``add/remove/search`` — nothing else changes.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path

import faiss
import numpy as np
from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.logging import log_event
from backend.db.models import Chunk, Document
from backend.db.session import session_scope
from backend.services.embeddings import from_bytes, get_embedder

# A flat index of a few thousand vectors needs no parallelism, and FAISS's OpenMP
# spin-waiting starves ONNX Runtime (embedder/reranker) threads: measured 10x
# slower reranking without this.
faiss.omp_set_num_threads(1)


class VectorStore(ABC):
    @abstractmethod
    def add(self, ids: list[int], vectors: np.ndarray) -> None: ...

    @abstractmethod
    def remove(self, ids: list[int]) -> None: ...

    @abstractmethod
    def search(self, vector: np.ndarray, k: int) -> list[tuple[int, float]]: ...

    @property
    @abstractmethod
    def size(self) -> int: ...


class FaissStore(VectorStore):
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        self._lock = threading.RLock()
        self.version = 0
        self.built_at: float | None = None

    def add(self, ids, vectors):
        if not ids:
            return
        with self._lock:
            self._index.remove_ids(np.asarray(ids, dtype="int64"))  # idempotent re-add
            self._index.add_with_ids(np.asarray(vectors, dtype="float32"), np.asarray(ids, dtype="int64"))
            self.version += 1

    def remove(self, ids):
        if not ids:
            return
        with self._lock:
            self._index.remove_ids(np.asarray(ids, dtype="int64"))
            self.version += 1

    def search(self, vector, k):
        with self._lock:
            if self._index.ntotal == 0:
                return []
            scores, ids = self._index.search(np.asarray([vector], dtype="float32"), min(k, self._index.ntotal))
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

    @property
    def size(self) -> int:
        return int(self._index.ntotal)

    def reset(self) -> None:
        with self._lock:
            self._index.reset()
            self.version += 1

    def save(self, directory: Path, model: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            faiss.write_index(self._index, str(directory / "faiss.index"))
            (directory / "meta.json").write_text(
                json.dumps({"model": model, "dim": self.dim, "ntotal": self.size, "built_at": self.built_at})
            )

    def load(self, directory: Path, model: str) -> bool:
        meta_path, idx_path = directory / "meta.json", directory / "faiss.index"
        if not (meta_path.exists() and idx_path.exists()):
            return False
        meta = json.loads(meta_path.read_text())
        if meta.get("model") != model or meta.get("dim") != self.dim:
            return False
        with self._lock:
            self._index = faiss.read_index(str(idx_path))
            self.built_at = meta.get("built_at")
            self.version += 1
        return True


# --- BM25 --------------------------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set(
    "a an the and or of to in on for with is are was were be been how do does did i me my you your we our "
    "can could should would what which who whom when where why this that these those it its as at by from "
    "about into than then there their them they he she his her not no yes if so".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class BM25Index:
    """Okapi BM25 over chunk texts — lightweight, dependency-free keyword retrieval.

    Chosen over PostgreSQL ``tsvector`` so the same code runs on SQLite (tests)
    and so keyword scores can be normalised and fused with cosine scores in Python.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.ids: list[int] = []
        self.tfs: list[Counter] = []
        self.lens: list[int] = []
        self.df: Counter = Counter()
        self.avgdl = 0.0

    def build(self, docs: list[tuple[int, str]]) -> None:
        self.ids, self.tfs, self.lens, self.df = [], [], [], Counter()
        for cid, text in docs:
            toks = tokenize(text)
            tf = Counter(toks)
            self.ids.append(cid)
            self.tfs.append(tf)
            self.lens.append(len(toks))
            self.df.update(tf.keys())
        self.avgdl = (sum(self.lens) / len(self.lens)) if self.lens else 0.0

    def search(self, query: str, k: int, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        q = tokenize(query)
        if not q or not self.ids:
            return []
        n = len(self.ids)
        scored = []
        for i, tf in enumerate(self.tfs):
            if allowed is not None and self.ids[i] not in allowed:
                continue
            s = 0.0
            for term in q:
                f = tf.get(term)
                if not f:
                    continue
                idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.lens[i] / (self.avgdl or 1)))
            if s > 0:
                scored.append((self.ids[i], s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


# --- Knowledge index (FAISS + BM25 + chunk metadata cache) ----------------------

class KnowledgeIndex:
    """Process-wide cache of everything retrieval needs, refreshed on change."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.faiss: FaissStore | None = None
        self.bm25 = BM25Index()
        self.chunk_scope: dict[int, str | None] = {}  # chunk id -> conversation id (None = global)
        self._bm25_version = -1

    def _store(self) -> FaissStore:
        if self.faiss is None:
            self.faiss = FaissStore(get_embedder().dim)
        return self.faiss

    def load_or_build(self) -> None:
        s = get_settings()
        store = self._store()
        model = get_embedder().name
        with self._lock:
            n_db = self._count_embedded()
            if store.load(s.index_dir, model) and store.size == n_db:
                log_event("index_loaded", vectors=store.size)
            else:
                self.rebuild()
            self.refresh_keyword_index(force=True)

    def _count_embedded(self) -> int:
        from sqlalchemy import func

        with session_scope() as db:
            return db.scalar(
                select(func.count(Chunk.id)).where(Chunk.embedding.is_not(None))
            ) or 0

    def rebuild(self) -> int:
        """Re-embed nothing; reload every stored vector from PostgreSQL into FAISS."""
        t0 = time.perf_counter()
        store = self._store()
        model = get_embedder().name
        with self._lock:
            store.reset()
            ids, vecs = [], []
            with session_scope() as db:
                rows = db.execute(
                    select(Chunk.id, Chunk.embedding, Chunk.embedding_model).where(Chunk.embedding.is_not(None))
                ).all()
            for cid, blob, emb_model in rows:
                if emb_model == model:
                    ids.append(cid)
                    vecs.append(from_bytes(blob))
            if ids:
                store.add(ids, np.vstack(vecs))
            store.built_at = time.time()
            store.save(get_settings().index_dir, model)
            self.refresh_keyword_index(force=True)
        log_event("index_rebuilt", vectors=store.size, ms=round((time.perf_counter() - t0) * 1000, 1))
        return store.size

    def add(self, ids: list[int], vectors: np.ndarray) -> None:
        store = self._store()
        with self._lock:
            store.add(ids, vectors)
            store.built_at = time.time()
            store.save(get_settings().index_dir, get_embedder().name)
            self.refresh_keyword_index(force=True)

    def remove(self, ids: list[int]) -> None:
        store = self._store()
        with self._lock:
            store.remove(ids)
            store.save(get_settings().index_dir, get_embedder().name)
            self.refresh_keyword_index(force=True)

    def refresh_keyword_index(self, force: bool = False) -> None:
        store = self._store()
        with self._lock:
            if not force and self._bm25_version == store.version:
                return
            with session_scope() as db:
                rows = db.execute(
                    select(Chunk.id, Chunk.text, Document.conversation_id, Document.title)
                    .join(Document, Document.id == Chunk.document_id)
                    .where(Document.status == "ready")
                ).all()
            # Title is indexed with the chunk text: help pages often only name the module in the title.
            # Build into a fresh object and swap references so concurrent searches never see a
            # half-built index (reference assignment is atomic in CPython).
            bm25 = BM25Index()
            bm25.build([(cid, f"{title}\n{text}") for cid, text, _, title in rows])
            self.bm25, self.chunk_scope = bm25, {cid: conv for cid, _, conv, _ in rows}
            self._bm25_version = store.version

    @property
    def size(self) -> int:
        return self.faiss.size if self.faiss else 0

    @property
    def built_at(self) -> float | None:
        return self.faiss.built_at if self.faiss else None


knowledge_index = KnowledgeIndex()
