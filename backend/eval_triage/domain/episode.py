"""Episode action DSL: a typed, sequential list of steps executed in one isolated session.

Action union: ``remember``, ``assert``, ``approve``, ``reject``, ``wrong``,
``forget``, ``rebuild``, ``recall``, ``generate``, ``tool_call``,
``inspect_state``, ``assert_state``. Each action has typed arguments. Steps may
target or reference only *earlier* steps; symbolic step ids are resolved to real
event/fact ids by the executing adapter and recorded in a mapping artifact.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from eval_triage.domain.refs import STEP_ID_PATTERN, parse_ref, ref_step


def _check_ref(value: str) -> str:
    parse_ref(value)
    return value


Ref = Annotated[str, AfterValidator(_check_ref)]
StepId = Annotated[str, Field(pattern=f"^{STEP_ID_PATTERN}$")]
StoreName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RememberArgs(_Model):
    text: str = Field(min_length=1, max_length=20000)
    actor: Literal["user", "assistant", "system"] = "user"


class AssertArgs(_Model):
    text: str = Field(min_length=1, max_length=20000)
    status: Literal["candidate", "approved"] = "candidate"


class StepTargetArgs(_Model):
    step: StepId


class WrongArgs(_Model):
    step: StepId
    claim_contains: str | None = Field(default=None, min_length=1)


class EmptyArgs(_Model):
    pass


class RecallArgs(_Model):
    query: str = Field(min_length=1, max_length=4000)
    level: Literal["low", "mid", "high"] = "mid"
    budget: int = Field(default=400, ge=1, le=100000)


class GenerateArgs(_Model):
    question: str = Field(min_length=1, max_length=20000)
    context_ref: Ref | None = None
    system_prompt: str | None = None


class ToolCallArgs(_Model):
    tool: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class StateCheck(_Model):
    kind: Literal["fact_present", "fact_absent", "queue_empty", "fact_count"]
    claim_contains: str | None = None
    state: Literal["active", "historical", "rejected", "withdrawn", "invalidated"] | None = None
    equals: int | None = Field(default=None, ge=0)


class AssertStateArgs(_Model):
    checks: list[StateCheck] = Field(min_length=1)


class _StepBase(_Model):
    id: StepId
    store: StoreName = "main"
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)


class RememberStep(_StepBase):
    action: Literal["remember"]
    args: RememberArgs


class AssertStep(_StepBase):
    action: Literal["assert"]
    args: AssertArgs


class ApproveStep(_StepBase):
    action: Literal["approve"]
    args: StepTargetArgs


class RejectStep(_StepBase):
    action: Literal["reject"]
    args: StepTargetArgs


class WrongStep(_StepBase):
    action: Literal["wrong"]
    args: WrongArgs


class ForgetStep(_StepBase):
    action: Literal["forget"]
    args: StepTargetArgs


class RebuildStep(_StepBase):
    action: Literal["rebuild"]
    args: EmptyArgs = Field(default_factory=EmptyArgs)


class RecallStep(_StepBase):
    action: Literal["recall"]
    args: RecallArgs


class GenerateStep(_StepBase):
    action: Literal["generate"]
    args: GenerateArgs


class ToolCallStep(_StepBase):
    action: Literal["tool_call"]
    args: ToolCallArgs


class InspectStateStep(_StepBase):
    action: Literal["inspect_state"]
    args: EmptyArgs = Field(default_factory=EmptyArgs)


class AssertStateStep(_StepBase):
    action: Literal["assert_state"]
    args: AssertStateArgs


Step = Annotated[
    RememberStep | AssertStep | ApproveStep | RejectStep | WrongStep | ForgetStep | RebuildStep | RecallStep
    | GenerateStep | ToolCallStep | InspectStateStep | AssertStateStep,
    Field(discriminator="action"),
]

ACTIONS = ("remember", "assert", "approve", "reject", "wrong", "forget", "rebuild", "recall", "generate",
           "tool_call", "inspect_state", "assert_state")

#: Actions that may change the state of the system under test. A timeout on one
#: of these leaves the outcome unknown; it is never retried blindly.
MUTATING_ACTIONS = frozenset({"remember", "assert", "approve", "reject", "wrong", "forget", "rebuild", "tool_call"})

DEFAULT_TIMEOUT_SECONDS = {
    "remember": 180.0, "assert": 180.0, "approve": 180.0, "reject": 30.0, "wrong": 120.0, "forget": 120.0,
    "rebuild": 600.0, "recall": 90.0, "generate": 180.0, "tool_call": 30.0, "inspect_state": 60.0,
    "assert_state": 60.0,
}


def step_timeout(step) -> float:
    return step.timeout_seconds or DEFAULT_TIMEOUT_SECONDS[step.action]


def step_references(step) -> list[str]:
    refs: list[str] = []
    if step.action == "generate" and step.args.context_ref:
        refs.append(step.args.context_ref)
    return refs


def step_dependencies(step) -> set[str]:
    """Earlier steps whose failure makes this step meaningless (it is then skipped)."""
    deps = {ref_step(ref) for ref in step_references(step)}
    target = getattr(step.args, "step", None)
    if target:
        deps.add(target)
    return deps


def episode_errors(steps: list) -> list[tuple[tuple[Any, ...], str]]:
    """Semantic checks that per-step schemas cannot express."""
    errors: list[tuple[tuple[Any, ...], str]] = []
    seen: dict[str, Any] = {}
    for index, step in enumerate(steps):
        if step.id in seen:
            errors.append(((index, "id"), f"duplicate step id {step.id!r}"))
        target = getattr(step.args, "step", None)
        if target is not None:
            prior = seen.get(target)
            if prior is None:
                errors.append(((index, "args", "step"), f"step {target!r} must be an earlier step in this episode"))
            else:
                if step.action in ("approve", "reject") and not (
                    prior.action == "assert" and prior.args.status == "candidate"
                ):
                    errors.append(((index, "args", "step"),
                                   f"{step.action} must target an earlier candidate 'assert' step"))
                if step.action in ("wrong", "forget") and prior.action not in ("remember", "assert"):
                    errors.append(((index, "args", "step"),
                                   f"{step.action} must target an earlier 'remember' or 'assert' step"))
                if prior.store != step.store:
                    errors.append(((index, "store"),
                                   f"target step {target!r} belongs to store {prior.store!r}, not {step.store!r}"))
        for ref in step_references(step):
            referenced = ref_step(ref)
            if referenced not in seen:
                errors.append(((index, "args", "context_ref"),
                               f"reference {ref!r} must point to an earlier step"))
        seen.setdefault(step.id, step)
    return errors
