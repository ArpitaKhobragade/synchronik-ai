# RAG evaluation (heldout split) — 2026-10-04 14:37 UTC

Dataset: 20 queries (15 answerable, 5 unanswerable) · corpus: 17 documents / 713 chunks · k=5

## Retrieval ablation

| Config | Recall@5 | Hit@5 | P@5 | MRR | nDCG@5 | Ctx recall | Ctx precision | Gate acc. | Answered (in-scope) | Refused (unanswerable) | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| semantic | 1.0 | 1.0 | 0.4 | 0.9 | 0.923 | 1.0 | 0.42 | 0.9 | 1.0 | 0.6 | 7.2 | 46.0 |
| keyword_bm25 | 1.0 | 1.0 | 0.44 | 0.763 | 0.794 | 1.0 | 0.44 | 0.85 | 1.0 | 0.4 | 2.7 | 43.4 |
| hybrid | 1.0 | 1.0 | 0.453 | 0.9 | 0.923 | 1.0 | 0.473 | 0.9 | 1.0 | 0.6 | 10.2 | 50.3 |
| hybrid_rerank | 1.0 | 1.0 | 0.413 | 0.933 | 0.933 | 1.0 | 0.492 | 0.95 | 1.0 | 0.8 | 897.8 | 1083.8 |

## Stage latency (hybrid_rerank, ms)

| Stage | p50 | p95 |
|---|---:|---:|
| total_ms | 897.8 | 1083.8 |
| embed_ms | 7.5 | 25.6 |
| semantic_ms | 0.2 | 0.3 |
| keyword_ms | 1.0 | 1.5 |
| fusion_ms | 1.4 | 2.4 |
| rerank_ms | 889.7 | 1077.0 |
| understanding_ms | 0.04 | 0.04 |
| context_build_ms | 1.78 | 2.3 |

## By question type (hybrid_rerank)

| Type | n | Recall@5 / Refused | MRR | Answered |
|---|---:|---:|---:|---:|
| ambiguous | 1 | refused 1.0 | – | – |
| configuration | 3 | 1.0 | 1.0 | 1.0 |
| factual | 4 | 1.0 | 1.0 | 1.0 |
| general_knowledge | 1 | refused 1.0 | – | – |
| multi_hop | 1 | 1.0 | 1.0 | 1.0 |
| procedural | 5 | 1.0 | 0.9 | 1.0 |
| troubleshooting | 2 | 1.0 | 0.75 | 1.0 |
| unsupported_erp | 3 | refused 0.667 | – | – |

## Generation

_Not run: run with --generation (requires GEMINI_API_KEY)_
