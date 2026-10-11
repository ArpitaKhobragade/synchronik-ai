"""Retrieval and generation metrics for the RAG evaluation.

Relevance labels are (url_fragment, phrase) pairs: a retrieved chunk is
relevant when its document URL contains ``url_fragment`` and the phrase appears
in the chunk's section heading or text. Labels were written against the crawled
help portal and are checked by ``run.py --check-labels``.
"""
from __future__ import annotations

import math
import re

from backend.services.vector_store import tokenize


def matched_labels(url: str | None, section: str | None, text: str, labels: list[list[str]]) -> set[int]:
    """Indices of the relevance labels this chunk satisfies."""
    url = url or ""
    hay = f"{section or ''} {text}".lower()
    return {i for i, (frag, phrase) in enumerate(labels) if frag in url and phrase.lower() in hay}


def recall_at_k(matches: list[set[int]], total_labels: int, k: int) -> float:
    """Share of labelled answer locations covered by at least one top-k chunk."""
    if not total_labels:
        return 0.0
    covered = set().union(*matches[:k]) if matches[:k] else set()
    return len(covered) / total_labels


def hit_at_k(rels: list[bool], k: int) -> float:
    return 1.0 if any(rels[:k]) else 0.0


def precision_at_k(rels: list[bool], k: int) -> float:
    top = rels[:k]
    return sum(top) / k if top else 0.0


def mrr(rels: list[bool]) -> float:
    for i, r in enumerate(rels, start=1):
        if r:
            return 1.0 / i
    return 0.0


def ndcg_at_k(rels: list[bool], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, r in enumerate(rels[:k]) if r)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, sum(rels) or 0)))
    return dcg / ideal if ideal else 0.0


# --- generation ----------------------------------------------------------------

CITE = re.compile(r"\[\d{1,2}\]")


def answer_sentences(answer: str) -> list[str]:
    """Content-bearing sentences of an answer (>= 3 content words), citation markers removed."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", CITE.sub("", answer)) if len(tokenize(s)) >= 3]


def faithfulness(answer: str, contexts: list[str], threshold: float = 0.5) -> float:
    """Share of answer sentences whose content words are mostly (>= threshold) present in the retrieved context.

    A lexical proxy for groundedness: deterministic and reproducible, but blind to paraphrase
    (under-counts) and to wrong combinations of correct words (over-counts).
    """
    ctx = set(tokenize(" ".join(contexts)))
    sents = answer_sentences(answer)
    if not sents:
        return 0.0
    ok = sum(1 for s in sents if len(set(tokenize(s)) & ctx) / len(set(tokenize(s))) >= threshold)
    return ok / len(sents)


def keyword_correctness(answer: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    a = answer.lower()
    return sum(1 for k in keywords if k.lower() in a) / len(keywords)


def citation_precision(cited_relevant: list[bool]) -> float:
    return sum(cited_relevant) / len(cited_relevant) if cited_relevant else 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(round(p * (len(v) - 1))))]
