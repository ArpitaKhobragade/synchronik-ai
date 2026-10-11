"""Evidence-based confidence.

The LLM is never asked "how confident are you?" (models are poorly calibrated
about that). Confidence is computed from retrieval evidence only:

  score = 0.60 * top_relevance          best chunk's rerank probability (or fused score)
        + 0.25 * min(support / 3, 1)    how many chunks independently cleared the bar
        + 0.15 * source_agreement       share of the top-3 that are close to the best one

Each signal is returned so the UI can explain the number.
"""
from __future__ import annotations

from backend.services.retrieval import RetrievalResult

LEVELS = [
    (0.70, "high", "High confidence", "Good documentation match"),
    (0.45, "medium", "Moderate confidence", "Partial documentation match — verify key details"),
    (0.0, "low", "Limited confidence", "Documentation coverage is weak"),
]


def compute_confidence(res: RetrievalResult | None, grounded: bool) -> dict:
    if res is None or not grounded or not res.candidates:
        return {
            "score": 0.0, "level": "none", "label": "No documentation match",
            "explanation": "No sufficiently relevant Synchronik documentation was found.",
            "signals": {"top_score": round(res.candidates[0].relevance, 3) if res and res.candidates else 0.0,
                        "support_chunks": 0, "score_margin": 0.0, "source_agreement": 0.0},
        }
    rel = [c.relevance for c in res.candidates]
    top = rel[0]
    support = len(rel)
    top3 = rel[:3]
    agreement = sum(1 for r in top3 if r >= 0.5 * top) / len(top3) if top > 0 else 0.0
    margin = top - rel[1] if len(rel) > 1 else top
    score = 0.60 * top + 0.25 * min(support / 3, 1.0) + 0.15 * agreement
    score = max(0.0, min(1.0, score))
    for threshold, level, label, explanation in LEVELS:
        if score >= threshold:
            break
    return {
        "score": round(score, 3), "level": level, "label": label, "explanation": explanation,
        "signals": {"top_score": round(top, 3), "support_chunks": support,
                    "score_margin": round(margin, 3), "source_agreement": round(agreement, 3)},
    }
