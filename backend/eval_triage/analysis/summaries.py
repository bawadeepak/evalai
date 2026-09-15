"""Run-level analysis. Every number is a ``MetricValue`` that states its definition,
denominator, eligibility, missing count and uncertainty method, and lists the
trials that contributed to it.

Repeats are summarised per case (and candidate) first. Per-case intervals assume
the repeats of that case are plausibly independent; pooling all repeats across
heterogeneous cases into one binomial is deliberately not offered.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select

from eval_triage.db.models import Case, Grade, GradingRun, Review, Run, ScenarioVersion, Trial, TrialOutcome
from eval_triage.domain.enums import SEVERITY_RANK, Severity, TrialStatus
from eval_triage.domain.metrics import Uncertainty
from eval_triage.statistics import core
from eval_triage.statistics.operational import latency_summary
from eval_triage.statistics.registry import metric_value
from eval_triage.statistics.representation import REPRESENTATIONS, category

PROBLEM_STATUSES = {TrialStatus.PROVIDER_ERROR, TrialStatus.TIMEOUT, TrialStatus.UNSUPPORTED,
                    TrialStatus.INDETERMINATE, TrialStatus.SKIPPED, TrialStatus.CANCELLED}
OUTPUT_STATUSES = {TrialStatus.SUCCESS, TrialStatus.INVALID_OUTPUT}
SEMANTIC_PROCEDURE = "semantic:pass_rule_outcome_v1"


@dataclass
class Row:
    trial_id: str
    case_id: str
    external_id: str
    ordinal: int
    severity: str
    cluster_id: str
    tags: dict
    weight: float
    case_hash: str
    purpose: str
    candidate_key: str
    repeat_index: int
    status: str
    outcome: str | None
    outcome_reason: str | None
    latency_ms: float | None
    output: dict | None
    invariant_failures: list = field(default_factory=list)
    grade_errors: int = 0


def _mv(name: str, value, **kw) -> dict[str, Any]:
    return metric_value(name, value, **kw).model_dump(mode="json")


def latest_grading_run(session, run_id: str) -> str | None:
    row = session.scalars(select(GradingRun).where(GradingRun.run_id == run_id)
                          .order_by(GradingRun.created_at.desc())).first()
    return row.id if row else None


def load_rows(session, run_id: str, grading_run_id: str | None = None) -> tuple[Run, str | None, list[Row]]:
    run = session.get(Run, run_id)
    if run is None:
        raise KeyError(run_id)
    grading_run_id = grading_run_id or latest_grading_run(session, run_id)
    outcomes = {o.trial_id: o for o in session.scalars(select(TrialOutcome).where(
        TrialOutcome.grading_run_id == grading_run_id))} if grading_run_id else {}
    errors = dict(session.execute(select(Grade.trial_id, func.count()).where(
        Grade.grading_run_id == grading_run_id, Grade.verdict == "error").group_by(Grade.trial_id)).all()
    ) if grading_run_id else {}
    rows = []
    for trial, case in session.execute(select(Trial, Case).join(Case, Case.id == Trial.case_id)
                                       .where(Trial.run_id == run_id)
                                       .order_by(Case.ordinal, Trial.candidate_key, Trial.repeat_index)).all():
        outcome = outcomes.get(trial.id)
        rows.append(Row(trial.id, case.id, case.external_id, case.ordinal, case.severity, case.cluster_id,
                        case.tags or {}, case.weight, case.case_hash, case.purpose, trial.candidate_key,
                        trial.repeat_index, trial.status, outcome.outcome if outcome else None,
                        outcome.reason if outcome else None, trial.latency_ms, trial.output,
                        outcome.invariant_failures if outcome else [], errors.get(trial.id, 0)))
    return run, grading_run_id, rows


def case_candidate_summary(rows: list[Row], representation: str = "raw", k_values=(1, 3, 5)) -> dict[str, Any]:
    if representation not in REPRESENTATIONS:
        raise ValueError(f"unknown representation {representation!r}")
    n = len(rows)
    ids = [r.trial_id for r in rows]
    passes = sum(r.outcome == "pass" for r in rows)
    fails = sum(r.outcome == "fail" for r in rows)
    graded = passes + fails
    unresolved = n - graded
    metrics: dict[str, Any] = {}
    if graded:
        low, high = core.wilson_interval(passes, graded)
        metrics["pass_rate"] = _mv("observed_pass_rate", passes / graded, numerator=passes, denominator=graded,
                                   eligible=graded, missing=unresolved, trial_ids=ids,
                                   uncertainty=Uncertainty(method="wilson", level=0.95, lower=low, upper=high,
                                                           label="95% Wilson interval (frequentist)"))
        b_low, b_high = core.beta_credible_interval(passes, graded)
        metrics["posterior"] = _mv("beta_posterior", core.beta_posterior_mean(passes, graded), numerator=passes,
                                   denominator=graded, eligible=graded, missing=unresolved, trial_ids=ids,
                                   uncertainty=Uncertainty(method="beta_equal_tailed", level=0.95, lower=b_low,
                                                           upper=b_high, label="95% credible interval, Beta(1,1) "
                                                                               "prior (Bayesian)"),
                                   prior="Beta(1,1)")
        for k in k_values:
            if k <= graded:
                metrics[f"pass_at_{k}"] = _mv("pass_at_k", core.pass_at_k(passes, graded, k), numerator=passes,
                                              denominator=graded, eligible=graded, trial_ids=ids, k=k)
                metrics[f"pass_all_{k}"] = _mv("pass_all_k", core.pass_all_k(passes, graded, k), numerator=passes,
                                               denominator=graded, eligible=graded, trial_ids=ids, k=k)
    else:
        reason = "no binary-graded repeats" if n else "no scheduled repeats"
        metrics["pass_rate"] = _mv("observed_pass_rate", None, reason=reason, eligible=0, missing=unresolved,
                                   trial_ids=ids)
        metrics["posterior"] = _mv("beta_posterior", None, reason=reason, eligible=0, missing=unresolved,
                                   trial_ids=ids)
    categories, ineligible = [], Counter()
    for r in rows:
        if r.output is None:
            ineligible["no output"] += 1
            continue
        cat, reason = category(r.output, representation, r.outcome if representation == "semantic" else None)
        if cat is None:
            ineligible[reason] += 1
        else:
            categories.append(cat)
    provenance = {"representation": representation,
                  "procedure": SEMANTIC_PROCEDURE if representation == "semantic" else representation}
    if len(categories) >= 2:
        rep = core.repeatability(categories)
        metrics["modal_agreement"] = _mv("modal_agreement", rep["modal_agreement"],
                                         numerator=max(rep["category_counts"].values()), denominator=rep["trials"],
                                         eligible=rep["trials"], missing=n - rep["trials"], trial_ids=ids,
                                         **provenance)
        metrics["pairwise_agreement"] = _mv("pairwise_agreement", rep["pairwise_agreement"],
                                            eligible=rep["trials"], missing=n - rep["trials"], trial_ids=ids,
                                            **provenance)
        metrics["entropy"] = _mv("output_entropy", rep["entropy_nats"], eligible=rep["trials"],
                                 missing=n - rep["trials"], trial_ids=ids, **provenance)
        distinct = rep["distinct_outcomes"]
    else:
        reason = "repeatability not measured: fewer than two comparable outputs"
        for key, name in (("modal_agreement", "modal_agreement"), ("pairwise_agreement", "pairwise_agreement"),
                          ("entropy", "output_entropy")):
            metrics[key] = _mv(name, None, reason=reason, eligible=len(categories), missing=n - len(categories),
                               trial_ids=ids, **provenance)
        distinct = len(set(categories))
    latency = latency_summary([r.latency_ms for r in rows if r.latency_ms is not None and r.status in OUTPUT_STATUSES],
                              timeouts=sum(r.status == TrialStatus.TIMEOUT for r in rows))
    metrics["latency_p50"] = _mv("latency_p50", latency["p50_ms"], reason=latency["reason"],
                                 eligible=latency["count"], missing=n - latency["count"], trial_ids=ids,
                                 timeouts=latency["timeouts"])
    statuses = Counter(r.status for r in rows)
    errors = sum(statuses[s] for s in PROBLEM_STATUSES) + sum(r.grade_errors > 0 for r in rows)
    return {
        "counts": {"trials": n, "passes": passes, "fails": fails, "unresolved": unresolved, "errors": errors,
                   "grading_errors": sum(r.grade_errors > 0 for r in rows),
                   "provider_errors": statuses[TrialStatus.PROVIDER_ERROR] + statuses[TrialStatus.TIMEOUT],
                   "invalid_outputs": statuses[TrialStatus.INVALID_OUTPUT], "distinct_outputs": distinct,
                   "ineligible_for_agreement": dict(ineligible)},
        "statuses": dict(statuses),
        "metrics": metrics,
        "flags": {"flaky": passes > 0 and fails > 0, "stable_wrong": graded >= 2 and passes == 0,
                  "all_pass": graded > 0 and fails == 0 and unresolved == 0,
                  "invariant_failures": sorted({i for r in rows for i in r.invariant_failures})},
        "trials": [{"id": r.trial_id, "repeat": r.repeat_index, "status": r.status, "outcome": r.outcome,
                    "grading_error": r.grade_errors > 0} for r in rows],
    }


def _latest_reviews(session, trial_ids: list[str]) -> dict[str, Review]:
    if not trial_ids:
        return {}
    reviews = session.scalars(select(Review).where(Review.trial_id.in_(trial_ids)).order_by(Review.created_at)).all()
    superseded = {r.supersedes_id for r in reviews if r.supersedes_id}
    latest: dict[str, Review] = {}
    for review in reviews:
        if review.id not in superseded:
            latest[review.trial_id] = review
    return latest


def run_summary(session, run_id: str, grading_run_id: str | None = None, representation: str = "raw") -> dict:
    run, grading_run_id, rows = load_rows(session, run_id, grading_run_id)
    scenario = session.get(ScenarioVersion, run.scenario_id)
    candidates = [c["key"] for c in sorted(run.manifest["candidates"], key=lambda c: c["ordinal"])]
    baseline = candidates[0]
    by_candidate: dict[str, list[Row]] = defaultdict(list)
    by_case: dict[str, dict[str, list[Row]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_candidate[r.candidate_key].append(r)
        by_case[r.case_id][r.candidate_key].append(r)
    reviews = _latest_reviews(session, [r.trial_id for r in rows])

    slot = {}
    for key in candidates:
        rs = by_candidate[key]
        ids = [r.trial_id for r in rs]
        S = len(rs)
        G = sum(r.status in OUTPUT_STATUSES for r in rs)
        P = sum(r.outcome == "pass" for r in rs)
        F = sum(r.outcome == "fail" for r in rs)
        E = P + F
        slot[key] = {
            "scheduled": S, "generated": G, "graded": E, "passed": P, "failed": F, "unresolved": S - E,
            "target_completion": _mv("target_completion", G / S if S else None, reason="no scheduled slots",
                                     numerator=G, denominator=S, eligible=S, missing=S - G, trial_ids=ids),
            "grade_coverage": _mv("grade_coverage", E / G if G else None, reason="no slots with output",
                                  numerator=E, denominator=G, eligible=G, missing=G - E, trial_ids=ids),
            "conditional_pass": _mv("conditional_pass", P / E if E else None, reason="no binary grades",
                                    numerator=P, denominator=E, eligible=E, missing=S - E, trial_ids=ids),
            "observed_success_yield": _mv("observed_success_yield", P / S if S else None,
                                          reason="no scheduled slots", numerator=P, denominator=S, eligible=S,
                                          missing=S - E, trial_ids=ids),
            "latency": latency_summary([r.latency_ms for r in rs if r.latency_ms is not None
                                        and r.status in OUTPUT_STATUSES],
                                       timeouts=sum(r.status == TrialStatus.TIMEOUT for r in rs)),
            "invariant_failures": dict(Counter(i for r in rs for i in r.invariant_failures)),
        }

    cases = []
    for case_id, per in sorted(by_case.items(), key=lambda kv: next(iter(kv[1].values()))[0].ordinal):
        first = next(iter(per.values()))[0]
        summaries = {key: case_candidate_summary(per.get(key, []), representation) for key in candidates}
        base_rate = summaries[baseline]["metrics"]["pass_rate"]["value"]
        deltas = {}
        for key in candidates[1:]:
            rate = summaries[key]["metrics"]["pass_rate"]["value"]
            deltas[key] = None if rate is None or base_rate is None else rate - base_rate
        trial_ids = [r.trial_id for rs in per.values() for r in rs]
        case_reviews = [reviews[t] for t in trial_ids if t in reviews]
        cases.append({
            "case_id": case_id, "external_id": first.external_id, "severity": first.severity,
            "cluster_id": first.cluster_id, "tags": first.tags, "purpose": first.purpose,
            "case_hash": first.case_hash, "candidates": summaries, "delta_vs_baseline": deltas,
            "changed": any(d is not None and abs(d) >= 0.5 for d in deltas.values()) or any(
                summaries[k]["flags"]["stable_wrong"] != summaries[baseline]["flags"]["stable_wrong"]
                for k in candidates[1:]),
            "review": ({"state": "reviewed", "decisions": dict(Counter(r.decision for r in case_reviews)),
                        "latest": max(case_reviews, key=lambda r: r.created_at).decision}
                       if case_reviews else {"state": "unreviewed", "decisions": {}, "latest": None}),
        })

    slices = []
    for key in scenario.slice_keys:
        values = defaultdict(lambda: defaultdict(list))
        for r in rows:
            if key in r.tags:
                values[str(r.tags[key])][r.candidate_key].append(r)
        for value, per in sorted(values.items()):
            entry = {"key": key, "value": value, "candidates": {}}
            for cand in candidates:
                rs = per.get(cand, [])
                P = sum(r.outcome == "pass" for r in rs)
                E = sum(r.outcome in ("pass", "fail") for r in rs)
                entry["candidates"][cand] = _mv(
                    "observed_pass_rate", P / E if E else None, reason="no binary grades in this slice",
                    numerator=P, denominator=E, eligible=E, missing=len(rs) - E, trial_ids=[r.trial_id for r in rs],
                    case_ids=sorted({r.case_id for r in rs}), slice=f"{key}={value}")
            slices.append(entry)

    return {
        "run_id": run.id, "grading_run_id": grading_run_id, "representation": representation,
        "is_demo": run.is_demo, "status": run.status, "candidates": candidates, "baseline": baseline,
        "slot_rates": slot, "cases": cases, "slices": slices,
        "notes": ["Overlapping slices are independently filtered views; they are not disjoint populations.",
                  "Per-case intervals assume independent repeats of that case; they are not dataset-level "
                  "intervals."],
    }


def _priority(item: dict[str, Any]) -> tuple:
    return (item["priority"], SEVERITY_RANK.get(Severity(item["severity"]), 9), item["external_id"],
            item["candidate_key"])


PRIORITY_LABELS = {0: "critical failure", 1: "regression vs baseline", 2: "uncertain label", 3: "flaky",
                   4: "other failure"}


def triage_queue(session, run_id: str, grading_run_id: str | None = None, filters: dict | None = None,
                 representation: str = "raw") -> dict[str, Any]:
    summary = run_summary(session, run_id, grading_run_id, representation)
    filters = filters or {}
    baseline = summary["baseline"]
    items = []
    for case in summary["cases"]:
        base = case["candidates"][baseline]
        for key, cs in case["candidates"].items():
            counts, flags = cs["counts"], cs["flags"]
            failing = counts["fails"] > 0 or counts["errors"] > 0 or counts["unresolved"] > 0
            if not failing:
                continue
            rate = cs["metrics"]["pass_rate"]["value"]
            base_rate = base["metrics"]["pass_rate"]["value"]
            regression = key != baseline and rate is not None and base_rate is not None and rate < base_rate
            uncertain = counts["grading_errors"] > 0 or case["review"]["latest"] in ("ambiguous", "grader_incorrect")
            if (case["severity"] == "critical" and counts["fails"] > 0) or flags["invariant_failures"]:
                priority = 0
            elif regression:
                priority = 1
            elif uncertain or (counts["unresolved"] > 0 and counts["fails"] == 0):
                priority = 2
            elif flags["flaky"]:
                priority = 3
            else:
                priority = 4
            representative = next((t for t in cs["trials"] if t["outcome"] == "fail"),
                                  next((t for t in cs["trials"] if t["outcome"] != "pass"), cs["trials"][0]))
            items.append({
                "case_id": case["case_id"], "external_id": case["external_id"], "purpose": case["purpose"],
                "severity": case["severity"], "tags": case["tags"], "candidate_key": key,
                "counts": counts, "flags": {**flags, "changed": case["changed"] and key != baseline,
                                            "regression": regression, "grading_error": counts["grading_errors"] > 0,
                                            "provider_error": counts["provider_errors"] > 0},
                "pass_rate": cs["metrics"]["pass_rate"], "agreement": cs["metrics"]["pairwise_agreement"],
                "review": case["review"], "priority": priority, "priority_label": PRIORITY_LABELS[priority],
                "representative_trial_id": representative["id"], "trials": cs["trials"],
            })
    def keep(item: dict[str, Any]) -> bool:
        f = item["flags"]
        checks = {
            "severity": lambda v: item["severity"] == v,
            "candidate": lambda v: item["candidate_key"] == v,
            "flaky": lambda v: f["flaky"] == v,
            "stable_wrong": lambda v: f["stable_wrong"] == v,
            "changed": lambda v: f["changed"] == v,
            "grading_error": lambda v: f["grading_error"] == v,
            "provider_error": lambda v: f["provider_error"] == v,
            "review": lambda v: (item["review"]["state"] == "unreviewed") if v == "unreviewed"
            else item["review"]["latest"] == "confirm_failure" if v == "confirmed" else True,
            "slice": lambda v: str(item["tags"].get(v.split("=", 1)[0])) == v.split("=", 1)[1] if "=" in v else True,
        }
        return all(checks[k](v) for k, v in filters.items() if k in checks and v not in (None, ""))

    items = sorted((i for i in items if keep(i)), key=_priority)
    return {"run_id": run_id, "grading_run_id": summary["grading_run_id"], "items": items,
            "sort": "priority (critical failures, regressions, uncertain labels, flaky, other), then severity, "
                    "then case id",
            "is_demo": summary["is_demo"], "baseline": baseline, "candidates": summary["candidates"]}
