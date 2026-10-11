# RAG evaluation (heldout split) — 2026-10-10 04:51 UTC

Dataset: 20 queries (15 answerable, 5 unanswerable) · corpus: 18 documents / 733 chunks · k=5

## Retrieval ablation

| Config | Recall@5 | Hit@5 | P@5 | MRR | nDCG@5 | Ctx recall | Ctx precision | Gate acc. | Answered (in-scope) | Refused (unanswerable) | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| semantic | 1.0 | 1.0 | 0.4 | 0.9 | 0.923 | 1.0 | 0.42 | 0.85 | 1.0 | 0.4 | 9.5 | 29.0 |
| keyword_bm25 | 0.933 | 0.933 | 0.427 | 0.75 | 0.767 | 0.933 | 0.427 | 0.85 | 1.0 | 0.4 | 2.1 | 5.6 |
| hybrid | 1.0 | 1.0 | 0.453 | 0.889 | 0.914 | 1.0 | 0.473 | 0.85 | 1.0 | 0.4 | 16.3 | 29.9 |
| hybrid_rerank | 1.0 | 1.0 | 0.413 | 0.922 | 0.924 | 1.0 | 0.492 | 0.9 | 1.0 | 0.6 | 912.7 | 1009.4 |

## Stage latency (hybrid_rerank, ms)

| Stage | p50 | p95 |
|---|---:|---:|
| total_ms | 912.7 | 1009.4 |
| embed_ms | 14.4 | 49.4 |
| semantic_ms | 0.2 | 0.4 |
| keyword_ms | 1.1 | 7.8 |
| fusion_ms | 1.4 | 4.2 |
| rerank_ms | 891.9 | 973.2 |
| understanding_ms | 0.03 | 0.05 |
| context_build_ms | 1.42 | 2.27 |

## By question type (hybrid_rerank)

| Type | n | Recall@5 / Refused | MRR | Answered |
|---|---:|---:|---:|---:|
| ambiguous | 1 | refused 1.0 | – | – |
| configuration | 3 | 1.0 | 1.0 | 1.0 |
| factual | 4 | 1.0 | 1.0 | 1.0 |
| general_knowledge | 1 | refused 1.0 | – | – |
| multi_hop | 1 | 1.0 | 1.0 | 1.0 |
| procedural | 5 | 1.0 | 0.9 | 1.0 |
| troubleshooting | 2 | 1.0 | 0.667 | 1.0 |
| unsupported_erp | 3 | refused 0.333 | – | – |

## Generation

_Not run: run with --generation (requires GEMINI_API_KEY)_
