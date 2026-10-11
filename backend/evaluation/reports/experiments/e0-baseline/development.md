# RAG evaluation (development split) — 2026-10-09 17:27 UTC

Dataset: 92 queries (71 answerable, 21 unanswerable) · corpus: 17 documents / 713 chunks · k=5

## Retrieval ablation

| Config | Recall@5 | Hit@5 | P@5 | MRR | nDCG@5 | Ctx recall | Ctx precision | Gate acc. | Answered (in-scope) | Refused (unanswerable) | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hybrid_rerank | 0.831 | 1.0 | 0.513 | 0.935 | 0.94 | 0.812 | 0.59 | 0.989 | 0.986 | 1.0 | 864.4 | 933.0 |

## Stage latency (hybrid_rerank, ms)

| Stage | p50 | p95 |
|---|---:|---:|
| total_ms | 864.4 | 933.0 |
| embed_ms | 14.9 | 73.7 |
| semantic_ms | 0.2 | 0.5 |
| keyword_ms | 1.0 | 1.7 |
| fusion_ms | 1.6 | 3.7 |
| rerank_ms | 838.5 | 916.8 |
| understanding_ms | 0.04 | 0.05 |
| context_build_ms | 1.64 | 2.65 |

## By question type (hybrid_rerank)

| Type | n | Recall@5 / Refused | MRR | Answered |
|---|---:|---:|---:|---:|
| adversarial | 2 | refused 1.0 | – | – |
| ambiguous | 3 | refused 1.0 | – | – |
| configuration | 11 | 0.864 | 1.0 | 1.0 |
| factual | 18 | 0.88 | 0.84 | 0.944 |
| follow_up | 4 | 0.792 | 1.0 | 1.0 |
| general_knowledge | 8 | refused 1.0 | – | – |
| module | 5 | 0.407 | 0.75 | 1.0 |
| multi_hop | 3 | 0.75 | 0.833 | 1.0 |
| procedural | 21 | 0.908 | 1.0 | 1.0 |
| troubleshooting | 9 | 0.796 | 1.0 | 1.0 |
| unsupported_erp | 8 | refused 1.0 | – | – |

## Follow-up rewriting (hybrid_rerank, follow-up questions only)

| Variant | Recall@5 | MRR | Answered |
|---|---:|---:|---:|
| raw follow-up text | 0.458 | 0.625 | 1.0 |
| rewritten with history | 0.792 | 1.0 | 1.0 |

## Generation

_Not run: run with --generation (requires GEMINI_API_KEY)_
