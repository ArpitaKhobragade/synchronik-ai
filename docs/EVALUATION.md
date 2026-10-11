# Evaluation

> **Read this first.** Both evaluation sets were written by the developer against the crawled
> help portal, and the development set was used while tuning the
> system. Treat the numbers as **regression baselines for this project, not an independent benchmark**.
> They are likely optimistic.

## Datasets

| Split | Location | Queries | Answerable | Unanswerable | Used for tuning? |
|---|---|---:|---:|---:|---|
| Development | `backend/evaluation/datasets/*.jsonl` | 92 | 71 | 21 | **Yes**: thresholds, the context cutoff and the ambiguity rule were chosen while looking at it |
| Held-out | `backend/evaluation/heldout/heldout.jsonl` | 20 | 15 | 5 | **No**: written after thresholds were frozen. Run three times on 2026-10-04 with identical settings and identical results; nothing was changed in response |

Corpus: 17 pages of `help.synchronik.co.in` (713 chunks; one development run recorded 714). Every query has a `type`:

**Reproducibility check (2026-10-09):** both splits were re-run on the same corpus with no LLM key, and every quality
metric (Recall@5, Hit@5, P@5, MRR, nDCG@5, context recall/precision, gate accuracy, answer and refusal rates) matched
the committed reports exactly, for all four configurations.

- **Answerable:** factual, procedural, configuration, troubleshooting, module, multi_hop, follow_up (with conversation `history`).
- **Unanswerable:** general_knowledge, unsupported_erp (ERP features the docs never mention), ambiguous, adversarial (prompt-injection phrasing).

### How labels were created

- Each answerable query lists `relevant` labels `[url_fragment, phrase]`. A chunk counts as relevant when its page URL contains the fragment and the phrase appears in the chunk's section heading or text.
- Labels were written by reading the crawled section headings and snippets.
- `python -m backend.evaluation.run --check-labels` (add `--split heldout` for the held-out set) verifies that every label matches at least one chunk.
- Unsupported-feature queries were checked to have **zero occurrences** of their key term in the corpus (e.g. "salary slip", "biometric", "Moodle", "hostel room").
- No independent annotator has reviewed the labels.

## Metrics

**Ranking**, measured on the top 5 *before* the relevance gate:

| Metric | Definition |
|---|---|
| Recall@5 | Share of a query's labelled answer locations covered by at least one top-5 chunk (label-level; 1.0 is often unreachable when a question has more than 5 valid locations) |
| Hit@5 | 1 if any top-5 chunk is relevant |
| Precision@5 | Relevant chunks among the top 5 |
| MRR | 1 / rank of the first relevant chunk |
| nDCG@5 | Binary-relevance discounted gain |

**Context and gate**, measured *after* the relevance gate and context selection, i.e. on what the LLM would actually see:

| Metric | Definition |
|---|---|
| Context precision | Relevant chunks among the chunks kept for the prompt (answered queries only) |
| Context recall | Recall@5 restricted to the kept chunks |
| Gate accuracy | (answerable queries answered + unanswerable queries refused or sent to clarification) / all queries |

Gate accuracy scores the *documentation* decision: answer from the docs, or not. Since 2026-10-10 the default
`GENERAL_ANSWERS=true` sends general-knowledge questions that fail the gate to an uncited general answer
instead of a refusal, while undocumented ERP questions are still refused. The retrieval metrics are unaffected (no
model is called during the retrieval evaluation), but "refused" for general-knowledge items now means "not answered
from the documentation".

**Generation** metrics in `run.py --generation` are implemented but **have not been run**. Answer quality was
instead measured with the separate answer-quality pipeline (`answers.py`), run on 2026-10-10 (see below).

| Metric | Definition |
|---|---|
| Lexical faithfulness | Share of answer sentences whose content words are ≥ 50% present in the retrieved context. Deterministic, blind to paraphrase |
| LLM-as-judge faithfulness (`--judge`) | The judge labels each answer sentence SUPPORTED/UNSUPPORTED against the context. Binary per-claim labels, and an unparseable verdict is dropped rather than counted as a pass |
| Citation precision | Cited sources that match a relevance label |
| Keyword correctness | Expected answer keywords present in the answer |
| Refusal accuracy | Unanswerable queries that end with no grounded answer |

## Results: development set (92 queries)

| Retrieval | Recall@5 | MRR | Context precision | Gate accuracy | p50 retrieval latency |
|---|---:|---:|---:|---:|---:|
| Semantic (FAISS) | 0.817 | 0.927 | 0.474 | 0.880 | ~10 ms |
| Keyword (BM25) | 0.756 | 0.850 | 0.434 | 0.804 | ~3 ms |
| Hybrid | 0.810 | 0.916 | 0.480 | 0.891 | ~10 ms |
| **Hybrid + rerank** | **0.831** | **0.935** | **0.590** | **0.989** | ~1.0–1.2 s |

- **Follow-up rewriting** (4 follow-up queries, using the rule-based rewriter since no LLM key was available): Recall@5 0.458 → 0.792 and MRR 0.625 → 1.0.
- **Gate errors (hybrid + rerank):** one answerable factual question was refused. All 21 unanswerable queries were refused or sent to clarification.
- **Caveat:** the ambiguity rule was added after the ambiguous queries failed, and it is scored on the same queries.

## Results: held-out set (20 queries, thresholds frozen)

| Retrieval | Recall@5 | MRR | Context precision | Gate accuracy |
|---|---:|---:|---:|---:|
| Semantic | 1.000 | 0.900 | 0.420 | 0.90 |
| Keyword | 1.000 | 0.763 | 0.440 | 0.85 |
| Hybrid | 1.000 | 0.900 | 0.473 | 0.90 |
| **Hybrid + rerank** | 1.000 | **0.933** | **0.492** | **0.95** |

- Recall@5 saturates because held-out questions mostly have one labelled section, so this set doesn't separate the configurations on recall. MRR, context precision and gate accuracy do separate them, in the same order as on the development set.
- **Failure:** "How do I allot hostel rooms to students?" was answered, because the docs discuss hostel *fees*. It's left unfixed to keep the held-out set honest.
- With only 20 queries, one query moves gate accuracy by 0.05.

## Why reranking changes Recall@5

On the original 40-query seed set, reranking first *lowered* Recall@5 (0.713 → 0.658). Diagnosis:

1. **About 0.022 was the metric, not a quality loss.** In 4 queries the reranker concentrated the top 5 on one strongly relevant location instead of spreading across several labelled ones, and Precision@5 went up. Label-level recall rewards breadth.
2. **About 0.033 was over-filtering.** The 0.10 gate threshold was also used to drop individual chunks, which cut relevant lower-ranked chunks. Fix: a separate per-chunk cutoff `MIN_CONTEXT_RERANK_SCORE=0.02`. A sweep gave context recall/precision of 0.658/0.705 at 0.10 versus 0.681/0.675 at 0.02. This value was chosen on the seed set. (The sweep figures are not in any saved report: treat them as unverified.)

On the 92-query set, reranking is now best on both ranking and context metrics.

## Latency methodology

- `time.perf_counter()` around each stage in `services/retrieval.py` and `services/rag_pipeline.py`. The evaluation reports p50/p95 per stage after one warm-up query.
- Hardware: a Windows laptop CPU, ONNX Runtime, with other applications running. Repeated runs varied by up to about 3× for reranking.
- Production latency will differ and also includes Gemini generation, which hasn't been measured here.

| Stage (hybrid + rerank, development run `20261004-184054`; later runs: rerank p50 931–1,166 ms on 2026-10-04 and 846 ms on 2026-10-09) | p50 | p95 |
|---|---:|---:|
| Query understanding | 0.03 ms | 0.05 ms |
| Query embedding (MiniLM, ONNX) | 12 ms | 54 ms |
| FAISS search | 0.3 ms | 0.6 ms |
| BM25 search | 1.5 ms | 7–18 ms |
| Fusion + DB hydration | 2 ms | 11 ms |
| **Cross-encoder rerank (12 candidates)** | **~1,050 ms** | **~1,230 ms** |
| Context building | 2.8 ms | 6.7 ms |
| Gemini generation | not measured | not measured |

## Retrieval diagnostics (2026-10-09, development split)

`backend/evaluation/diagnose.py` explains *why* queries score what they score. It is read-only and writes no reports.
Findings on the 713-chunk corpus with the shipped hybrid + rerank configuration:

| Finding | Evidence | Command |
|---|---|---|
| Two pages dominate the corpus | `where-to-find` 257 chunks + `how-to` 200 = 64%. No duplicate chunks; median chunk 705 chars | `diagnose corpus` |
| Long sections crowd the top 5 | 41 top-5 slots across 28 of 71 answerable queries repeat a (document, section) already ranked. E.g. all 5 OBE results are fragments of one report table | `diagnose scores`, `diagnose query --type module` |
| Low-score context chunks are mostly off-label | Chunks with rerank score ≥ 0.75 match a label 67% of the time (147/220); below 0.10, 17% (4/23) | `diagnose scores` |
| Part of the low context precision is labelling | 134 of 311 context chunks (43%) match no label. Inspection shows a mix of relevant-but-unlabelled chunks (e.g. "Generate a report" for an exam-reports question) and real off-topic ones (e.g. "Freeze **marks**" for a course-registration freeze question). Not quantified | `diagnose misses` |
| The rerank pool caps recall | Label recall of the fused candidate list at depth 5 / 12 / 24 / 40: 0.822 / **0.910** / 0.952 / 0.956. The reranker sees 12. For module questions: 0.513 / **0.580** / 0.720 / 0.720 | `diagnose pool` |
| Module overviews are thin in the docs | Only `common_base` §4 "Modules at a Glance" (one line per module, 14 modules; Library is not listed) and short intros in `where-to-find`. No per-module overview pages | `diagnose query --type module` |

### Experiments

Run with `python -m backend.evaluation.run --tag <name> --only hybrid_rerank`. Results are in
`backend/evaluation/reports/experiments/<name>/`; the reference reports are never overwritten. Adoption criteria were
written down before each run. Development split only; the held-out split is reserved for a final check.

| Experiment | Recall@5 | MRR | Ctx recall | Ctx precision | Gate acc. | Decision |
|---|---:|---:|---:|---:|---:|---|
| e0 baseline (same harness) | 0.831 | 0.935 | 0.812 | 0.590 | 0.989 | reproduces `latest.json` exactly |
| e1 section diversity, cap 1 (`MAX_CHUNKS_PER_SECTION=1`) | 0.836 | 0.937 | 0.817 | 0.546 | 0.989 | **rejected**: context precision fell |
| e1 section diversity, cap 2 | 0.836 | 0.935 | 0.817 | 0.584 | 0.989 | **rejected**: context precision fell; module recall unchanged (0.407) |
| e2 context cutoff 0.05 (`MIN_CONTEXT_RERANK_SCORE=0.05`) | 0.831 | 0.935 | 0.810 | 0.606 | 0.989 | **not adopted yet**: one dev run only; the 0.10 run and the held-out check were not done |

**Curated FAQ added (2026-10-10, `e4-faq-added`, both splits, same settings as the baseline).** The knowledge base gained
`backend/knowledge/synchronik-overview.html` (17 sections from synchronik.co.in and the help portal):

| Hybrid + rerank | Recall@5 | MRR | Ctx precision | Gate acc. | Out-of-scope declined |
|---|---:|---:|---:|---:|---:|
| Development: baseline → with FAQ | 0.831 → 0.811 | 0.935 → 0.920 | 0.590 → 0.570 | 0.989 → 0.957 | 1.00 → 0.81 |
| Held-out: baseline → with FAQ | 1.000 → 1.000 | 0.933 → 0.922 | 0.492 → 0.492 | 0.95 → 0.90 | 0.80 → 0.60 |

Read these drops with the question-level changes, not as a plain regression:

- **Labels are now out of date for two "unanswerable" questions.** "How do I connect a biometric fingerprint device?"
  and "Can the ERP mark attendance using face recognition?" were labelled unsupported because the help portal never
  mentions them; Synchronik's website (now in the FAQ) says SackInfo integrates biometric and face-detection devices.
- **One false refusal was fixed:** "How does the ERP keep data separate between institutes?" is now answered.
- **Ranking drops are mostly unlabelled-but-relevant FAQ hits** ("What user types and roles exist?", "Which browser
  should I use?"): the FAQ section ranks first but is not in the labels.
- **Three off-topic questions now pass the retrieval gate on the FAQ's broad sections** (share price, Zoom classes,
  casual leave). Live, all three end on the general path: the documentation prompt declines and the question is handed
  over, so no Synchronik feature is invented. They do cost one extra model call each.

The labels were not edited, to keep the baseline comparable; updating them (and adding FAQ answer locations) is a
listed next step.

Diversity did not help because the missing sections are not in the 12-candidate rerank pool at all, so reordering
cannot surface them. Not yet run: a larger rerank pool (18 / 24 candidates), which the pool analysis points to, at a
latency cost roughly proportional to the pool size. Section diversity remains available but is off by default.

## Answer-quality evaluation (first run: 2026-10-10)

`backend/evaluation/answers.py` scores what the assistant actually says, separately from retrieval. It calls the real
pipeline (`rag_pipeline.answer`) and deletes the conversations it creates.

**Setup of the run:** `gemini-3.5-flash-lite`, `RERANKER=none` and `GENERAL_ANSWERS=true` (the deployed configuration),
the 18-document corpus including the curated FAQ, 5 s between requests. Report:
`reports/answers/answers_20261010-103545_rescored.*` (local; answer runs are not committed).

**Dataset:** `answers/answer_set.jsonl`, 23 items: 18 answerable (procedural, troubleshooting, configuration, module,
FAQ) and 5 not answerable from the documentation (3 undocumented ERP features, 1 off-topic, 1 prompt injection). Each
answerable item has a reference answer, atomic key facts and evidence quotes; `--check` verifies every quote exists
verbatim in the cited section (23/23). References were drafted from the quoted sources and are **pending human review**.
Several questions overlap the retrieval sets. With general answers on, an undocumented question counts as handled
correctly when it gets no documentation-cited answer and no leak. (At the time of the recorded run the scorer also
required a "General answer" label; the label and that check were removed later the same day.)

| Measure | Result | What it means |
|---|---:|---|
| Items scored / fallback | 22 / 1 | One request hit a momentary Gemini failure and got the labelled excerpt fallback; retried alone, it was answered correctly |
| Answerable questions answered from the documentation | 18 / 18 | None fell through to a general answer |
| Key-fact coverage (mean) | 0.924 | Share of each reference's atomic facts present |
| Fully complete by key facts | 15 / 18 | Misses: late-fine nightly job; company founding year and city; "only SuperAdmin crosses tenants" |
| Evidence section retrieved | 17 / 18 | The miss (data separation) was answered from the FAQ, an equally valid source not in the label |
| Citations pointing to a returned source | 18 / 18 | After fixing the metric (it first compared against the number of sources, not their ids) |
| Citation support (cited sentence vs cited chunks, lexical) | 0.979 | |
| Lexical faithfulness | 0.957 | |
| Undocumented / off-topic handled correctly | 4 / 4 (+1 on retry) | No fake citations. At the time of this run general answers carried a "General answer" label; the label was removed from the UI later on 2026-10-10 |
| Secret or prompt leaks | 0 | |
| LLM judge, documentation answers | 18 correct, 0 partial, 0 incorrect, 0 invented features | Supplementary; it rated two answers "correct" that key facts show are incomplete |
| LLM judge, general answers | 0 state Synchronik specifics as fact; 2 / 3 "helpful" | It called "Canberra" unhelpful, apparently for being off-topic for an ERP assistant: a judge quirk |

**Caveats.** 23 items is a small sample, written by the developer, and the judge is the same model family that
generated the answers. These results show the answer path works end to end and flag concrete gaps (completeness on
broad questions); they are not an independent accuracy benchmark. The human-review sheet
(`human_review_<stamp>.csv`) has not been filled in yet.

## Reproduce

```bash
python -m backend.crawler.crawler help_portal                # corpus (polite crawl)
python -m backend.evaluation.run                             # development split
python -m backend.evaluation.run --split heldout             # held-out split
python -m backend.evaluation.run --check-labels              # every label matches the corpus
python -m backend.evaluation.diagnose pool                   # retrieval diagnostics (see above)
python -m backend.evaluation.answers --check                 # answer-set evidence quotes exist
python -m backend.evaluation.answers [--judge] [--id ITEM]     # answer quality: needs GEMINI_API_KEY with quota
python -m backend.evaluation.answers --rescore FILE.json      # recompute metrics of a saved run (no LLM calls)
```

Reports are written to `backend/evaluation/reports/` (`latest.*`, `heldout_latest.*`) and served to admins at
`GET /api/admin/evaluation`. Answer-quality runs go to `reports/answers/` (not committed).
