"""Built-in lexical retriever (``lexical_bm25_v1``) for RAG scenarios.

Used only when the target does not perform its own retrieval. It is part of the
target stack under evaluation and is recorded in the run manifest.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

VERSION = "lexical_bm25_v1"
_TOKEN = re.compile(r"\w+", re.UNICODE)
_STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "on", "for", "and", "or", "do", "does", "i", "my", "me",
         "can", "how", "what", "when", "which", "who", "it", "at", "be", "by", "with", "much", "many"}


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.casefold()) if t not in _STOP]


def lexical_retrieve(corpus: list[dict[str, Any]], query: str, k: int, k1: float = 1.2,
                     b: float = 0.75) -> list[dict[str, Any]]:
    docs = [(d["id"], tokens(f"{d.get('title', '')} {d['text']}")) for d in corpus]
    if not docs:
        return []
    n = len(docs)
    avg = sum(len(t) for _, t in docs) / n or 1.0
    df = Counter(term for _, terms in docs for term in set(terms))
    q = tokens(query)
    scored = []
    for order, (doc_id, terms) in enumerate(docs):
        tf = Counter(terms)
        score = 0.0
        for term in q:
            if tf[term]:
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(terms) / avg))
        scored.append((score, -order, doc_id))
    scored.sort(reverse=True)
    return [{"id": doc_id, "score": round(score, 6)} for score, _, doc_id in scored[:k] if score > 0]
