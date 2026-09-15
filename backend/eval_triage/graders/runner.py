"""Dispatch graders and apply the dataset pass rule.

The pass rule names the mandatory graders. A trial

* **fails** if any applicable mandatory grader fails;
* **passes** only if every applicable mandatory grader passes and at least one applies;
* is otherwise **unresolved** (grader errors, abstentions, missing evidence, or
  only non-binary graders). Unresolved slots are never counted as failures or passes.

Optional graders are reported but cannot veto or satisfy the rule.
"""

from __future__ import annotations

import traceback
from collections.abc import Mapping
from typing import Any

from eval_triage.domain.enums import TRIAL_HAS_OUTPUT, GraderKind, Verdict
from eval_triage.graders.base import NO_OUTPUT, NOT_APPLICABLE, GradeResult, GradingContext, aggregate
from eval_triage.graders.deterministic import CHECK_FUNCTIONS
from eval_triage.graders.judge import JudgeCall, grade_model, grade_pairwise

IMPLEMENTATION_VERSION = "graders_v1"


def grade(ctx: GradingContext, judge: JudgeCall | None = None) -> GradeResult:
    kind = GraderKind(ctx.grader["kind"])
    if ctx.output is None or ctx.trial_status not in TRIAL_HAS_OUTPUT:
        return GradeResult(Verdict.UNAVAILABLE, reason=f"{NO_OUTPUT}: trial status {ctx.trial_status}")
    try:
        if kind in (GraderKind.DETERMINISTIC, GraderKind.STRUCTURED):
            checks = [CHECK_FUNCTIONS[name](ctx) for name in ctx.grader.get("checks", [])]
            verdict, reason = aggregate(checks)
            metrics = {c.name: c.metrics for c in checks if c.metrics}
            failed = [c for c in checks if c.applicable and c.binary and c.passed is False]
            explanation = "; ".join(f"{c.name}: {c.detail}" for c in (failed or [c for c in checks if c.applicable]))
            return GradeResult(verdict, reason=reason, checks=checks, metric=metrics or None,
                               explanation=explanation[:4000])
        if kind is GraderKind.MODEL:
            return grade_model(ctx, judge)
        if kind is GraderKind.PAIRWISE:
            return grade_pairwise(ctx, judge)
        plugin = (ctx.grader.get("config") or {}).get("plugin")
        return GradeResult(Verdict.UNAVAILABLE, reason=f"external plugin {plugin!r} is not installed or configured")
    except Exception as exc:  # noqa: BLE001 - a grader bug must surface as a grading error, never a verdict
        return GradeResult(Verdict.ERROR, reason="grader_exception",
                           error={"code": "grader_exception", "message": f"{type(exc).__name__}: {exc}",
                                  "traceback": traceback.format_exc(limit=5)})


def trial_outcome(grades: Mapping[str, Mapping[str, Any]], pass_rule: Mapping[str, Any]) -> dict[str, Any]:
    """``grades`` maps grader name -> {"verdict", "reason"}."""
    mandatory = list(pass_rule.get("mandatory_graders", []))
    applied, blockers = [], []
    for name in mandatory:
        grade_ = grades.get(name)
        if grade_ is None:
            blockers.append(f"{name}: not graded")
            continue
        verdict, reason = grade_.get("verdict"), grade_.get("reason")
        if verdict == Verdict.UNAVAILABLE and reason == NOT_APPLICABLE:
            continue
        applied.append(name)
        if verdict == Verdict.FAIL:
            return {"outcome": "fail", "reason": f"mandatory grader {name} failed", "mandatory": mandatory}
        if verdict != Verdict.PASS:
            blockers.append(f"{name}: {verdict}" + (f" ({reason})" if reason else ""))
    if blockers:
        return {"outcome": "unresolved", "reason": "; ".join(blockers), "mandatory": mandatory}
    if not applied:
        return {"outcome": "unresolved", "reason": "no mandatory grader applies to this case",
                "mandatory": mandatory}
    return {"outcome": "pass", "reason": "all applicable mandatory graders passed", "mandatory": mandatory}
