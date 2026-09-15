"""Operational definitions: slot rates, latency and cost [application definitions].

Let S be scheduled slots, G successful transport/output slots, E binary-graded
slots, P passing slots and F failing slots.

* ``target_completion = G / S``
* ``grade_coverage = E / eligible`` (slots eligible for that grader)
* ``conditional_pass = P / (P + F)``
* ``observed_success_yield = P / S`` — unresolved slots are not claimed wrong.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from eval_triage.statistics.core import linear_quantile


def _rate(numerator: int, denominator: int, reason: str) -> dict:
    return {"value": numerator / denominator if denominator else None, "numerator": numerator,
            "denominator": denominator, "reason": None if denominator else reason}


def slot_rates(scheduled: int, generated: int, graded: int, eligible: int, passed: int, failed: int) -> dict:
    return {
        "target_completion": _rate(generated, scheduled, "no scheduled slots"),
        "grade_coverage": _rate(graded, eligible, "no slots eligible for grading"),
        "conditional_pass": _rate(passed, passed + failed, "no binary grades"),
        "observed_success_yield": _rate(passed, scheduled, "no scheduled slots"),
        "unresolved": scheduled - passed - failed,
    }


def latency_summary(latencies_ms: Sequence[float], timeouts: int = 0) -> dict:
    """p50/p95 over completed calls by linear interpolation (type 7); timeouts reported separately."""
    values = [v for v in latencies_ms if v is not None]
    return {
        "count": len(values),
        "timeouts": timeouts,
        "p50_ms": linear_quantile(values, 0.5),
        "p95_ms": linear_quantile(values, 0.95),
        "method": "linear_type7_over_completed_calls",
        "reason": None if values else "no completed calls",
    }


def cost_summary(items: Iterable[dict]) -> dict:
    """``items``: dicts with ``amount`` (None when unknown), ``currency`` and ``kind``
    (``target``, ``retry`` or ``judge``). Missing prices are not free."""
    totals: dict[str, float] = defaultdict(float)
    by_kind: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    known = unknown = 0
    for item in items:
        amount, currency, kind = item.get("amount"), item.get("currency"), item.get("kind", "target")
        if amount is None or currency is None:
            unknown += 1
            continue
        known += 1
        totals[currency] += amount
        by_kind[kind][currency] += amount
    total = known + unknown
    return {
        "by_currency": dict(totals),
        "by_kind": {k: dict(v) for k, v in by_kind.items()},
        "known_items": known,
        "unknown_items": unknown,
        "coverage": known / total if total else None,
        "complete": total > 0 and unknown == 0,
        "display": "unknown" if unknown and not known else None,
    }


def cost_per_confirmed_success(summary: dict, passed: int) -> dict:
    if not summary["complete"]:
        return {"value": None, "reason": "cost accounting is incomplete (some prices or usage unknown)"}
    if len(summary["by_currency"]) != 1:
        return {"value": None, "reason": "costs span several currencies"}
    if passed == 0:
        return {"value": None, "reason": "no passing slots"}
    currency, amount = next(iter(summary["by_currency"].items()))
    return {"value": amount / passed, "currency": currency, "numerator": amount, "denominator": passed,
            "reason": None}
