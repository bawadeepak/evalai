"""Run validation, idempotent creation and cancellation.

All planned trial slots (cases × candidates × repeats) are created in one
transaction before anything is dispatched, together with one durable job per
trial. Scheduling order is a deterministic shuffle recorded by its seed.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from eval_triage.adapters.base import PARAMETER_CAPABILITIES
from eval_triage.adapters.pricing import estimate_run_cost, load_pricing
from eval_triage.config import Settings
from eval_triage.db.models import (
    Case,
    DatasetVersion,
    GraderVersion,
    GradingRun,
    IdempotencyKey,
    Project,
    Run,
    RunCandidate,
    ScenarioVersion,
    TargetConfigVersion,
    Trial,
)
from eval_triage.db.repositories import grader_spec
from eval_triage.db.types import utcnow
from eval_triage.domain.canonical import content_hash
from eval_triage.domain.enums import RUN_TERMINAL, JobKind, RunStatus, TrialStatus
from eval_triage.execution import events, jobs
from eval_triage.execution.manifest import build_manifest, manifest_hash

#: Parameters the adapters interpret themselves (not provider sampling parameters).
ADAPTER_PARAMETERS = {"profile", "delay_ms", "max_tokens", "max_output_tokens", "system", "stop", "reasoning",
                      "max_turns", "effort", "max_completion_tokens"}
DEFAULT_CONCURRENCY = {"memoryai": 1}
STATELESS_DEFAULT_CONCURRENCY = 2


class CandidateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    target_config_id: str


class ExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repeats: int = Field(default=5, ge=1, le=500)
    max_concurrency: int | None = Field(default=None, ge=1, le=16)
    repeat_mode: Literal["full_episode", "frozen_context"] = "full_episode"
    cache_outputs: bool = False
    schedule_seed: int = 42
    restart_interrupted_episodes: bool = True
    max_transport_retries: int = Field(default=2, ge=0, le=2)


class LimitsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_target_calls: int | None = Field(default=None, ge=1)
    max_judge_calls: int | None = Field(default=None, ge=0)
    max_cost: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    timeout_seconds: float = Field(default=120.0, gt=0, le=3600)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    scenario_id: str
    dataset_id: str
    name: str = ""
    candidates: list[CandidateSpec] = Field(min_length=1, max_length=4)
    grader_ids: list[str] | None = None
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)
    limits: LimitsSpec = Field(default_factory=LimitsSpec)
    case_ids: list[str] | None = None
    parent_run_id: str | None = None

    @field_validator("candidates")
    @classmethod
    def _unique_keys(cls, value):
        keys = [c.key for c in value]
        if len(set(keys)) != len(keys):
            raise ValueError("candidate keys must be unique")
        return value


class RunValidationError(Exception):
    def __init__(self, errors: list[dict[str, Any]], status: int = 422) -> None:
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors
        self.status = status


def _err(field: str, message: str, code: str = "invalid") -> dict[str, Any]:
    return {"field": field, "message": message, "code": code}


def schedule_order(keys: list[tuple[str, str, int]], seed: int) -> dict[tuple[str, str, int], int]:
    ranked = sorted(keys, key=lambda k: hashlib.sha256(f"{seed}:{k[0]}:{k[1]}:{k[2]}".encode()).hexdigest())
    return {key: index for index, key in enumerate(ranked)}


def validate_run(session, settings: Settings, request: RunRequest) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    project = session.get(Project, request.project_id)
    scenario = session.get(ScenarioVersion, request.scenario_id)
    dataset = session.get(DatasetVersion, request.dataset_id)
    if project is None:
        errors.append(_err("project_id", "project not found", "not_found"))
    if scenario is None or (project and scenario.project_id != project.id):
        errors.append(_err("scenario_id", "scenario version not found in this project", "not_found"))
    if dataset is None or (project and dataset.project_id != project.id):
        errors.append(_err("dataset_id", "dataset version not found in this project", "not_found"))
    if scenario and dataset and dataset.scenario_id != scenario.id:
        errors.append(_err("dataset_id", "dataset version belongs to a different scenario version", "mismatch"))
    if request.execution.cache_outputs:
        errors.append(_err("execution.cache_outputs", "output caching is not allowed: every repeat must be a "
                                                      "fresh execution", "unsupported"))
    if errors:
        raise RunValidationError(errors, 404 if all(e["code"] == "not_found" for e in errors) else 422)

    cases = list(session.scalars(select(Case).where(Case.dataset_id == dataset.id).order_by(Case.ordinal)))
    if request.case_ids is not None:
        wanted = set(request.case_ids)
        cases = [c for c in cases if c.id in wanted or c.external_id in wanted]
        if not cases:
            errors.append(_err("case_ids", "no matching cases in this dataset"))
    pack = scenario.pack
    if request.execution.repeat_mode == "frozen_context" and pack != "memory_lifecycle":
        errors.append(_err("execution.repeat_mode", "frozen_context applies only to memory episodes"))

    pricing = load_pricing(settings)
    candidates, cost_estimates, is_demo = [], {}, bool(scenario.is_demo and dataset.is_demo)
    stage_calls = _stage_calls(scenario, cases)
    for index, cand in enumerate(request.candidates):
        field = f"candidates[{index}]"
        config = session.get(TargetConfigVersion, cand.target_config_id)
        if config is None or config.project_id != project.id:
            errors.append(_err(f"{field}.target_config_id", "target configuration not found", "not_found"))
            continue
        is_demo = is_demo and config.adapter == "demo"
        caps = config.capabilities or {}
        for param in config.parameters:
            if param in ADAPTER_PARAMETERS:
                continue
            capability = PARAMETER_CAPABILITIES.get(param)
            state = (caps.get(capability) or {}).get("state", "unknown") if capability else "unknown"
            if state == "unsupported":
                errors.append(_err(f"{field}.parameters.{param}",
                                   f"{config.name}: parameter {param!r} is unsupported by {config.adapter}"
                                   f"/{config.model or config.endpoint_type} "
                                   f"({(caps.get(capability) or {}).get('source', 'capability table')})",
                                   "capability_conflict"))
            elif state == "unknown":
                if config.experimental:
                    warnings.append(f"{config.name}: {param!r} support is unknown; sent in experimental mode")
                else:
                    errors.append(_err(f"{field}.parameters.{param}",
                                       f"{config.name}: support for {param!r} is unknown; run a connection test "
                                       "or enable experimental mode on the configuration", "capability_unknown"))
        if pack == "memory_lifecycle" and (caps.get("episodes") or {}).get("state") != "supported":
            errors.append(_err(f"{field}.target_config_id", f"{config.name} cannot run memory episodes; use the "
                                                            "MemoryAI or demo adapter", "capability_conflict"))
        if pack == "tool_agent" and (caps.get("tools") or {}).get("state") == "unsupported":
            errors.append(_err(f"{field}.target_config_id", f"{config.name} does not support tools",
                               "capability_conflict"))
        if config.adapter == "memoryai":
            memory = config.memory_config or {}
            if memory.get("backend", "real") == "real" and not (settings.memoryai_source_path.is_dir()
                                                                and settings.resolved_memoryai_python.exists()):
                errors.append(_err(f"{field}.target_config_id", "MemoryAI prerequisites missing: set "
                                                                "MEMORYAI_SOURCE_PATH and MEMORYAI_PYTHON",
                                   "prerequisite_missing"))
            if any(step.get("action") == "generate" for case in cases for step in case.episode) and not memory.get(
                    "generation_target_config_id"):
                errors.append(_err(f"{field}.target_config_id", "episodes with generate steps need "
                                                                "memory_config.generation_target_config_id (MemoryAI's "
                                                                "recall returns context, not an answer)",
                                   "generation_target_missing"))
        if config.credential_ref and not os.environ.get(config.credential_ref):
            errors.append(_err(f"{field}.target_config_id", f"credential {config.credential_ref} is not set in "
                                                            "the server environment", "credential_missing"))
        calls = len(cases) * request.execution.repeats * stage_calls
        cost_estimates[cand.key] = estimate_run_cost(pricing, config.adapter, config.model, calls)
        candidates.append({"key": cand.key, "config": _config_manifest(config), "ordinal": index})

    grader_ids = request.grader_ids if request.grader_ids is not None else list(scenario.grader_refs)
    graders = []
    for gid in grader_ids:
        row = session.get(GraderVersion, gid)
        if row is None or row.project_id != project.id:
            errors.append(_err("grader_ids", f"grader {gid} not found", "not_found"))
            continue
        spec = grader_spec(row)
        if row.kind in ("model", "pairwise") and not row.judge_config_id:
            warnings.append(f"grader {row.name} has no judge configured; its grades will be unavailable")
        graders.append(spec)
    mandatory = set(dataset.pass_rule.get("mandatory_graders", []))
    missing = mandatory - {g["name"] for g in graders}
    if missing:
        errors.append(_err("grader_ids", f"mandatory graders {sorted(missing)} must be included", "pass_rule"))

    planned_trials = len(cases) * len(request.candidates) * request.execution.repeats
    target_calls = planned_trials * stage_calls
    judge_graders = [g for g in graders if g["kind"] in ("model", "pairwise") and g["judge_config_id"]]
    judge_calls = planned_trials * len(judge_graders)
    if request.limits.max_target_calls is not None and target_calls > request.limits.max_target_calls:
        errors.append(_err("limits.max_target_calls", f"the plan needs about {target_calls} target calls, above "
                                                      f"the limit of {request.limits.max_target_calls}", "limit"))
    if request.limits.max_judge_calls is not None and judge_calls > request.limits.max_judge_calls:
        errors.append(_err("limits.max_judge_calls", f"the plan needs about {judge_calls} judge calls, above the "
                                                     f"limit of {request.limits.max_judge_calls}", "limit"))
    unknown_cost = [k for k, v in cost_estimates.items() if v["amount"] is None]
    if request.limits.max_cost is not None and unknown_cost:
        errors.append(_err("limits.max_cost", f"a monetary cap needs known pricing; unknown for {unknown_cost}",
                           "pricing_unknown"))
    if errors:
        raise RunValidationError(errors)

    execution = request.execution.model_dump(mode="json")
    limits = request.limits.model_dump(mode="json")
    manifest = build_manifest(settings=settings, scenario=scenario, dataset=dataset, candidates=candidates,
                              graders=[{k: g[k] for k in ("id", "name", "kind", "hash", "implementation_version",
                                                          "judge_config_id")} for g in graders],
                              execution=execution, limits=limits, is_demo=is_demo, warnings=warnings,
                              case_ids=[c.id for c in cases])
    return {
        "scenario": scenario, "dataset": dataset, "cases": cases, "graders": graders, "is_demo": is_demo,
        "manifest": manifest, "manifest_hash": manifest_hash(manifest), "warnings": warnings,
        "plan": {"cases": len(cases), "candidates": len(request.candidates), "repeats": request.execution.repeats,
                 "planned_trials": planned_trials, "stage_calls_per_episode": stage_calls,
                 "target_calls_estimate": target_calls, "judge_calls_estimate": judge_calls,
                 "judge_calls_note": "estimate; each invalid judge reply may add one formatting retry",
                 "cost_estimates": cost_estimates},
    }


def _stage_calls(scenario, cases: list[Case]) -> int:
    if scenario.pack == "memory_lifecycle":
        return max([sum(1 for s in c.episode if s["action"] == "generate") for c in cases] + [0]) or 0
    if scenario.pack == "tool_agent":
        return 3
    return 1


def _config_manifest(config: TargetConfigVersion) -> dict[str, Any]:
    return {"id": config.id, "hash": config.hash, "name": config.name, "adapter": config.adapter,
            "adapter_version": config.adapter_version, "endpoint_type": config.endpoint_type,
            "requested_model": config.model, "base_url": config.base_url,
            "credential_ref": config.credential_ref, "parameters": config.parameters,
            "prompt_template": config.prompt_template, "tools": config.tools,
            "memory_config": config.memory_config, "capabilities": config.capabilities,
            "experimental": config.experimental}


def _concurrency(config: dict[str, Any], requested: int | None) -> tuple[str, int]:
    adapter = config["adapter"]
    if adapter == "memoryai":
        return "memoryai", 1
    return f"target:{config['id']}", requested or DEFAULT_CONCURRENCY.get(adapter, STATELESS_DEFAULT_CONCURRENCY)


def create_run(db, settings: Settings, request: RunRequest, idempotency_key: str | None) -> tuple[int, dict]:
    body_hash = content_hash(request.model_dump(mode="json"))
    with db.write() as session:
        if idempotency_key:
            existing = session.get(IdempotencyKey, idempotency_key)
            if existing is not None:
                if existing.request_hash != body_hash:
                    raise RunValidationError([_err("Idempotency-Key", "this idempotency key was already used with "
                                                                      "a different request body", "conflict")], 409)
                return existing.status_code, existing.response
        plan = validate_run(session, settings, request)
        run = Run(project_id=request.project_id, scenario_id=request.scenario_id, dataset_id=request.dataset_id,
                  name=request.name or f"{plan['scenario'].name} · {utcnow():%Y-%m-%d %H:%M}",
                  manifest=plan["manifest"], manifest_hash=plan["manifest_hash"], status=RunStatus.QUEUED,
                  planned_trial_count=plan["plan"]["planned_trials"], budget=request.limits.model_dump(mode="json"),
                  usage={}, is_demo=plan["is_demo"], parent_run_id=request.parent_run_id)
        session.add(run)
        session.flush()
        for cand in plan["manifest"]["candidates"]:
            session.add(RunCandidate(run_id=run.id, candidate_key=cand["key"],
                                     target_config_id=cand["config"]["id"], ordinal=cand["ordinal"]))
        grading = GradingRun(run_id=run.id, source="initial", grader_ids=[g["id"] for g in plan["graders"]],
                             grader_hashes=[g["hash"] for g in plan["graders"]], status="queued")
        session.add(grading)
        repeats = request.execution.repeats
        keys = [(c.id, cand["key"], r) for c in plan["cases"] for cand in plan["manifest"]["candidates"]
                for r in range(repeats)]
        order = schedule_order(keys, request.execution.schedule_seed)
        configs = {cand["key"]: cand["config"] for cand in plan["manifest"]["candidates"]}
        for case_id, key, repeat in keys:
            trial = Trial(run_id=run.id, case_id=case_id, candidate_key=key, repeat_index=repeat,
                          schedule_order=order[(case_id, key, repeat)], status=TrialStatus.PENDING)
            session.add(trial)
            session.flush()
            ckey, limit = _concurrency(configs[key], request.execution.max_concurrency)
            jobs.enqueue(session, JobKind.TRIAL, {"trial_id": trial.id, "grading_run_id": grading.id},
                         run_id=run.id, concurrency_key=ckey, concurrency_limit=limit,
                         priority=order[(case_id, key, repeat)], max_attempts=3)
        events.emit(session, run.id, "run.queued", run.id, {"planned": run.planned_trial_count})
        response = {"data": {"id": run.id, "status": run.status, "manifest_hash": run.manifest_hash,
                             "plan": plan["plan"], "warnings": plan["warnings"]}, "meta": {}}
        if idempotency_key:
            session.add(IdempotencyKey(key=idempotency_key, scope="runs", request_hash=body_hash, status_code=201,
                                       response=response))
        return 201, response


def cancel_run(db, run_id: str) -> Run | None:
    from eval_triage.execution.finalize import maybe_finalize

    with db.write() as session:
        run = session.get(Run, run_id)
        if run is None:
            return None
        if run.status in RUN_TERMINAL:
            return run
        run.cancel_requested_at = run.cancel_requested_at or utcnow()
        run.status = RunStatus.CANCELLING
        jobs.cancel_queued(session, run_id, [JobKind.TRIAL])
        for trial in session.scalars(select(Trial).where(Trial.run_id == run_id,
                                                         Trial.status == TrialStatus.PENDING)):
            trial.status = TrialStatus.CANCELLED
            trial.error = {"code": "cancelled", "message": "run cancelled before this trial started"}
            trial.finished_at = utcnow()
        events.emit(session, run_id, "run.progress", run_id, {"status": "cancelling"})
        maybe_finalize(session, run_id)
        return run
