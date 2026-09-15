"""Execute one trial: a stateless call, an agent tool loop, or a full memory episode.

* A running attempt row is written *before* the external call so a worker crash
  leaves evidence. On recovery that attempt is marked ``interrupted``.
* Interrupted memory episodes are never replayed in the same store; with
  ``restart_interrupted_episodes`` they restart from scratch in a fresh
  isolated store as a new recorded attempt, otherwise the trial is
  ``indeterminate``.
* Results that arrive after a cancel request are still recorded.
* Terminal attempts and trials are immutable, so every field of a finished
  attempt is written in a single update with the status assigned last.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import func, select

from eval_triage.adapters.base import RunContext, TargetConfig, TargetRequest, TargetResult
from eval_triage.adapters.registry import get_adapter
from eval_triage.api.context import AppContext
from eval_triage.artifacts.records import store_json
from eval_triage.db.models import Attempt, Case, Run, ScenarioVersion, TargetConfigVersion, Trial
from eval_triage.db.types import utcnow
from eval_triage.domain.enums import TRIAL_TERMINAL, AttemptStatus, JobKind, RunStatus, TrialStatus
from eval_triage.execution import events, jobs
from eval_triage.execution.common import Defer
from eval_triage.execution.episode import run_episode
from eval_triage.execution.executors import call_target, execute_agent, execute_stateless, request_parameters
from eval_triage.execution.finalize import maybe_finalize, trial_counts
from eval_triage.security.redaction import redact

GRADING_CONCURRENCY = 4
#: Umbrella stages that group sub-calls; they are not counted as target calls for budgets.
UMBRELLA_STAGES = ("episode", "execution")


def _case_dict(row: Case) -> dict[str, Any]:
    return {"id": row.id, "external_id": row.external_id, "purpose": row.purpose, "input": row.input,
            "episode": row.episode, "expected": row.expected, "alternatives": row.alternatives,
            "evidence": row.evidence, "tags": row.tags, "severity": row.severity, "cluster_id": row.cluster_id,
            "weight": row.weight, "split": row.split, "case_hash": row.case_hash,
            "fixture_options": row.fixture_options or {}}


def _is_agentic(scenario: dict[str, Any]) -> bool:
    return scenario["pack"] == "tool_agent" or (scenario["pack"] == "robustness_security"
                                                and bool(scenario.get("tools")))


def enqueue_grade(session, trial: Trial, grading_run_id: str) -> None:
    jobs.enqueue(session, JobKind.GRADE, {"trial_id": trial.id, "grading_run_id": grading_run_id},
                 run_id=trial.run_id, concurrency_key="grading", concurrency_limit=GRADING_CONCURRENCY,
                 priority=-1, max_attempts=3)


def terminate(session, trial: Trial, status: str, error: dict | None, grading_run_id: str) -> None:
    """Make the trial terminal (last write to it), queue its grading and report progress."""
    trial.error = error
    trial.finished_at = utcnow()
    trial.status = status
    session.flush()
    enqueue_grade(session, trial, grading_run_id)
    events.emit(session, trial.run_id, "run.progress", trial.id,
                {"trial_status": status, "counts": trial_counts(session, trial.run_id)})


def _prepare(app: AppContext, trial_id: str, grading_run_id: str, worker_id: str) -> dict[str, Any] | None:
    with app.db.write() as session:
        trial = session.get(Trial, trial_id)
        if trial is None or trial.status in TRIAL_TERMINAL:
            return None
        run = session.get(Run, trial.run_id)
        if run.status in (RunStatus.CANCELLING, RunStatus.CANCELLED) or run.cancel_requested_at:
            terminate(session, trial, TrialStatus.CANCELLED,
                      {"code": "cancelled", "message": "run cancelled before this trial started"}, grading_run_id)
            maybe_finalize(session, run.id)
            return None
        execution, limits = run.manifest["execution"], run.manifest["limits"]
        scenario = session.get(ScenarioVersion, run.scenario_id).definition
        case_row = session.get(Case, trial.case_id)
        case = _case_dict(case_row)
        candidate = next(c for c in run.manifest["candidates"] if c["key"] == trial.candidate_key)
        config_row = session.get(TargetConfigVersion, candidate["config"]["id"])
        memory = scenario["pack"] == "memory_lifecycle"

        # Recover attempts left running by a worker that died.
        interrupted = session.scalars(select(Attempt).where(Attempt.trial_id == trial.id,
                                                            Attempt.status == AttemptStatus.RUNNING)).all()
        for attempt in interrupted:
            attempt.finished_at = utcnow()
            attempt.mutation_outcome_known = not memory
            attempt.error = {"code": "interrupted", "message": "worker stopped before this attempt finished"}
            attempt.status = AttemptStatus.INTERRUPTED
        session.flush()
        if interrupted and memory and not execution.get("restart_interrupted_episodes", True):
            terminate(session, trial, TrialStatus.INDETERMINATE,
                      {"code": "interrupted_episode", "message": "an episode was interrupted mid-mutation and "
                                                                 "restart is disabled"}, grading_run_id)
            maybe_finalize(session, run.id)
            return None

        max_calls = limits.get("max_target_calls")
        if max_calls is not None:
            used = session.scalar(select(func.count()).select_from(Attempt).join(Trial).where(
                Trial.run_id == run.id, Attempt.stage.notin_(UMBRELLA_STAGES)))
            if used >= max_calls:
                terminate(session, trial, TrialStatus.SKIPPED,
                          {"code": "budget_exhausted", "message": f"max_target_calls ({max_calls}) reached"},
                          grading_run_id)
                maybe_finalize(session, run.id)
                return None

        frozen_source = None
        if execution.get("repeat_mode") == "frozen_context" and trial.repeat_index > 0:
            source = session.scalars(select(Trial).where(Trial.run_id == run.id, Trial.case_id == trial.case_id,
                                                         Trial.candidate_key == trial.candidate_key,
                                                         Trial.repeat_index == 0)).first()
            if source is None or source.status not in TRIAL_TERMINAL:
                return {"defer": "waiting for repeat 0 to capture the frozen context"}
            if source.status != TrialStatus.SUCCESS:
                terminate(session, trial, TrialStatus.SKIPPED,
                          {"code": "no_frozen_context", "message": f"repeat 0 ended {source.status}"},
                          grading_run_id)
                maybe_finalize(session, run.id)
                return None
            frozen_source = {"trial_id": source.id, "steps": source.steps,
                             "stores": (source.output or {}).get("stores", {})}

        if run.status == RunStatus.QUEUED:
            run.status = RunStatus.RUNNING
            run.started_at = utcnow()
            events.emit(session, run.id, "run.started", run.id, {"planned": run.planned_trial_count})
        if trial.status == TrialStatus.PENDING:
            events.emit(session, run.id, "trial.started", trial.id,
                        {"case": case_row.external_id, "candidate": trial.candidate_key,
                         "repeat": trial.repeat_index})
        trial.status = TrialStatus.RUNNING
        trial.started_at = trial.started_at or utcnow()
        stage = "episode" if memory else ("execution" if _is_agentic(scenario) else "target")
        prior = session.scalar(select(func.count()).select_from(Attempt).where(Attempt.trial_id == trial.id,
                                                                               Attempt.stage == stage))
        attempt = Attempt(trial_id=trial.id, stage=stage, attempt_index=prior, status=AttemptStatus.RUNNING,
                          requested_model=config_row.model, worker_id=worker_id,
                          mutation_outcome_known=stage != "episode")
        session.add(attempt)
        session.flush()
        generation = None
        if config_row.adapter == "memoryai":
            gen_id = (config_row.memory_config or {}).get("generation_target_config_id")
            gen_row = session.get(TargetConfigVersion, gen_id) if gen_id else None
            generation = TargetConfig.from_row(gen_row) if gen_row else None
        return {
            "trial_id": trial.id, "run_id": run.id, "grading_run_id": grading_run_id, "case": case,
            "scenario": scenario, "config": TargetConfig.from_row(config_row),
            "capabilities": config_row.capabilities or {}, "execution": execution, "limits": limits,
            "is_demo": run.is_demo, "attempt_id": attempt.id, "attempt_index": prior, "stage": stage,
            "candidate_key": trial.candidate_key, "repeat_index": trial.repeat_index,
            "frozen_source": frozen_source, "generation": generation,
        }


async def run_trial_job(app: AppContext, job, worker_id: str) -> dict[str, Any]:
    prep = await asyncio.to_thread(_prepare, app, job.payload["trial_id"], job.payload["grading_run_id"], worker_id)
    if prep is None:
        return {"skipped": True}
    if "defer" in prep:
        raise Defer(1.0, prep["defer"])
    try:
        outcome = await _execute(app, prep)
    except Exception as exc:  # noqa: BLE001 - adapter defects become recorded provider errors
        outcome = {"status": TrialStatus.PROVIDER_ERROR, "output": None, "steps": [],
                   "error": {"code": "adapter_exception", "message": f"{type(exc).__name__}: {exc}"[:1000]},
                   "attempts": [], "latency_ms": None}
    await asyncio.to_thread(_finish, app, prep, outcome)
    return {"trial_status": outcome["status"]}


def _context(app: AppContext, prep: dict[str, Any]) -> RunContext:
    return RunContext(run_id=prep["run_id"], trial_id=prep["trial_id"], candidate_key=prep["candidate_key"],
                      repeat_index=prep["repeat_index"], case_external_id=prep["case"]["external_id"],
                      attempt_index=prep["attempt_index"], data_dir=app.settings.data_dir,
                      fixture_options=prep["case"].get("fixture_options") or {}, is_demo=prep["is_demo"])


async def _execute(app: AppContext, prep: dict[str, Any]) -> dict[str, Any]:
    attempts: list[tuple[str, int, TargetResult]] = []
    config: TargetConfig = prep["config"]
    scenario, case = prep["scenario"], prep["case"]
    execution, limits = prep["execution"], prep["limits"]
    context = _context(app, prep)
    timeout = float(limits.get("timeout_seconds") or 120)
    retries = int(execution.get("max_transport_retries", 2))

    def on_attempt(stage: str, index: int, result: TargetResult) -> None:
        attempts.append((stage, index, result))

    if scenario["pack"] == "memory_lifecycle":
        return await _execute_episode(app, prep, context, attempts, on_attempt, timeout, retries)
    adapter = get_adapter(config.adapter)
    session = await adapter.prepare(config, context)
    try:
        runner = execute_agent if _is_agentic(scenario) else execute_stateless
        status, output, result = await runner(adapter, session, config, scenario, case, prep["repeat_index"],
                                              timeout=timeout, max_retries=retries, on_attempt=on_attempt,
                                              capabilities=prep["capabilities"])
    finally:
        await adapter.close(session)
    has_output = status in (TrialStatus.SUCCESS, TrialStatus.INVALID_OUTPUT)
    return {"status": status, "output": output if has_output else None, "steps": [],
            "error": None if has_output else (result.error or {"code": status}), "attempts": attempts,
            "latency_ms": sum(r.latency_ms or 0 for _, _, r in attempts) or result.latency_ms}


async def _execute_episode(app, prep, context, attempts, on_attempt, timeout, retries) -> dict[str, Any]:
    config: TargetConfig = prep["config"]
    case = prep["case"]
    backend, prepare_kwargs = _memory_backend(app, config, case)
    gen_adapter, gen_session, gen_config = None, None, prep.get("generation")
    if gen_config is not None:
        gen_adapter = get_adapter(gen_config.adapter)
        gen_session = await gen_adapter.prepare(gen_config, context)

    async def generate(step_id: str, messages: list[dict[str, str]]) -> TargetResult:
        request = TargetRequest(messages=messages, parameters=request_parameters(gen_config),
                                metadata={"pack": "memory_lifecycle", "external_id": case["external_id"],
                                          "repeat_index": prep["repeat_index"], "stage": "generate"})
        return await call_target(gen_adapter, gen_session, request, timeout=timeout, max_retries=retries,
                                 on_attempt=on_attempt, stage=f"generate:{step_id}")

    try:
        if prep["frozen_source"]:
            episode = await _frozen_episode(backend, prepare_kwargs, context, case, prep["frozen_source"],
                                            generate if gen_adapter else None)
        else:
            episode = await run_episode(backend, case, prepare_kwargs=prepare_kwargs, context=context,
                                        generate=generate if gen_adapter else None)
    finally:
        if gen_adapter is not None:
            await gen_adapter.close(gen_session)
    status = {"ok": TrialStatus.SUCCESS, "indeterminate": TrialStatus.INDETERMINATE}.get(
        episode["status"], TrialStatus.PROVIDER_ERROR)
    output = {"text": episode["text"], "parsed": None, "parse_error": None, "stores": episode["stores"],
              "tool_calls": [], "effects": [], "retrieved_ids": None, "probability": None,
              "probability_unavailable_reason": "memory episodes do not produce event probabilities",
              "refused": None, "event_ids": episode["event_ids"], "store_close": episode["close"],
              "frozen_from_trial": (prep["frozen_source"] or {}).get("trial_id")}
    return {"status": status, "output": output if status == TrialStatus.SUCCESS else None,
            "partial_output": output if status != TrialStatus.SUCCESS else None,
            "steps": episode["steps"], "error": episode["error"], "attempts": attempts,
            "latency_ms": sum(s.get("elapsed_ms") or 0 for s in episode["steps"]),
            "episode_status": episode["status"]}


def _memory_backend(app: AppContext, config: TargetConfig, case: dict[str, Any]):
    if config.adapter == "demo":
        from eval_triage.adapters.demo import DemoMemoryBackend

        return DemoMemoryBackend(), {"profile": config.parameters.get("profile", "baseline"),
                                     "external_id": case["external_id"]}
    if config.adapter == "memoryai":
        from eval_triage.adapters.memoryai.adapter import memory_backend

        return memory_backend(app, config), {}
    raise ValueError(f"adapter {config.adapter} cannot run memory episodes")


async def _frozen_episode(backend, prepare_kwargs, context, case, source, generate) -> dict[str, Any]:
    """Repeat only generation over the context captured by repeat 0 (no mutation)."""
    from eval_triage.domain.refs import resolve_ref
    from eval_triage.execution.prompts import memory_answer_messages

    records, answers = [], []
    session = await backend.prepare(sorted({s.get("store", "main") for s in case["episode"]}) or ["main"], context,
                                    **prepare_kwargs)
    try:
        outputs = {s["step_id"]: s.get("output", {}) for s in source["steps"]}
        for step, prior in zip(case["episode"], source["steps"], strict=False):
            if step["action"] != "generate":
                records.append({**prior, "frozen_from": source["trial_id"]})
                continue
            ref = step["args"].get("context_ref")
            context_text = resolve_ref(ref, outputs) if ref else None
            base = {"step_id": step["id"], "action": "generate", "store": step.get("store", "main"),
                    "new_event_ids": [], "frozen_context_from": source["trial_id"]}
            if getattr(backend, "handles_generate", False):
                out = await backend.execute_action(session, step, {"context": context_text})
                record = {**base, "status": "ok", "output": out, "error": None}
            elif generate is None:
                record = {**base, "status": "error", "output": {},
                          "error": {"code": "no_generation_target", "message": "configure a generation target"}}
            else:
                result = await generate(step["id"], memory_answer_messages(step["args"]["question"], context_text))
                ok = result.status == "success"
                record = {**base, "status": "ok" if ok else "error", "output": {"text": result.text} if ok else {},
                          "error": None if ok else result.error}
            records.append(record)
            if record["status"] == "ok":
                answers.append(record["output"].get("text"))
    finally:
        close = await backend.close(session)
    failed = [r for r in records if r.get("status") not in ("ok", "skipped")]
    return {"status": "error" if failed else "ok", "error": failed[0]["error"] if failed else None,
            "steps": records, "stores": source["stores"], "text": answers[-1] if answers else None,
            "event_ids": {}, "close": close}


_ATTEMPT_STATUS = {"success": AttemptStatus.SUCCESS, "provider_error": AttemptStatus.PROVIDER_ERROR,
                   "timeout": AttemptStatus.TIMEOUT, "invalid_output": AttemptStatus.INVALID_OUTPUT,
                   "unsupported": AttemptStatus.UNSUPPORTED, "cancelled": AttemptStatus.CANCELLED,
                   "indeterminate": AttemptStatus.INDETERMINATE, "skipped": AttemptStatus.CANCELLED}


def _finish_attempt(session, store, attempt: Attempt, result: TargetResult, index: int) -> None:
    """Write artifacts first, then every attempt field in one update (status last)."""
    request_hash = response_hash = None
    if result.raw_request is not None:
        request_hash = store_json(session, store, result.raw_request, kind="raw_request", entity_type="attempt",
                                  entity_id=attempt.id, role="request")
    if result.raw_response is not None:
        response_hash = store_json(session, store, result.raw_response, kind="raw_response", entity_type="attempt",
                                   entity_id=attempt.id, role="response")
    attempt.request_artifact = request_hash
    attempt.response_artifact = response_hash
    attempt.finished_at = utcnow()
    attempt.latency_ms = result.latency_ms
    attempt.request_id = result.request_id
    attempt.actual_model = result.actual_model
    attempt.usage = result.usage or {}
    attempt.cost = result.cost or {}
    attempt.error = result.error
    attempt.retry_reason = f"transport retry {index} after a retryable failure" if index > 0 else None
    attempt.status = _ATTEMPT_STATUS.get(result.status, AttemptStatus.PROVIDER_ERROR)
    session.flush()


def _finish(app: AppContext, prep: dict[str, Any], outcome: dict[str, Any]) -> None:
    store = app.store
    with app.db.write() as session:
        trial = session.get(Trial, prep["trial_id"])
        run = session.get(Run, prep["run_id"])
        if trial.status in TRIAL_TERMINAL:
            return
        primary = session.get(Attempt, prep["attempt_id"])
        cost_items, last_attempt_id, primary_used = [], primary.id, False
        next_index: dict[str, int] = {}
        for stage, index, result in outcome["attempts"]:
            if prep["stage"] == "target" and stage == "target" and not primary_used:
                attempt, primary_used = primary, True
            else:
                if stage not in next_index:
                    next_index[stage] = session.scalar(select(func.count()).select_from(Attempt).where(
                        Attempt.trial_id == trial.id, Attempt.stage == stage))
                attempt = Attempt(trial_id=trial.id, stage=stage, attempt_index=next_index[stage],
                                  status=AttemptStatus.RUNNING, requested_model=prep["config"].model)
                next_index[stage] += 1
                session.add(attempt)
                session.flush()
            _finish_attempt(session, store, attempt, result, index)
            cost_items.append(result.cost or {})
            last_attempt_id = attempt.id
            events.emit(session, run.id, "attempt.finished", attempt.id,
                        {"stage": stage, "attempt": index, "status": attempt.status, "retryable": result.retryable})
        if not primary_used:
            # Umbrella attempt (episode / agent execution) or an execution that produced no call result.
            primary.latency_ms = outcome.get("latency_ms")
            primary.error = outcome.get("error")
            primary.finished_at = utcnow()
            if prep["stage"] == "episode":
                primary.mutation_outcome_known = outcome.get("episode_status") != "indeterminate"
                primary.status = {"ok": AttemptStatus.SUCCESS, "indeterminate": AttemptStatus.INDETERMINATE}.get(
                    outcome.get("episode_status"), AttemptStatus.PROVIDER_ERROR)
            else:
                primary.status = _ATTEMPT_STATUS.get(str(outcome["status"]), AttemptStatus.PROVIDER_ERROR)
            session.flush()
        output = outcome.get("output")
        evidence = output if output is not None else outcome.get("partial_output")
        if evidence is not None:
            trial.output_artifacts = [store_json(session, store, evidence, kind="trial_output",
                                                 entity_type="trial", entity_id=trial.id, role="output")]
            trial.state_artifacts = [store_json(session, store, snap, kind="memory_state", entity_type="trial",
                                                entity_id=trial.id, role=f"state:{name}")
                                     for name, snap in (evidence.get("stores") or {}).items() if snap is not None]
        if outcome.get("steps"):
            store_json(session, store, outcome["steps"], kind="episode_trace", entity_type="trial",
                       entity_id=trial.id, role="trace")
        trial.output = redact(output)[0] if output is not None else None
        trial.steps = redact(outcome.get("steps") or [])[0]
        trial.latency_ms = outcome.get("latency_ms")
        trial.selected_attempt_id = last_attempt_id
        usage = dict(run.usage or {})
        usage["target_calls"] = usage.get("target_calls", 0) + len(outcome["attempts"])
        known = dict(usage.get("cost_known", {}))
        for item in cost_items:
            if item.get("amount") is not None and item.get("currency"):
                known[item["currency"]] = known.get(item["currency"], 0.0) + item["amount"]
            else:
                usage["cost_unknown_calls"] = usage.get("cost_unknown_calls", 0) + 1
        usage["cost_known"] = known
        run.usage = usage
        if evidence is not None:
            events.emit(session, run.id, "artifact.created", trial.id, {"kind": "trial_output"})
        terminate(session, trial, outcome["status"], outcome.get("error"), prep["grading_run_id"])
