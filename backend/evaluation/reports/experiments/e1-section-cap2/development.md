# RAG evaluation (development split) — 2026-10-09 17:33 UTC

Dataset: 92 queries (71 answerable, 21 unanswerable) · corpus: 17 documents / 713 chunks · k=5

## Retrieval ablation

| Config | Recall@5 | Hit@5 | P@5 | MRR | nDCG@5 | Ctx recall | Ctx precision | Gate acc. | Answered (in-scope) | Refused (unanswerable) | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hybrid_rerank | 0.836 | 1.0 | 0.501 | 0.935 | 0.937 | 0.817 | 0.584 | 0.989 | 0.986 | 1.0 | 1023.1 | 1241.2 |

## Stage latency (hybrid_rerank, ms)

| Stage | p50 | p95 |
|---|---:|---:|
| total_ms | 1023.1 | 1241.2 |
| embed_ms | 9.6 | 39.4 |
| semantic_ms | 0.2 | 0.5 |
| keyword_ms | 1.1 | 3.0 |
| fusion_ms | 1.8 | 7.2 |
| rerank_ms | 1002.8 | 1189.2 |
| understanding_ms | 0.07 | 0.16 |
| context_build_ms | 2.29 | 10.11 |

## By question type (hybrid_rerank)

| Type | n | Recall@5 / Refused | MRR | Answered |
|---|---:|---:|---:|---:|
| adversarial | 2 | refused 1.0 | – | – |
| ambiguous | 3 | refused 1.0 | – | – |
| configuration | 11 | 0.864 | 1.0 | 1.0 |
| factual | 18 | 0.88 | 0.84 | 0.944 |
| follow_up | 4 | 0.875 | 1.0 | 1.0 |
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
| rewritten with history | 0.875 | 1.0 | 1.0 |

## Generation

_Not run: run with --generation (requires GEMINI_API_KEY)_
