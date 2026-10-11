"""Query understanding: intent detection and conversation-aware rewriting.

Intent detection is deliberately rule-based (fast, free, testable). Whether a
question is *answerable* is decided later by the retrieval relevance gate —
evidence, not keyword lists, decides "out of scope".

Rewriting turns "How do I configure it?" into a standalone query using the
recent conversation, because retrieval has no memory: the embedding of "it"
matches nothing. With an LLM available we ask it for a one-line rewrite;
without one we fall back to anchoring the follow-up on the previous question.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.core.logging import log_event
from backend.services.llm import ChatTurn, get_llm
from backend.services.vector_store import tokenize

GREETING = re.compile(
    r"^\s*(hi+|hello+|hey+|hii+|good\s+(morning|afternoon|evening)|namaste|thanks?|thank\s+you|ok(ay)?|bye)"
    r"[\s!.,]*(there|team|bot|assistant)?[\s!.]*$",
    re.I,
)
SMALLTALK = re.compile(r"^\s*(who|what)\s+are\s+you\??\s*$|^\s*what\s+can\s+you\s+do\??\s*$", re.I)
# Words that only make sense with an antecedent from earlier in the conversation.
FOLLOW_UP = re.compile(
    r"\b(it|its|this|that|these|those|they|them|there|same|above|previous|earlier|the\s+module|the\s+feature|"
    r"more\s+detail|elaborate|explain\s+more|what\s+about|and\s+how|also)\b",
    re.I,
)
DOC_REFERENCE = re.compile(r"\b(uploaded|attached|this|the|my)\s+(document|file|pdf|docx|attachment)\b", re.I)


@dataclass
class QueryAnalysis:
    intent: str  # greeting | document_question | follow_up | ambiguous | attachment_question
    retrieval_query: str
    rewritten: bool = False
    needs_retrieval: bool = True


def classify(message: str, history: list[dict], has_attachments: bool) -> str:
    text = message.strip()
    if GREETING.match(text) or SMALLTALK.match(text):
        return "greeting"
    if has_attachments and DOC_REFERENCE.search(text):
        return "attachment_question"
    words = re.findall(r"\w+", text)
    if history and (FOLLOW_UP.search(text) or len(words) <= 4):
        return "follow_up"
    # Without history, a pronoun-led question with almost no content words ("How do I fix it?",
    # "What about the second one?") has nothing to refer to: ask instead of guessing.
    content = [w for w in tokenize(text) if not FOLLOW_UP.fullmatch(w)]
    if not history and (len(words) <= 1 or (FOLLOW_UP.search(text) and len(content) <= 2)):
        return "ambiguous"
    return "document_question"


REWRITE_SYSTEM = (
    "You rewrite a follow-up question into a standalone search query about the Synchronik ERP product. "
    "Resolve pronouns using the conversation. Output only the rewritten query on one line, no quotes, "
    "no explanation. If the question is already standalone, output it unchanged."
)


def _heuristic_rewrite(message: str, history: list[dict]) -> str:
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    return f"{message} (context: {last_user[:200]})" if last_user else message


def rewrite(message: str, history: list[dict]) -> str:
    convo = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in history[-4:])
    llm = get_llm(required=False)
    if llm is None:
        return _heuristic_rewrite(message, history)
    try:
        out = llm.generate(
            REWRITE_SYSTEM,
            [ChatTurn("user", f"Conversation:\n{convo}\n\nFollow-up question: {message}\n\nStandalone query:")],
            max_tokens=64,
        )
        out = out.strip().strip('"').splitlines()[0] if out.strip() else ""
        return out[:300] or _heuristic_rewrite(message, history)
    except Exception as exc:  # noqa: BLE001 - rewriting is best-effort
        log_event("rewrite_failed", error=type(exc).__name__)
        return _heuristic_rewrite(message, history)


def analyze(message: str, history: list[dict], has_attachments: bool = False) -> QueryAnalysis:
    intent = classify(message, history, has_attachments)
    if intent == "greeting":
        return QueryAnalysis(intent, message, needs_retrieval=False)
    if intent == "ambiguous":
        return QueryAnalysis(intent, message, needs_retrieval=False)
    if intent == "follow_up":
        q = rewrite(message, history)
        return QueryAnalysis(intent, q, rewritten=q != message)
    return QueryAnalysis(intent, message)
