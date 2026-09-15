"""Grader contracts.

A grader evaluates a preserved trial output; it can never rewrite the output or
touch the target's state. Verdicts are ``pass``, ``fail``, ``abstain``,
``error`` (the *grader* failed) or ``unavailable`` (with a reason such as
``not_applicable``, ``not_a_binary_verdict`` or missing evidence). A grading
error never turns into a model pass or failure.

Normalised trial output consumed by graders::

    {
      "text": str | None,          # final answer / raw text
      "parsed": Any | None,        # parsed JSON when the contract expects JSON
      "parse_error": str | None,
      "tool_calls": [{"tool", "arguments", "result", "effects", "error", "valid_arguments"}],
      "effects": [str],
      "retrieved_ids": [str],
      "probability": float | None, "probability_unavailable_reason": str | None,
      "stores": {store: MemoryStateSnapshot-dict},   # final memory state per store
      "refused": bool | None,
    }

Episode step outputs (``StepOutput`` dicts) are passed separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eval_triage.domain.enums import Verdict

NOT_APPLICABLE = "not_applicable"
NOT_A_BINARY_VERDICT = "not_a_binary_verdict"
NO_OUTPUT = "no_output"


@dataclass
class CheckResult:
    name: str
    applicable: bool = True
    passed: bool | None = None
    detail: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    binary: bool = True
    unavailable_reason: str | None = None
    invariants: dict[str, str] = field(default_factory=dict)

    @classmethod
    def skip(cls, name: str, detail: str = "no expectation declared for this case") -> CheckResult:
        return cls(name=name, applicable=False, detail=detail)

    @classmethod
    def unavailable(cls, name: str, reason: str) -> CheckResult:
        return cls(name=name, passed=None, unavailable_reason=reason, detail=reason)

    @property
    def status(self) -> str:
        if not self.applicable:
            return NOT_APPLICABLE
        if not self.binary:
            return "measured"
        if self.passed is None:
            return "unavailable"
        return "pass" if self.passed else "fail"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "applicable": self.applicable, "passed": self.passed,
                "detail": self.detail, "evidence": self.evidence, "metrics": self.metrics,
                "unavailable_reason": self.unavailable_reason, "invariants": self.invariants}


@dataclass
class GradeResult:
    verdict: Verdict
    reason: str | None = None
    checks: list[CheckResult] = field(default_factory=list)
    metric: dict[str, Any] | None = None
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    explanation: str = ""
    error: dict[str, Any] | None = None
    judge_attempts: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def invariant_results(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for check in self.checks:
            for name, status in check.invariants.items():
                if merged.get(name) != "fail":
                    merged[name] = status
        return merged


@dataclass
class GradingContext:
    """Everything a grader may read. Built from immutable stored records."""

    scenario: dict[str, Any]
    case: dict[str, Any]
    grader: dict[str, Any]
    trial_status: str
    output: dict[str, Any] | None
    steps: list[dict[str, Any]] = field(default_factory=list)
    trial_id: str | None = None
    candidate_key: str | None = None
    repeat_index: int = 0
    related_outputs: dict[str, Any] = field(default_factory=dict)
    peer_output: dict[str, Any] | None = None
    peer_trial_id: str | None = None

    @property
    def pack(self) -> str:
        return self.scenario["pack"]

    @property
    def expected(self) -> dict[str, Any]:
        return self.case.get("expected") or {}

    def step(self, step_id: str) -> dict[str, Any] | None:
        return next((s for s in self.steps if s.get("step_id") == step_id), None)

    def case_step(self, step_id: str) -> dict[str, Any] | None:
        return next((s for s in self.case.get("episode") or [] if s.get("id") == step_id), None)


def aggregate(checks: list[CheckResult]) -> tuple[Verdict, str | None]:
    """Combine check results into one verdict for a deterministic grader."""
    applicable = [c for c in checks if c.applicable]
    if not applicable:
        return Verdict.UNAVAILABLE, NOT_APPLICABLE
    binary = [c for c in applicable if c.binary]
    if not binary:
        return Verdict.UNAVAILABLE, NOT_A_BINARY_VERDICT
    if any(c.passed is False for c in binary):
        return Verdict.FAIL, None
    missing = [c for c in binary if c.passed is None]
    if missing:
        return Verdict.UNAVAILABLE, "; ".join(f"{c.name}: {c.unavailable_reason}" for c in missing)
    return Verdict.PASS, None
