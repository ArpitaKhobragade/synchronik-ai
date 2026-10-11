"""Retrieval diagnostics: why a query scores what it scores.

    python -m backend.evaluation.diagnose corpus                 # chunk-size / duplicate / per-page statistics
    python -m backend.evaluation.diagnose query --type module    # every dev query of a type, chunk by chunk
    python -m backend.evaluation.diagnose query --id q12 [--split heldout]
    python -m backend.evaluation.diagnose misses                 # context chunks that match no label (dev split)
    python -m backend.evaluation.diagnose pool                   # label recall of the pre-rerank candidate pool by depth
    python -m backend.evaluation.diagnose scores                 # label precision by rerank score; section repeats in top-k

Read-only: it runs the production ``retrieve()`` and prints, for each ranked / in-context chunk, its page,
section, fused / rerank scores and which relevance labels it satisfies. Nothing is written to reports/.
"""
from __future__ import annotations

import argparse
import hashlib
import statistics
import sys
from collections import Counter, defaultdict

from sqlalchemy import select

from backend.db.models import Chunk, Document
from backend.db.session import init_db, session_scope
from backend.evaluation import metrics as M
from backend.evaluation.run import K, load_dataset, retrieval_query
from backend.services.vector_store import knowledge_index


def _short(url: str | None) -> str:
    return (url or "").replace("http://help.synchronik.co.in/", "").replace("https://help.synchronik.co.in/", "") or "-"


def corpus() -> None:
    with session_scope() as db:
        rows = db.execute(select(Document.source_url, Document.title, Chunk.section, Chunk.text)
                          .join(Chunk, Chunk.document_id == Document.id)).all()
    sizes = [len(t) for *_, t in rows]
    print(f"chunks: {len(rows)}  chars: median {statistics.median(sizes):.0f}, "
          f"p10 {sorted(sizes)[len(sizes) // 10]}, p90 {sorted(sizes)[9 * len(sizes) // 10]}, max {max(sizes)}")
    per_page = Counter(_short(u) for u, *_ in rows)
    print("\nchunks per page:")
    for page, n in per_page.most_common():
        print(f"  {n:4d}  {page}")
    norm = Counter(hashlib.md5(" ".join(t.lower().split()).encode()).hexdigest() for *_, t in rows)
    dups = sum(n - 1 for n in norm.values() if n > 1)
    print(f"\nexact-duplicate chunks (after whitespace/case normalisation): {dups}")
    tiny = [(u, s, t) for u, _, s, t in rows if len(t) < 120]
    print(f"chunks under 120 chars: {len(tiny)}")
    for u, s, t in tiny[:15]:
        print(f"   {_short(u)} | {s!r} | {t[:90]!r}")
    no_section = sum(1 for _, _, s, _ in rows if not s)
    print(f"chunks without a section heading: {no_section}")


def show(item: dict) -> dict:
    from backend.services.retrieval import retrieve

    res = retrieve(retrieval_query(item), None, top_n=K)
    labels = item.get("relevant", [])
    print(f"\n[{item['id']}] ({item.get('type')}) {item['question']}")
    print(f"  gate: {'PASS' if res.passed_gate else 'REFUSE ' + res.gate_reason}   labels: {labels}")
    covered: set[int] = set()
    for rank, c in enumerate(res.ranked, start=1):
        m = M.matched_labels(c.url, c.section, c.text, labels)
        covered |= m
        kept = "ctx" if res.passed_gate and c in res.candidates else "   "
        rr = f"{c.rerank:.3f}" if c.rerank is not None else "  -  "
        print(f"  {rank}. {kept} rr={rr} fused={c.fused:.3f} sem={c.semantic:.3f} kw={c.keyword:.2f} "
              f"labels={sorted(m) or '-'}  {_short(c.url)} § {c.section!r}")
        print(f"        {' '.join(c.text.split())[:150]!r}")
    if labels:
        missing = [labels[i] for i in range(len(labels)) if i not in covered]
        print(f"  uncovered labels: {missing or 'none'}")
    return {"res": res, "covered": covered}


def misses(split: str) -> None:
    """Aggregate: which pages/sections fill the context without matching any label."""
    from backend.services.retrieval import retrieve

    by_page = Counter()
    examples = defaultdict(list)
    total = 0
    for it in load_dataset(split):
        if not it["answerable"]:
            continue
        res = retrieve(retrieval_query(it), None, top_n=K)
        if not res.passed_gate:
            continue
        for c in res.candidates:
            total += 1
            if not M.matched_labels(c.url, c.section, c.text, it["relevant"]):
                key = f"{_short(c.url)} § {c.section}"
                by_page[_short(c.url)] += 1
                if len(examples[key]) < 2:
                    examples[key].append(it["question"])
    n_miss = sum(by_page.values())
    print(f"context chunks: {total}, matching no label: {n_miss} ({n_miss / max(total, 1):.1%})\n")
    for page, n in by_page.most_common():
        print(f"  {n:4d}  {page}")
    print("\nmost frequent unlabeled sections:")
    for key, qs in sorted(examples.items(), key=lambda kv: -len(kv[1]))[:25]:
        print(f"  {key}\n      e.g. {qs[0]}")


def pool(split: str) -> None:
    """Label coverage of the fused candidate pool before reranking: can the reranker even see the answer?"""
    from backend.services.retrieval import retrieve

    depths = [5, 12, 24, 40]
    cov = {d: [] for d in depths}
    by_type = defaultdict(lambda: {d: [] for d in depths})
    for it in load_dataset(split):
        if not it["answerable"]:
            continue
        res = retrieve(retrieval_query(it), None, rerank=False, top_n=max(depths))
        ranked = res.ranked
        for d in depths:
            m = [M.matched_labels(c.url, c.section, c.text, it["relevant"]) for c in ranked[:d]]
            r = M.recall_at_k(m, len(it["relevant"]), d)
            cov[d].append(r)
            by_type[it.get("type")][d].append(r)
    print("label recall of the fused (pre-rerank) candidate list at depth d:")
    print("  " + "  ".join(f"d={d:<3}" for d in depths))
    print("  " + "  ".join(f"{statistics.mean(cov[d]):.3f}" for d in depths) + "   all answerable")
    for t, v in sorted(by_type.items()):
        print("  " + "  ".join(f"{statistics.mean(v[d]):.3f}" for d in depths) + f"   {t} (n={len(v[depths[0]])})")


def bucket(v: float, edges: list[float]) -> str:
    for lo, hi in zip(edges, edges[1:]):
        if lo <= v < hi:
            return f"[{lo:.2f}, {hi:.2f})"
    return f">= {edges[-1]:.2f}"


def scores() -> None:
    """Label precision of prompt chunks by rerank score, and how often the top-k repeats a section (dev split)."""
    from backend.services.retrieval import retrieve

    abs_b, rel_b = Counter(), Counter()
    abs_hit, rel_hit = Counter(), Counter()
    dup_queries = dup_slots = answered = 0
    for it in load_dataset("development"):
        if not it["answerable"]:
            continue
        res = retrieve(retrieval_query(it), None, top_n=K)
        sections = Counter((c.document_id, c.section) for c in res.ranked)
        extra = sum(n - 1 for n in sections.values() if n > 1)
        dup_slots += extra
        dup_queries += extra > 0
        if not res.passed_gate:
            continue
        answered += 1
        best = res.candidates[0].rerank or 1e-9
        for c in res.candidates:
            hit = bool(M.matched_labels(c.url, c.section, c.text, it["relevant"]))
            a = bucket(c.rerank, [0.0, 0.05, 0.1, 0.25, 0.5, 0.75])
            r = bucket(c.rerank / best, [0.0, 0.05, 0.1, 0.25, 0.5, 0.75])
            abs_b[a] += 1
            abs_hit[a] += hit
            rel_b[r] += 1
            rel_hit[r] += hit
    print(f"answered dev queries: {answered}")
    print(f"top-{K} slots taken by a repeat of an already-ranked (document, section): {dup_slots} "
          f"across {dup_queries} queries\n")
    for name, b, h in (("absolute rerank score", abs_b, abs_hit), ("score / best score in query", rel_b, rel_hit)):
        print(f"label precision by {name}:")
        for k in sorted(b):
            print(f"  {k:>14}  n={b[k]:4d}  labelled={h[k]:4d}  precision={h[k] / b[k]:.2f}")
        print()



def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["corpus", "query", "misses", "pool", "scores"])
    ap.add_argument("--split", default="development")
    ap.add_argument("--type")
    ap.add_argument("--id", action="append")
    a = ap.parse_args()
    init_db()
    knowledge_index.load_or_build()
    if a.what == "corpus":
        corpus()
    elif a.what == "misses":
        misses(a.split)
    elif a.what == "pool":
        pool(a.split)
    elif a.what == "scores":
        scores()
    else:
        for it in load_dataset(a.split):
            if (a.type and it.get("type") == a.type) or (a.id and it["id"] in a.id):
                show(it)


if __name__ == "__main__":
    main()
