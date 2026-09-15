"""Paired cluster bootstrap and evidence-based release gates.

Repeats are summarised per case first (by the caller); paired case differences
are grouped by ``cluster`` (conversation/person) so correlated cases count as one
independent unit. Complete clusters are resampled with replacement, keeping each
candidate/baseline pair together. A percentile interval is a statement about the
resampling procedure — never "the probability the candidate is better".
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from eval_triage.statistics.core import StatisticsError

METHOD = "paired_cluster_percentile_bootstrap"
MIN_CLUSTERS_FOR_GATE = 20


def paired_cluster_bootstrap(units: Sequence[Mapping[str, Any]], *, resamples: int = 10_000, seed: int = 42,
                             confidence: float = 0.95, estimand: str = "equal_weight_clusters",
                             min_clusters_warning: int = MIN_CLUSTERS_FOR_GATE) -> dict:
    """``units``: one dict per paired case with ``cluster``, ``baseline``, ``candidate`` and optional
    ``weight``. ``estimand`` is ``equal_weight_clusters`` (default) or ``case_weighted``."""
    if estimand not in ("equal_weight_clusters", "case_weighted"):
        raise StatisticsError(f"unknown estimand {estimand!r}")
    if type(resamples) is not int or resamples < 100:
        raise StatisticsError("resamples must be an integer >= 100")
    if not 0 < confidence < 1:
        raise StatisticsError("confidence must be strictly between 0 and 1")
    clusters: dict[str, list[tuple[float, float]]] = defaultdict(list)
    base_values, cand_values = [], []
    for unit in units:
        b, c = float(unit["baseline"]), float(unit["candidate"])
        w = float(unit.get("weight", 1.0))
        if not (np.isfinite(b) and np.isfinite(c) and np.isfinite(w)) or w <= 0:
            raise StatisticsError("paired values and weights must be finite (weights positive)")
        clusters[str(unit["cluster"])].append((c - b, w))
        base_values.append(b)
        cand_values.append(c)
    names = sorted(clusters)
    m = len(names)
    result: dict[str, Any] = {
        "method": METHOD, "estimand": estimand, "resamples": resamples, "seed": seed, "confidence": confidence,
        "clusters": m, "cases": len(base_values), "delta": None, "lower": None, "upper": None,
        "degenerate": False, "warnings": [], "reason": None,
        "baseline_mean": float(np.mean(base_values)) if base_values else None,
        "candidate_mean": float(np.mean(cand_values)) if cand_values else None,
    }
    if m == 0:
        result["reason"] = "no paired cases"
        return result
    if estimand == "equal_weight_clusters":
        numerators = np.array([np.mean([d for d, _ in clusters[n]]) for n in names])
        denominators = np.ones(m)
    else:
        numerators = np.array([sum(d * w for d, w in clusters[n]) for n in names])
        denominators = np.array([sum(w for _, w in clusters[n]) for n in names])
    result["delta"] = float(numerators.sum() / denominators.sum())
    if m < 2:
        result["reason"] = "at least two independent clusters are needed for an interval"
        result["warnings"].append(result["reason"])
        return result
    rng = np.random.default_rng(seed)
    index = rng.integers(0, m, size=(resamples, m))
    draws = numerators[index].sum(axis=1) / denominators[index].sum(axis=1)
    alpha = (1 - confidence) / 2
    result["lower"] = float(np.quantile(draws, alpha, method="linear"))
    result["upper"] = float(np.quantile(draws, 1 - alpha, method="linear"))
    result["degenerate"] = bool(draws.max() - draws.min() < 1e-12)
    if result["degenerate"]:
        result["warnings"].append("degenerate bootstrap distribution: every resample gave the same delta")
    if m < min_clusters_warning:
        result["warnings"].append(f"only {m} independent clusters (fewer than {min_clusters_warning}); "
                                  "interval is descriptive and cannot drive an automatic gate")
    return result


@dataclass
class GateMetric:
    name: str
    direction: str = "higher_is_better"
    margin: float = 0.0
    required: bool = True


@dataclass
class ReleasePolicyConfig:
    metrics: list[GateMetric] = field(default_factory=list)
    critical_invariants: list[str] = field(default_factory=list)
    min_paired_coverage: float = 1.0
    min_independent_clusters: int = MIN_CLUSTERS_FOR_GATE
    confidence: float = 0.95
    resamples: int = 10_000
    seed: int = 42

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReleasePolicyConfig:
        metrics = [GateMetric(**m) for m in data.get("metrics", [])]
        for metric in metrics:
            if metric.direction not in ("higher_is_better", "lower_is_better"):
                raise StatisticsError(f"{metric.name}: direction must be higher_is_better or lower_is_better")
            if metric.margin < 0:
                raise StatisticsError(f"{metric.name}: margin must be non-negative")
        return cls(metrics=metrics,
                   critical_invariants=list(data.get("critical_invariants", [])),
                   min_paired_coverage=float(data.get("min_paired_coverage", 1.0)),
                   min_independent_clusters=int(data.get("min_independent_clusters", MIN_CLUSTERS_FOR_GATE)),
                   confidence=float(data.get("confidence", 0.95)),
                   resamples=int(data.get("resamples", 10_000)),
                   seed=int(data.get("seed", 42)))


def evaluate_gate(policy: ReleasePolicyConfig, metric_results: Mapping[str, Mapping[str, Any]],
                  invariant_failures: Mapping[str, int] | None = None, *, paired_coverage: float | None = None,
                  run_problems: Sequence[str] = ()) -> dict:
    """Return ``ready`` / ``blocked`` / ``inconclusive`` with the exact reason for each check.

    * Required critical-invariant failures block regardless of average improvement.
    * A metric clears when its sign-adjusted lower bound is at least ``-margin``
      (non-inferiority); it blocks when the whole interval lies beyond the margin
      (a demonstrated regression); otherwise, or with insufficient data, it is inconclusive.
    * Partial, cancelled or incompatible experiments can never be ``ready``.
    """
    checks: list[dict] = []
    failures = dict(invariant_failures or {})
    for name in policy.critical_invariants:
        count = failures.get(name, 0)
        checks.append({"check": f"invariant:{name}", "status": "blocked" if count else "clear",
                       "reason": f"{count} critical invariant failure(s)" if count else "no observed violation"})
    for problem in run_problems:
        checks.append({"check": "experiment", "status": "inconclusive", "reason": problem})
    if paired_coverage is not None and paired_coverage < policy.min_paired_coverage:
        checks.append({"check": "paired_coverage", "status": "inconclusive",
                       "reason": f"paired coverage {paired_coverage:.1%} is below the required "
                                 f"{policy.min_paired_coverage:.0%}"})
    for metric in policy.metrics:
        result = metric_results.get(metric.name)
        entry = {"check": f"metric:{metric.name}", "direction": metric.direction, "margin": metric.margin,
                 "required": metric.required}
        if result is None or result.get("lower") is None or result.get("upper") is None:
            why = (result or {}).get("reason") or "no paired cases with binary grades"
            entry.update(status="inconclusive", reason=f"no interval available ({why}; "
                                                       f"{(result or {}).get('clusters', 0)} independent clusters)")
        elif result.get("clusters", 0) < policy.min_independent_clusters:
            entry.update(status="inconclusive", reason=f"{result.get('clusters', 0)} independent clusters; "
                                                       f"{policy.min_independent_clusters} required")
        else:
            sign = 1.0 if metric.direction == "higher_is_better" else -1.0
            low, high = sorted((sign * result["lower"], sign * result["upper"]))
            entry.update(adjusted_lower=low, adjusted_upper=high, delta=result.get("delta"))
            if low >= -metric.margin:
                entry.update(status="clear", reason=f"lower bound {low:+.4f} >= -{metric.margin} (non-inferior)")
            elif high < -metric.margin:
                entry.update(status="blocked", reason=f"upper bound {high:+.4f} < -{metric.margin} "
                                                      "(demonstrated regression)")
            else:
                entry.update(status="inconclusive", reason=f"interval [{low:+.4f}, {high:+.4f}] crosses "
                                                           f"-{metric.margin}")
        if not metric.required and entry["status"] != "clear":
            entry["status"] = "advisory"
        checks.append(entry)
    statuses = {c["status"] for c in checks}
    if "blocked" in statuses:
        verdict = "blocked"
    elif "inconclusive" in statuses or not policy.metrics:
        verdict = "inconclusive"
    else:
        verdict = "ready"
    reasons = [f"{c['check']}: {c['reason']}" for c in checks if c["status"] in ("blocked", "inconclusive")]
    if not policy.metrics:
        reasons.append("policy declares no gate metrics")
    required = sum(1 for m in policy.metrics if m.required)
    return {
        "verdict": verdict,
        "reasons": reasons,
        "checks": checks,
        "multiplicity_note": (f"{required} required gates are evaluated together; the chance that at least one "
                              "gate misfires is higher than for a single test.") if required > 1 else None,
        "note": "Evidence gate only; this is not a deployment action.",
    }
