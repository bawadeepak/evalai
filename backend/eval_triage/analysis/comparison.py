"""Paired comparison of a baseline and a candidate, and the release decision.

Compatibility is checked first: grader versions, pass rule and repeat design
must match, and cases are paired on ``(external_id, case_hash)`` so a later
dataset version pairs its unchanged cases and lists added or changed cases as
exclusions. Incompatible experiments are shown descriptively only; the
inferential delta and gate are disabled. Repeats are summarised per case, cases
are grouped by cluster, and complete clusters are bootstrapped.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from eval_triage.analysis.summaries import case_candidate_summary, load_rows
from eval_triage.db.models import Comparison, DatasetVersion, GradingRun, ReleasePolicy, Run
from eval_triage.domain.enums import RunStatus
from eval_triage.statistics.bootstrap import ReleasePolicyConfig, evaluate_gate, paired_cluster_bootstrap

DEFAULT_POLICY = {"metrics": [{"name": "case_pass_rate", "direction": "higher_is_better", "margin": 0.05,
                               "required": True}],
                  "critical_invariants": [], "min_paired_coverage": 1.0, "min_independent_clusters": 20,
                  "confidence": 0.95, "resamples": 10000, "seed": 42}


def _side(session, run_id: str, key: str, grading_run_id: str | None):
    run, grading_run_id, rows = load_rows(session, run_id, grading_run_id)
    rows = [r for r in rows if r.candidate_key == key]
    grading = session.get(GradingRun, grading_run_id) if grading_run_id else None
    return run, grading, rows


def _case_index(rows) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = cases.setdefault(r.external_id, {"case_hash": r.case_hash, "cluster": r.cluster_id,
                                                 "severity": r.severity, "tags": r.tags, "rows": []})
        entry["rows"].append(r)
    return cases


def evaluate(session, *, baseline_run_id: str, baseline_key: str, candidate_run_id: str, candidate_key: str,
             baseline_grading_run_id: str | None = None, candidate_grading_run_id: str | None = None,
             policy: dict | None = None) -> dict[str, Any]:
    base_run, base_grading, base_rows = _side(session, baseline_run_id, baseline_key, baseline_grading_run_id)
    cand_run, cand_grading, cand_rows = _side(session, candidate_run_id, candidate_key, candidate_grading_run_id)
    if not base_rows:
        raise ValueError(f"baseline run has no candidate {baseline_key!r}")
    if not cand_rows:
        raise ValueError(f"candidate run has no candidate {candidate_key!r}")
    findings, problems = [], []

    def finding(check: str, ok: bool, message: str, blocks_inference: bool = True) -> None:
        findings.append({"check": check, "ok": ok, "message": message, "blocks_inference": blocks_inference and not ok})

    finding("grader_versions", bool(base_grading and cand_grading and
                                    sorted(base_grading.grader_hashes) == sorted(cand_grading.grader_hashes)),
            "grader versions match" if base_grading and cand_grading and sorted(base_grading.grader_hashes) ==
            sorted(cand_grading.grader_hashes) else "grader versions differ; regrade both runs with one grader version")
    base_rule = session.get(DatasetVersion, base_run.dataset_id).pass_rule
    cand_rule = session.get(DatasetVersion, cand_run.dataset_id).pass_rule
    finding("pass_rule", base_rule == cand_rule, "outcome definitions (pass rule) match" if base_rule == cand_rule
            else "pass rules differ, so outcomes are not comparable")
    design = lambda run: (run.manifest["execution"]["repeats"], run.manifest["execution"]["repeat_mode"])  # noqa: E731
    finding("repeat_design", design(base_run) == design(cand_run),
            f"repeat design {design(base_run)} vs {design(cand_run)}")
    finding("scenario", base_run.scenario_id == cand_run.scenario_id or
            base_run.manifest["scenario"]["hash"] == cand_run.manifest["scenario"]["hash"],
            "same scenario contract" if base_run.manifest["scenario"]["hash"] == cand_run.manifest["scenario"]["hash"]
            else "scenario versions differ")
    for label, run in (("baseline", base_run), ("candidate", cand_run)):
        if run.status in (RunStatus.CANCELLED, RunStatus.CANCELLING, RunStatus.FAILED, RunStatus.QUEUED,
                          RunStatus.RUNNING):
            problems.append(f"{label} run is {run.status}; partial or incomplete runs cannot be release-ready")
    if base_run.is_demo or cand_run.is_demo:
        findings.append({"check": "demo", "ok": True, "blocks_inference": False,
                         "message": "demo data: results are synthetic fixtures, not measurements"})

    base_cases, cand_cases = _case_index(base_rows), _case_index(cand_rows)
    exclusions, pairs = [], []
    for ext in sorted(set(base_cases) | set(cand_cases)):
        b, c = base_cases.get(ext), cand_cases.get(ext)
        if b is None:
            exclusions.append({"external_id": ext, "reason": "added_in_candidate"})
        elif c is None:
            exclusions.append({"external_id": ext, "reason": "missing_in_candidate"})
        elif b["case_hash"] != c["case_hash"]:
            exclusions.append({"external_id": ext, "reason": "case_changed"})
        else:
            pairs.append((ext, b, c))
    union = len(set(base_cases) | set(cand_cases))
    coverage = len(pairs) / union if union else 0.0
    compatible = not any(f["blocks_inference"] for f in findings)

    units, case_changes = [], {"improved": [], "regressed": [], "unchanged": [], "unresolved": []}
    critical = []
    for ext, b, c in pairs:
        bs, cs = case_candidate_summary(b["rows"]), case_candidate_summary(c["rows"])
        br, cr = bs["metrics"]["pass_rate"]["value"], cs["metrics"]["pass_rate"]["value"]
        entry = {"external_id": ext, "baseline": br, "candidate": cr, "cluster": b["cluster"],
                 "severity": b["severity"], "baseline_trials": [t["id"] for t in bs["trials"]],
                 "candidate_trials": [t["id"] for t in cs["trials"]]}
        if br is None or cr is None:
            case_changes["unresolved"].append(entry)
            continue
        units.append({"cluster": b["cluster"], "baseline": br, "candidate": cr})
        bucket = "improved" if cr > br else "regressed" if cr < br else "unchanged"
        case_changes[bucket].append({**entry, "delta": cr - br})
        if b["severity"] == "critical":
            critical.append({**entry, "delta": cr - br})
    policy = policy or DEFAULT_POLICY
    config = ReleasePolicyConfig.from_dict(policy)
    boot = paired_cluster_bootstrap(units, resamples=config.resamples, seed=config.seed,
                                    confidence=config.confidence,
                                    min_clusters_warning=config.min_independent_clusters) if units else {
        "delta": None, "lower": None, "upper": None, "clusters": 0, "cases": 0, "warnings": ["no paired cases"],
        "reason": "no paired cases with binary grades", "degenerate": False}
    invariant_failures = defaultdict(int)
    for r in cand_rows:
        for name in r.invariant_failures:
            invariant_failures[name] += 1
    if not compatible:
        problems.append("experiments are incompatible; only descriptive comparison is shown")
    gate = evaluate_gate(config, {"case_pass_rate": boot} if compatible else {}, dict(invariant_failures),
                         paired_coverage=coverage, run_problems=problems)

    def side_rate(rows):
        passes = sum(r.outcome == "pass" for r in rows)
        graded = sum(r.outcome in ("pass", "fail") for r in rows)
        return {"passes": passes, "graded": graded, "rate": passes / graded if graded else None}

    metrics = [{
        "name": "case_pass_rate", "definition": "mean over paired cases of per-case pass fraction",
        "unit": "fraction", "direction": "higher_is_better",
        "baseline": boot.get("baseline_mean"), "candidate": boot.get("candidate_mean"),
        "delta": boot["delta"] if compatible else None, "lower": boot["lower"] if compatible else None,
        "upper": boot["upper"] if compatible else None, "independent_clusters": boot["clusters"],
        "paired_cases": boot.get("cases", len(units)), "method": boot.get("method"),
        "resamples": boot.get("resamples"), "seed": boot.get("seed"), "confidence": config.confidence,
        "margin": next((m.margin for m in config.metrics if m.name == "case_pass_rate"), None),
        "warnings": boot.get("warnings", []), "degenerate": boot.get("degenerate", False),
        "gate": next((c["status"] for c in gate["checks"] if c["check"] == "metric:case_pass_rate"), None),
        "inferential": compatible,
        "note": "The interval describes the resampling procedure; it is not the probability that the "
                "candidate is better.",
    }, {
        "name": "observed_pass_rate", "definition": "passes / binary-graded slots (descriptive, all repeats)",
        "unit": "fraction", "direction": "higher_is_better", "baseline": side_rate(base_rows),
        "candidate": side_rate(cand_rows), "inferential": False, "gate": "descriptive",
    }]
    return {
        "compatibility": {"compatible": compatible, "findings": findings, "paired_coverage": coverage,
                          "paired_cases": len(pairs), "union_cases": union},
        "pairing": {"method": "external_id + case_hash", "pairs": [p[0] for p in pairs]},
        "exclusions": exclusions,
        "method": {"bootstrap": boot.get("method"), "estimand": "equal_weight_clusters",
                   "resamples": config.resamples, "seed": config.seed, "confidence": config.confidence},
        "metrics": metrics,
        "case_changes": {**case_changes, "critical": critical},
        "invariant_failures": dict(invariant_failures),
        "decision": gate,
        "grading_run_ids": [base_grading.id if base_grading else None, cand_grading.id if cand_grading else None],
        "demo": base_run.is_demo or cand_run.is_demo,
    }


def create_comparison(session, project_id: str, *, baseline_run_id: str, baseline_key: str, candidate_run_id: str,
                      candidate_key: str, baseline_grading_run_id: str | None = None,
                      candidate_grading_run_id: str | None = None, policy_id: str | None = None) -> Comparison:
    for run_id in (baseline_run_id, candidate_run_id):
        run = session.get(Run, run_id)
        if run is None or run.project_id != project_id:
            raise KeyError(run_id)
    policy = None
    if policy_id:
        row = session.get(ReleasePolicy, policy_id)
        if row is None or row.project_id != project_id:
            raise KeyError(policy_id)
        policy = row.policy
    result = evaluate(session, baseline_run_id=baseline_run_id, baseline_key=baseline_key,
                      candidate_run_id=candidate_run_id, candidate_key=candidate_key,
                      baseline_grading_run_id=baseline_grading_run_id,
                      candidate_grading_run_id=candidate_grading_run_id, policy=policy)
    row = Comparison(project_id=project_id, baseline_run_id=baseline_run_id, candidate_run_id=candidate_run_id,
                     baseline_candidate_key=baseline_key, candidate_candidate_key=candidate_key,
                     grading_run_ids=result["grading_run_ids"], policy_id=policy_id,
                     compatibility=result["compatibility"], pairing=result["pairing"], method=result["method"],
                     metrics=result["metrics"], exclusions=result["exclusions"],
                     case_changes=result["case_changes"],
                     decision={**result["decision"], "invariant_failures": result["invariant_failures"],
                               "demo": result["demo"]})
    session.add(row)
    session.flush()
    return row
