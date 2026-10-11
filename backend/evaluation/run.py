"""Reproducible RAG evaluation.

    python -m backend.evaluation.run                 # retrieval ablation + refusal + latency (no LLM needed)
    python -m backend.evaluation.run --generation    # + generation metrics (needs GEMINI_API_KEY)
    python -m backend.evaluation.run --generation --judge   # + LLM-as-judge faithfulness
    python -m backend.evaluation.run --check-labels  # verify every label matches the indexed corpus

Datasets: every ``datasets/*.jsonl`` file (version-controlled). Each answerable item
lists ``relevant`` labels ``[url_fragment, phrase]`` that point at real sections of
the crawled help portal; ``--check-labels`` proves each label matches >= 1 chunk.

Two views of retrieval quality are reported for each configuration:

* **Ranking** (top-k *before* the relevance gate): Recall@k, Hit@k, Precision@k, MRR, nDCG@k.
* **Context** (chunks that actually reach the LLM, *after* the gate): recall and precision.

The gate's answer/refuse decisions give in-scope answer rate, out-of-scope refusal
rate and overall gate accuracy. Per-stage latencies are reported as p50/p95.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.db.models import Chunk, Document
from backend.db.session import init_db, session_scope
from backend.evaluation import metrics as M
from backend.services.vector_store import knowledge_index

HERE = Path(__file__).parent
REPORTS = HERE / "reports"
K = 5
CONFIGS = [
    ("semantic", {"mode": "semantic", "rerank": False}),
    ("keyword_bm25", {"mode": "keyword", "rerank": False}),
    ("hybrid", {"mode": "hybrid", "rerank": False}),
    ("hybrid_rerank", {"mode": "hybrid", "rerank": True}),
]


SPLITS = {"development": HERE / "datasets", "heldout": HERE / "heldout"}


def load_dataset(split: str = "development") -> list[dict]:
    """``development``: used while building/tuning. ``heldout``: written after thresholds were frozen."""
    items = []
    for path in sorted(SPLITS[split].glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                item["dataset"] = path.stem
                items.append(item)
    return items


def check_labels(items: list[dict]) -> list[str]:
    with session_scope() as db:
        rows = db.execute(select(Document.source_url, Chunk.section, Chunk.text)
                          .join(Chunk, Chunk.document_id == Document.id)).all()
    problems = []
    for it in items:
        for i, (frag, phrase) in enumerate(it["relevant"]):
            if not any(M.matched_labels(u, s, t, [[frag, phrase]]) for u, s, t in rows):
                problems.append(f"{it['id']}: label #{i} {frag!r}/{phrase!r} matches no chunk")
    return problems


def retrieval_query(item: dict, rewrite: bool = True) -> str:
    """Follow-ups are resolved with the production query-understanding step (heuristic without an LLM)."""
    if item.get("history") and rewrite:
        from backend.services.query_understanding import analyze

        return analyze(item["question"], item["history"]).retrieval_query
    return item["question"]


def _mean(values) -> float:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 3) if values else 0.0


def eval_retrieval(items: list[dict], name: str, opts: dict, rewrite: bool = True) -> dict:
    from backend.services.retrieval import retrieve

    rows, stage_times = [], defaultdict(list)
    for it in items:
        from backend.services.query_understanding import analyze

        # The pipeline asks for clarification instead of retrieving for unresolvable questions;
        # that decision is part of the answer/refuse behaviour being measured.
        skip = not it.get("history") and not analyze(it["question"], []).needs_retrieval
        t0 = time.perf_counter()
        res = retrieve(retrieval_query(it, rewrite), None, top_n=K, **opts)
        total = (time.perf_counter() - t0) * 1000
        if skip:
            res.passed_gate, res.candidates = False, []
        stage_times["total_ms"].append(total)
        for stage, ms in res.timings.items():
            stage_times[stage].append(ms)
        row = {"id": it["id"], "type": it.get("type"), "answerable": it["answerable"],
               "passed_gate": res.passed_gate, "top": [c.title for c in res.ranked[:3]]}
        if it["answerable"]:
            ranked = [M.matched_labels(c.url, c.section, c.text, it["relevant"]) for c in res.ranked[:K]]
            context = [M.matched_labels(c.url, c.section, c.text, it["relevant"]) for c in res.candidates] \
                if res.passed_gate else []
            rels = [bool(m) for m in ranked]
            row.update(
                recall=M.recall_at_k(ranked, len(it["relevant"]), K), hit=M.hit_at_k(rels, K),
                precision=M.precision_at_k(rels, K), mrr=M.mrr(rels), ndcg=M.ndcg_at_k(rels, K),
                context_recall=M.recall_at_k(context, len(it["relevant"]), K),
                context_precision=(sum(bool(m) for m in context) / len(context)) if context else 0.0,
                context_chunks=len(context),
            )
        rows.append(row)

    ans = [r for r in rows if r["answerable"]]
    neg = [r for r in rows if not r["answerable"]]
    by_type: dict[str, dict] = {}
    for t in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == t]
        if sub[0]["answerable"]:
            by_type[t] = {"n": len(sub), f"recall@{K}": _mean(r["recall"] for r in sub), "mrr": _mean(r["mrr"] for r in sub),
                          "answered": _mean(float(r["passed_gate"]) for r in sub)}
        else:
            by_type[t] = {"n": len(sub), "refused": _mean(float(not r["passed_gate"]) for r in sub)}
    return {
        "config": name,
        f"recall@{K}": _mean(r["recall"] for r in ans), f"hit@{K}": _mean(r["hit"] for r in ans),
        f"precision@{K}": _mean(r["precision"] for r in ans), "mrr": _mean(r["mrr"] for r in ans),
        f"ndcg@{K}": _mean(r["ndcg"] for r in ans),
        "context_recall": _mean(r["context_recall"] for r in ans),
        "context_precision": _mean(r["context_precision"] for r in ans if r["passed_gate"]),
        "avg_context_chunks": _mean(r["context_chunks"] for r in ans),
        "answer_rate_in_scope": _mean(float(r["passed_gate"]) for r in ans),
        "refusal_rate_out_of_scope": _mean(float(not r["passed_gate"]) for r in neg),
        "gate_accuracy": round((sum(r["passed_gate"] for r in ans) + sum(not r["passed_gate"] for r in neg)) / len(rows), 3),
        "latency_ms": {stage: {"p50": round(M.percentile(v, 0.5), 1), "p95": round(M.percentile(v, 0.95), 1)}
                       for stage, v in stage_times.items()},
        "by_type": by_type,
        "per_question": rows,
    }


JUDGE_SYSTEM = (
    "You are a strict fact-checking judge. For each numbered CLAIM, answer SUPPORTED only if the CONTEXT "
    "explicitly states it; otherwise UNSUPPORTED. Output one line per claim: '<n>: SUPPORTED' or "
    "'<n>: UNSUPPORTED'. No other text."
)


def judge_faithfulness(llm, answer: str, contexts: list[str]) -> float | None:
    """LLM-as-judge: share of answer sentences the judge marks SUPPORTED by the retrieved context.

    Binary per-claim labels (not a 1-10 'quality' score) so the result is auditable;
    temperature comes from LLM_TEMPERATURE (set it to 0 for evaluation runs).
    """
    from backend.services.llm import ChatTurn

    claims = M.answer_sentences(answer)
    if not claims:
        return None
    prompt = "CONTEXT:\n" + "\n---\n".join(contexts) + "\n\nCLAIMS:\n" + \
        "\n".join(f"{i}: {c}" for i, c in enumerate(claims, start=1))
    out = llm.generate(JUDGE_SYSTEM, [ChatTurn("user", prompt)], max_tokens=16 * len(claims) + 32)
    verdicts = [line.split(":", 1)[1].strip().upper() for line in out.splitlines() if ":" in line]
    if len(verdicts) != len(claims):
        return None  # unparseable judgement is dropped, never counted as a pass
    return sum(v.startswith("SUPPORTED") for v in verdicts) / len(claims)


def eval_generation(items: list[dict], use_judge: bool) -> dict:
    from backend.services import rag_pipeline
    from backend.services.llm import get_llm

    llm = get_llm(required=True)
    rows = []
    for it in items:
        conv_id = None
        if it.get("history"):  # replay the history so the real rewrite path runs
            conv_id = rag_pipeline.answer(it["history"][0]["content"], None)["conversation_id"]
        t0 = time.perf_counter()
        try:
            out = rag_pipeline.answer(it["question"], conv_id)
        except AppError as exc:  # rate limit / outage: record it, never score it
            rows.append({"id": it["id"], "type": it.get("type"), "answerable": it["answerable"], "status": exc.code})
            continue
        if (out.get("metadata") or {}).get("model") == "extractive-fallback":
            # The LLM was unavailable and excerpts were returned instead: not a generated answer, so not scored.
            rows.append({"id": it["id"], "type": it.get("type"), "answerable": it["answerable"], "status": "llm_fallback"})
            continue
        ms = (time.perf_counter() - t0) * 1000
        with session_scope() as db:
            ctx = [c.text for c in (db.get(Chunk, s["chunk_id"]) for s in out["sources"]) if c is not None]
        cited_rel = [bool(M.matched_labels(s["url"], s["section"], s["snippet"], it["relevant"]))
                     for s in out["sources"]] if it["answerable"] else []
        row = {
            "id": it["id"], "type": it.get("type"), "answerable": it["answerable"], "status": "scored",
            "grounded": out["grounded"],
            "refused_correctly": (not out["grounded"]) if not it["answerable"] else None,
            "faithfulness_lexical": M.faithfulness(out["answer"], ctx) if out["grounded"] else None,
            "keyword_correctness": M.keyword_correctness(out["answer"], it["answer_keywords"]) if it["answerable"] else None,
            "citation_precision": M.citation_precision(cited_rel) if cited_rel else None,
            "has_citations": bool(M.CITE.search(out["answer"])) if out["grounded"] else None,
            "confidence": out["confidence"]["score"], "latency_ms": round(ms, 1),
            "llm_ms": out["metadata"]["llm_ms"],
        }
        if use_judge and out["grounded"] and ctx:
            row["faithfulness_judge"] = judge_faithfulness(llm, out["answer"], ctx)
        rows.append(row)
        time.sleep(1.0)  # stay inside free-tier rate limits

    scored = [r for r in rows if r["status"] == "scored"]

    def mean(key, pred=lambda r: True):
        return _mean(r.get(key) for r in scored if pred(r))

    return {
        "model": get_settings().llm_model,
        "faithfulness_lexical": mean("faithfulness_lexical"),
        "faithfulness_judge": mean("faithfulness_judge") if use_judge else None,
        "answer_correctness_keywords": mean("keyword_correctness"),
        "citation_precision": mean("citation_precision"),
        "answers_with_citations": mean("has_citations"),
        "refusal_accuracy_out_of_scope": mean("refused_correctly", lambda r: not r["answerable"]),
        "answered_in_scope": mean("grounded", lambda r: r["answerable"]),
        "status_counts": {k: sum(1 for r in rows if r["status"] == k) for k in sorted({r["status"] for r in rows})},
        "latency_p50_ms": round(M.percentile([r["latency_ms"] for r in scored], 0.5), 1) if scored else None,
        "latency_p95_ms": round(M.percentile([r["latency_ms"] for r in scored], 0.95), 1) if scored else None,
        "llm_p50_ms": round(M.percentile([r["llm_ms"] for r in scored if r["llm_ms"]], 0.5), 1)
        if any(r["llm_ms"] for r in scored) else None,
        "per_question": rows,
    }


def to_markdown(report: dict) -> str:
    d, c = report["dataset"], report["corpus"]
    lines = [f"# RAG evaluation ({report.get('split', 'development')} split) — {report['created_at']}", "",
             f"Dataset: {d['questions']} queries ({d['answerable']} answerable, {d['unanswerable']} unanswerable) · "
             f"corpus: {c['documents']} documents / {c['chunks']} chunks · k={K}", "",
             "## Retrieval ablation", "",
             f"| Config | Recall@{K} | Hit@{K} | P@{K} | MRR | nDCG@{K} | Ctx recall | Ctx precision | Gate acc. | Answered (in-scope) | Refused (unanswerable) | p50 ms | p95 ms |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in report["retrieval"]:
        lat = r["latency_ms"]["total_ms"]
        lines.append(f"| {r['config']} | {r[f'recall@{K}']} | {r[f'hit@{K}']} | {r[f'precision@{K}']} | {r['mrr']} | "
                     f"{r[f'ndcg@{K}']} | {r['context_recall']} | {r['context_precision']} | {r['gate_accuracy']} | "
                     f"{r['answer_rate_in_scope']} | {r['refusal_rate_out_of_scope']} | {lat['p50']} | {lat['p95']} |")
    final = report["retrieval"][-1]
    lines += ["", f"## Stage latency ({final['config']}, ms)", "", "| Stage | p50 | p95 |", "|---|---:|---:|"]
    for stage, v in final["latency_ms"].items():
        lines.append(f"| {stage} | {v['p50']} | {v['p95']} |")
    for stage, v in report.get("pipeline_latency_ms", {}).items():
        lines.append(f"| {stage} | {v['p50']} | {v['p95']} |")
    lines += ["", f"## By question type ({final['config']})", "", "| Type | n | Recall@5 / Refused | MRR | Answered |", "|---|---:|---:|---:|---:|"]
    for t, v in final["by_type"].items():
        if "refused" in v:
            lines.append(f"| {t} | {v['n']} | refused {v['refused']} | – | – |")
        else:
            lines.append(f"| {t} | {v['n']} | {v[f'recall@{K}']} | {v['mrr']} | {v['answered']} |")
    fu = report.get("follow_up_rewrite")
    if fu:
        lines += ["", "## Follow-up rewriting (hybrid_rerank, follow-up questions only)", "",
                  "| Variant | Recall@5 | MRR | Answered |", "|---|---:|---:|---:|",
                  f"| raw follow-up text | {fu['without'][f'recall@{K}']} | {fu['without']['mrr']} | {fu['without']['answered']} |",
                  f"| rewritten with history | {fu['with'][f'recall@{K}']} | {fu['with']['mrr']} | {fu['with']['answered']} |"]
    g = report.get("generation")
    lines += ["", "## Generation", ""]
    if g:
        lines += [f"Model: `{g['model']}`", "", "| Metric | Value |", "|---|---|"]
        for key in ("faithfulness_lexical", "faithfulness_judge", "answer_correctness_keywords", "citation_precision",
                    "answers_with_citations", "refusal_accuracy_out_of_scope", "answered_in_scope",
                    "latency_p50_ms", "latency_p95_ms", "llm_p50_ms"):
            lines.append(f"| {key} | {g[key]} |")
    else:
        lines.append(f"_Not run: {report.get('generation_skipped', 'use --generation')}_")
    return "\n".join(lines) + "\n"


def pipeline_stage_latency(items: list[dict]) -> dict:
    """Non-LLM stages the retriever doesn't time itself: query understanding and context building."""
    from backend.services.context_builder import build_sources_block, select_context
    from backend.services.query_understanding import analyze
    from backend.services.retrieval import retrieve

    und, ctx = [], []
    for it in items:
        t0 = time.perf_counter()
        qa = analyze(it["question"], it.get("history", []))
        und.append((time.perf_counter() - t0) * 1000)
        res = retrieve(qa.retrieval_query, None)
        if res.passed_gate:
            t0 = time.perf_counter()
            build_sources_block(select_context(res.candidates, qa.retrieval_query), qa.retrieval_query)
            ctx.append((time.perf_counter() - t0) * 1000)
    return {"understanding_ms": {"p50": round(M.percentile(und, 0.5), 2), "p95": round(M.percentile(und, 0.95), 2)},
            "context_build_ms": {"p50": round(M.percentile(ctx, 0.5), 2), "p95": round(M.percentile(ctx, 0.95), 2)}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generation", action="store_true")
    ap.add_argument("--judge", action="store_true", help="add LLM-as-judge faithfulness (with --generation)")
    ap.add_argument("--check-labels", action="store_true")
    ap.add_argument("--split", choices=sorted(SPLITS), default="development")
    ap.add_argument("--tag", help="experiment name: write to reports/experiments/<tag>/ and leave latest.* untouched")
    ap.add_argument("--only", action="append", choices=[n for n, _ in CONFIGS], help="run only these configs")
    args = ap.parse_args()

    from backend.core.logging import configure_logging
    configure_logging("WARNING", as_json=False)
    init_db()
    knowledge_index.load_or_build()
    items = load_dataset(args.split)

    problems = check_labels(items)
    if args.check_labels:
        print("\n".join(problems) or f"All labels of {len(items)} queries match the corpus.")
        return
    if problems:
        print("WARNING: some labels match no chunk:\n  " + "\n  ".join(problems))

    with session_scope() as db:
        n_docs = db.scalar(select(func.count(Document.id)).where(Document.conversation_id.is_(None)))
        n_chunks = db.scalar(select(func.count(Chunk.id)))
    s = get_settings()
    # Warm-up: first calls pay one-off ONNX graph initialisation; don't count it as query latency.
    from backend.services.retrieval import retrieve
    retrieve("warm up attendance", None)

    report = {
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "split": args.split,
        "dataset": {"questions": len(items), "answerable": sum(i["answerable"] for i in items),
                    "unanswerable": sum(not i["answerable"] for i in items),
                    "files": sorted({i["dataset"] for i in items}),
                    "types": dict(sorted(defaultdict(int, {t: sum(1 for i in items if i.get("type") == t)
                                                           for t in {i.get("type") for i in items}}).items()))},
        "corpus": {"documents": n_docs, "chunks": n_chunks},
        "settings": {"embedding_model": s.embedding_model, "reranker": s.reranker_model if s.reranker != "none" else "none",
                     "semantic_weight": s.hybrid_semantic_weight, "keyword_weight": s.hybrid_keyword_weight,
                     "min_semantic_score": s.min_semantic_score, "min_rerank_score": s.min_rerank_score,
                     "min_context_rerank_score": s.min_context_rerank_score, "rerank_candidates": s.rerank_candidates,
                     "chunk_size": s.chunk_size, "chunk_overlap": s.chunk_overlap, "k": K,
                     "max_chunks_per_section": s.max_chunks_per_section, "rerank_max_chars": s.rerank_max_chars},
        "tag": args.tag,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "label_problems": problems,
        "retrieval": [eval_retrieval(items, name, opts) for name, opts in CONFIGS if not args.only or name in args.only],
        "pipeline_latency_ms": pipeline_stage_latency(items),
    }
    followups = [i for i in items if i.get("history")]
    if followups:
        def summary(r):
            ans = [q for q in r["per_question"] if q["answerable"]]
            return {f"recall@{K}": _mean(q["recall"] for q in ans), "mrr": _mean(q["mrr"] for q in ans),
                    "answered": _mean(float(q["passed_gate"]) for q in ans)}
        report["follow_up_rewrite"] = {
            "n": len(followups),
            "without": summary(eval_retrieval(followups, "raw", CONFIGS[-1][1], rewrite=False)),
            "with": summary(eval_retrieval(followups, "rewritten", CONFIGS[-1][1], rewrite=True)),
            "rewriter": "llm" if s.llm_configured else "heuristic (no GEMINI_API_KEY)",
        }
    report["configs"] = [{k: v for k, v in r.items() if k not in ("per_question", "by_type", "latency_ms")}
                         | {"latency_p50_ms": r["latency_ms"]["total_ms"]["p50"],
                            "latency_p95_ms": r["latency_ms"]["total_ms"]["p95"]} for r in report["retrieval"]]
    if args.generation:
        if s.llm_configured:
            report["generation"] = eval_generation(items, args.judge)
        else:
            report["generation_skipped"] = "Live generation testing requires GEMINI_API_KEY."
    else:
        report["generation_skipped"] = "run with --generation (requires GEMINI_API_KEY)"

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = json.dumps(report, indent=2, default=str)
    md = to_markdown(report)
    if args.tag:  # experiments never overwrite the baseline reports
        out = REPORTS / "experiments" / args.tag
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.split}.json").write_text(payload, encoding="utf-8")
        (out / f"{args.split}.md").write_text(md, encoding="utf-8")
        print(md)
        return
    REPORTS.mkdir(exist_ok=True)
    prefix = "" if args.split == "development" else f"{args.split}_"
    (REPORTS / f"{prefix}{stamp}.json").write_text(payload, encoding="utf-8")
    (REPORTS / f"{prefix}latest.json").write_text(payload, encoding="utf-8")
    (REPORTS / f"{prefix}latest.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
