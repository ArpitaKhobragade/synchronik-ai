# RAG evaluation (development split) — 2026-10-10 04:48 UTC

Dataset: 92 queries (71 answerable, 21 unanswerable) · corpus: 18 documents / 733 chunks · k=5

## Retrieval ablation

| Config | Recall@5 | Hit@5 | P@5 | MRR | nDCG@5 | Ctx recall | Ctx precision | Gate acc. | Answered (in-scope) | Refused (unanswerable) | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| semantic | 0.8 | 0.972 | 0.454 | 0.898 | 0.901 | 0.8 | 0.462 | 0.87 | 1.0 | 0.429 | 5.7 | 43.7 |
| keyword_bm25 | 0.756 | 0.944 | 0.434 | 0.836 | 0.844 | 0.756 | 0.434 | 0.804 | 1.0 | 0.143 | 2.0 | 4.9 |
| hybrid | 0.81 | 0.972 | 0.459 | 0.902 | 0.91 | 0.81 | 0.483 | 0.88 | 1.0 | 0.476 | 6.4 | 8.7 |
| hybrid_rerank | 0.811 | 0.986 | 0.499 | 0.92 | 0.926 | 0.809 | 0.57 | 0.957 | 1.0 | 0.81 | 880.1 | 1023.7 |

## Stage latency (hybrid_rerank, ms)

| Stage | p50 | p95 |
|---|---:|---:|
| total_ms | 880.1 | 1023.7 |
| embed_ms | 13.2 | 69.0 |
| semantic_ms | 0.2 | 0.5 |
| keyword_ms | 1.0 | 1.7 |
| fusion_ms | 1.5 | 3.8 |
| rerank_ms | 863.0 | 1005.3 |
| understanding_ms | 0.03 | 0.05 |
| context_build_ms | 1.47 | 2.78 |

## By question type (hybrid_rerank)

| Type | n | Recall@5 / Refused | MRR | Answered |
|---|---:|---:|---:|---:|
| adversarial | 2 | refused 1.0 | – | – |
| ambiguous | 3 | refused 1.0 | – | – |
| configuration | 11 | 0.864 | 1.0 | 1.0 |
| factual | 18 | 0.81 | 0.781 | 1.0 |
| follow_up | 4 | 0.792 | 1.0 | 1.0 |
| general_knowledge | 8 | refused 0.875 | – | – |
| module | 5 | 0.373 | 0.75 | 1.0 |
| multi_hop | 3 | 0.75 | 0.833 | 1.0 |
| procedural | 21 | 0.908 | 1.0 | 1.0 |
| troubleshooting | 9 | 0.796 | 1.0 | 1.0 |
| unsupported_erp | 8 | refused 0.625 | – | – |

## Follow-up rewriting (hybrid_rerank, follow-up questions only)

| Variant | Recall@5 | MRR | Answered |
|---|---:|---:|---:|
| raw follow-up text | 0.458 | 0.625 | 1.0 |
| rewritten with history | 0.792 | 1.0 | 1.0 |

## Generation

_Not run: run with --generation (requires GEMINI_API_KEY)_
