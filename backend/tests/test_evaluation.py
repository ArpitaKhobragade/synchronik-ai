"""Evaluation tests: metric correctness + a representative-question regression on the real corpus.

The corpus test runs only when a crawled index exists (``data/``); it guards
against retrieval regressions using thresholds below the measured baseline.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.evaluation import metrics as M

ROOT = Path(__file__).resolve().parents[2]


def test_rank_metrics():
    assert M.mrr([False, True, False]) == 0.5
    assert M.precision_at_k([True, False, True, False, False], 5) == 0.4
    assert M.hit_at_k([False, False], 2) == 0.0
    assert M.recall_at_k([{0}, set(), {0, 2}], total_labels=4, k=3) == 0.5
    assert M.ndcg_at_k([True, False], 2) == 1.0


def test_faithfulness_and_keywords():
    ctx = ["Attendance is marked per lecture by the faculty member."]
    assert M.faithfulness("Attendance is marked per lecture by the faculty [1].", ctx) == 1.0
    assert M.faithfulness("Bitcoin prices doubled yesterday in Tokyo markets.", ctx) == 0.0
    assert M.keyword_correctness("Use the HOD approval", ["hod", "approval"]) == 1.0


def test_dataset_is_well_formed():
    from backend.evaluation.run import load_dataset

    rows = load_dataset()
    assert len({r["id"] for r in rows}) == len(rows) >= 80
    assert all(r.get("type") for r in rows)
    assert all(r["history"][0]["role"] == "user" for r in rows if r.get("history"))
    assert all(r["relevant"] for r in rows if r["answerable"])
    assert sum(not r["answerable"] for r in rows) >= 5


@pytest.mark.skipif(not (ROOT / "data/synchronik.db").exists(), reason="no crawled corpus (run the crawler first)")
def test_representative_questions_on_real_corpus(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{ROOT / 'data/synchronik.db'}")
    monkeypatch.setenv("RERANKER", "none")
    from backend.core.config import get_settings
    from backend.db import session as dbs
    from backend.services import embeddings, reranker, vector_store
    import backend.services.retrieval as retrieval

    get_settings.cache_clear(); dbs.reset_engine()
    embeddings.set_embedder(None); reranker.set_reranker(None)
    idx = vector_store.KnowledgeIndex()
    monkeypatch.setattr(retrieval, "knowledge_index", idx)
    idx.load_or_build()
    try:
        for q, frag in [("How do late fine rules work for fee payments?", "how-to"),
                        ("Why is the Freeze button greyed out on marks entry?", "faq"),
                        ("Where do I find library reports?", "where-to-find")]:
            res = retrieval.retrieve(q, None, rerank=False)
            assert res.passed_gate and frag in (res.candidates[0].url or "")
        assert not retrieval.retrieve("Give me a good recipe for pasta carbonara.", None, rerank=False).passed_gate
    finally:
        embeddings.set_embedder(None); reranker.set_reranker(None)
        dbs.reset_engine(); get_settings.cache_clear()
