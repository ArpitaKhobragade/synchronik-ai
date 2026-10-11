# RAG evaluation (development split) — 2026-10-04 14:12 UTC

Dataset: 92 queries (71 answerable, 21 unanswerable) · corpus: 17 documents / 714 chunks · k=5

## Retrieval ablation

| Config | Recall@5 | Hit@5 | P@5 | MRR | nDCG@5 | Ctx recall | Ctx precision | Gate acc. | Answered (in-scope) | Refused (unanswerable) | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| semantic | 0.817 | 0.986 | 0.465 | 0.927 | 0.924 | 0.817 | 0.474 | 0.88 | 1.0 | 0.476 | 9.4 | 45.5 |
| keyword_bm25 | 0.756 | 0.944 | 0.434 | 0.85 | 0.853 | 0.756 | 0.434 | 0.804 | 1.0 | 0.143 | 2.3 | 13.9 |
| hybrid | 0.81 | 0.972 | 0.465 | 0.916 | 0.92 | 0.81 | 0.48 | 0.891 | 1.0 | 0.524 | 10.3 | 30.7 |
| hybrid_rerank | 0.831 | 1.0 | 0.513 | 0.935 | 0.94 | 0.812 | 0.59 | 0.989 | 0.986 | 1.0 | 952.5 | 1210.9 |

## Stage latency (hybrid_rerank, ms)

| Stage | p50 | p95 |
|---|---:|---:|
| total_ms | 952.5 | 1210.9 |
| embed_ms | 6.3 | 44.6 |
| semantic_ms | 0.2 | 0.4 |
| keyword_ms | 1.1 | 3.4 |
| fusion_ms | 1.5 | 13.6 |
| rerank_ms | 931.5 | 1201.1 |
| understanding_ms | 0.04 | 0.06 |
| context_build_ms | 1.93 | 4.47 |

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
