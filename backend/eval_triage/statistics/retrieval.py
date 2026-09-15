"""Retrieval metrics over document ids, with the catalogue's explicit empty-set rules.

* Retrieved ids are de-duplicated preserving first rank, then cut to ``k``.
* Precision@k divides by the unique ids actually retrieved; fixed-slot ``/k``
  precision is a separately named metric.
* No relevant ids: recall, reciprocal rank and nDCG are unavailable (and whether
  the query intentionally has no answer is recorded).
* Relevant ids but nothing retrieved: recall = 0, reciprocal rank = 0, precision
  unavailable.
* IDCG = 0: nDCG unavailable. Relevance grades must be integers 0–3.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import log2

from eval_triage.statistics.core import StatisticsError

DEFINITION_VERSION = "retrieval_v1"


def dedupe_preserving_rank(ids: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _value(value, numerator=None, denominator=None, reason=None) -> dict:
    return {"value": value, "numerator": numerator, "denominator": denominator, "reason": reason}


def retrieval_metrics(relevant: Sequence[str], retrieved: Sequence[str], k: int,
                      relevance: Mapping[str, int] | None = None, intentional_no_answer: bool = False) -> dict:
    if type(k) is not int or k < 1:
        raise StatisticsError("k must be an integer >= 1")
    grades = dict(relevance or {})
    if any(g not in (0, 1, 2, 3) for g in grades.values()):
        raise StatisticsError("relevance grades must be integers 0-3")
    relevant_set = set(relevant) | {doc for doc, g in grades.items() if g > 0}
    top = dedupe_preserving_rank(retrieved)[:k]
    hits = [doc for doc in top if doc in relevant_set]
    no_relevant = "no relevant documents declared" + (
        " (query intentionally has no answer)" if intentional_no_answer else "")

    out: dict[str, dict] = {}
    out["precision_at_k"] = (_value(len(hits) / len(top), len(hits), len(top)) if top
                             else _value(None, reason="no documents retrieved"))
    out["precision_fixed_slots_at_k"] = _value(len(hits) / k, len(hits), k)
    if not relevant_set:
        out["recall_at_k"] = _value(None, reason=no_relevant)
        out["reciprocal_rank"] = _value(None, reason=no_relevant)
        out["ndcg_at_k"] = _value(None, reason=no_relevant)
    else:
        out["recall_at_k"] = _value(len(hits) / len(relevant_set), len(hits), len(relevant_set))
        first = next((rank for rank, doc in enumerate(top, start=1) if doc in relevant_set), None)
        out["reciprocal_rank"] = _value(1 / first if first else 0.0, 1 if first else 0, first)

        def gain(doc: str) -> float:
            grade = grades.get(doc, 1 if doc in relevant_set else 0)
            return float(2 ** grade - 1)

        dcg = sum(gain(doc) / log2(rank + 1) for rank, doc in enumerate(top, start=1))
        ideal = sorted((gain(doc) for doc in relevant_set), reverse=True)[:k]
        idcg = sum(g / log2(rank + 1) for rank, g in enumerate(ideal, start=1))
        out["ndcg_at_k"] = (_value(dcg / idcg, dcg, idcg) if idcg > 0
                            else _value(None, reason="ideal DCG is zero"))
    out["_meta"] = {"k": k, "retrieved_unique": top, "relevant": sorted(relevant_set),
                    "intentional_no_answer": intentional_no_answer, "definition_version": DEFINITION_VERSION}
    return out
