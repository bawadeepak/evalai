"""Grade stored trial outputs. Grading never calls the target and never mutates state.

Deterministic graders run first; model and pairwise judges follow. The pass
rule is applied per trial and stored as an immutable ``TrialOutcome``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import func, select

from eval_triage.adapters.base import TargetConfig, TargetRequest
from eval_triage.adapters.registry import get_adapter
from eval_triage.api.context import AppContext
from eval_triage.db.models import (
    Case,
    DatasetVersion,
    Grade,
    GraderVersion,
    GradingRun,
    Run,
    ScenarioVersion,
    TargetConfigVersion,
    Trial,
    TrialOutcome,
)
from eval_triage.db.repositories import grader_spec
from eval_triage.domain.enums import TRIAL_TERMINAL, GraderKind, JobKind, TrialStatus
from eval_triage.execution import events, jobs
from eval_triage.execution.common import Defer
from eval_triage.execution.finalize import maybe_finalize, maybe_finalize_grading
from eval_triage.graders.base import GradeResult, GradingContext
from eval_triage.graders.judge import JudgeReply
from eval_triage.graders.runner import grade, trial_outcome
from eval_triage.security.redaction import redact


def _load(app: AppContext, grading_run_id: str, trial_id: str) -> dict[str, Any] | None:
    with app.db.read() as session:
        grading = session.get(GradingRun, grading_run_id)
        trial = session.get(Trial, trial_id)
        if grading is None or trial is None:
            return None
        run = session.get(Run, trial.run_id)
        scenario = session.get(ScenarioVersion, run.scenario_id)
        dataset = session.get(DatasetVersion, run.dataset_id)
        case = session.get(Case, trial.case_id)
        graders = [session.get(GraderVersion, gid) for gid in grading.grader_ids]
        done = set(session.scalars(select(Grade.grader_id).where(Grade.grading_run_id == grading_run_id,
                                                                  Grade.trial_id == trial_id)))
        candidates = {c["key"]: c for c in run.manifest["candidates"]}
        baseline_key = min(candidates.values(), key=lambda c: c["ordinal"])["key"]
        peer = None
        if any(g.kind == GraderKind.PAIRWISE for g in graders) and trial.candidate_key != baseline_key:
            peer = session.scalars(select(Trial).where(Trial.run_id == run.id, Trial.case_id == trial.case_id,
                                                       Trial.candidate_key == baseline_key,
                                                       Trial.repeat_index == trial.repeat_index)).first()
            if peer is not None and peer.status not in TRIAL_TERMINAL:
                return {"defer": "waiting for the paired baseline trial"}
        related = {}
        base_ids = {(case.expected or {}).get("invariance_base")} - {None}
        if base_ids:
            for other in session.scalars(select(Trial).join(Case).where(
                    Trial.run_id == run.id, Trial.candidate_key == trial.candidate_key,
                    Trial.repeat_index == trial.repeat_index, Case.external_id.in_(base_ids))):
                related[session.get(Case, other.case_id).external_id] = other.output
        judge_rows = {g.judge_config_id: session.get(TargetConfigVersion, g.judge_config_id)
                      for g in graders if g.judge_config_id}
        judge_calls_used = sum(len(g.judge_attempts or []) for g in session.scalars(
            select(Grade).join(Trial).where(Trial.run_id == run.id)))
        return {
            "grading": grading, "trial": trial, "run": run, "scenario": scenario.definition,
            "case": {"id": case.id, "external_id": case.external_id, "input": case.input, "episode": case.episode,
                     "expected": case.expected, "alternatives": case.alternatives, "severity": case.severity},
            "graders": [g for g in graders if g.id not in done], "pass_rule": dataset.pass_rule,
            "peer": peer, "related": related, "judges": {k: TargetConfig.from_row(v) for k, v in judge_rows.items()},
            "profile": candidates[trial.candidate_key]["config"]["parameters"].get("profile", "baseline"),
            "judge_calls_used": judge_calls_used, "max_judge_calls": run.manifest["limits"].get("max_judge_calls"),
            "already_graded": done,
        }


def _provider_judge(config: TargetConfig, loop: asyncio.AbstractEventLoop, context_meta: dict[str, Any]):
    adapter = get_adapter(config.adapter)

    def call(messages, meta) -> JudgeReply:
        async def run() -> JudgeReply:
            from eval_triage.adapters.base import RunContext

            ctx = RunContext(run_id=context_meta["run_id"], trial_id=context_meta["trial_id"], candidate_key="judge",
                             repeat_index=0, case_external_id=context_meta["case"], attempt_index=meta["attempt"],
                             data_dir=context_meta["data_dir"])
            session = await adapter.prepare(config, ctx)
            try:
                result = await adapter.execute(TargetRequest(messages=messages, parameters=dict(config.parameters),
                                                             stage="judge", metadata={"stage": "judge"}), session)
            finally:
                await adapter.close(session)
            if result.status != "success":
                return JudgeReply(error=result.error or {"message": result.status}, model=result.actual_model,
                                  request_id=result.request_id)
            return JudgeReply(text=result.text, model=result.actual_model, request_id=result.request_id,
                              usage=result.usage, cost=result.cost, latency_ms=result.latency_ms)

        return asyncio.run_coroutine_threadsafe(run(), loop).result(timeout=300)

    return call


def _grade_all(data: dict[str, Any], app: AppContext, loop) -> list[tuple[GraderVersion, GradeResult]]:
    trial = data["trial"]
    results: list[tuple[GraderVersion, GradeResult]] = []
    ordered = sorted(data["graders"], key=lambda g: g.kind in (GraderKind.MODEL, GraderKind.PAIRWISE))
    deterministic: dict[str, dict] = {}
    judge_calls = data["judge_calls_used"]
    for row in ordered:
        spec = grader_spec(row)
        ctx = GradingContext(scenario=data["scenario"], case=data["case"], grader=spec, trial_status=trial.status,
                             output=trial.output, steps=trial.steps or [], trial_id=trial.id,
                             candidate_key=trial.candidate_key, repeat_index=trial.repeat_index,
                             related_outputs=data["related"],
                             peer_output=data["peer"].output if data["peer"] is not None else None,
                             peer_trial_id=data["peer"].id if data["peer"] is not None else None)
        judge = None
        if row.kind in (GraderKind.MODEL, GraderKind.PAIRWISE) and row.judge_config_id:
            if data["max_judge_calls"] is not None and judge_calls >= data["max_judge_calls"]:
                results.append((row, GradeResult(verdict="unavailable", reason="judge call limit reached")))
                continue
            config = data["judges"][row.judge_config_id]
            if config.adapter == "demo":
                from eval_triage.adapters.demo import demo_judge

                outcome = trial_outcome(deterministic, data["pass_rule"])["outcome"]
                judge = demo_judge(data["case"]["external_id"], data["profile"], trial.repeat_index, outcome)
            else:
                judge = _provider_judge(config, loop, {"run_id": trial.run_id, "trial_id": trial.id,
                                                       "case": data["case"]["external_id"],
                                                       "data_dir": app.settings.data_dir})
        result = grade(ctx, judge)
        judge_calls += len(result.judge_attempts)
        if row.kind in (GraderKind.DETERMINISTIC, GraderKind.STRUCTURED):
            deterministic[row.name] = {"verdict": result.verdict, "reason": result.reason}
        results.append((row, result))
    return results


def _persist(app: AppContext, data: dict[str, Any], results) -> dict[str, Any]:
    trial = data["trial"]
    grading_id = data["grading"].id
    with app.db.write() as session:
        for row, result in results:
            exists = session.scalar(select(func.count()).select_from(Grade).where(
                Grade.grading_run_id == grading_id, Grade.trial_id == trial.id, Grade.grader_id == row.id))
            if exists:
                continue
            attempts = redact(result.judge_attempts)[0]
            session.add(Grade(grading_run_id=grading_id, trial_id=trial.id, grader_id=row.id,
                              verdict=str(result.verdict), reason=result.reason, metric=result.metric,
                              checks=[c.to_dict() for c in result.checks], evidence_refs=result.evidence_refs,
                              explanation=result.explanation, error=result.error, judge_attempts=attempts))
            events.emit(session, trial.run_id, "grade.created", trial.id,
                        {"grader": row.name, "verdict": str(result.verdict)})
        session.flush()
        grades = {g.grader_id: g for g in session.scalars(select(Grade).where(Grade.grading_run_id == grading_id,
                                                                              Grade.trial_id == trial.id))}
        names = {g.id: g.name for g in session.scalars(select(GraderVersion).where(
            GraderVersion.id.in_(list(grades))))}
        by_name = {names[gid]: {"verdict": g.verdict, "reason": g.reason} for gid, g in grades.items()}
        outcome = trial_outcome(by_name, data["pass_rule"])
        invariant_failures = sorted({name for g in grades.values() for c in g.checks
                                     for name, status in (c.get("invariants") or {}).items() if status == "fail"})
        if session.scalar(select(func.count()).select_from(TrialOutcome).where(
                TrialOutcome.grading_run_id == grading_id, TrialOutcome.trial_id == trial.id)) == 0:
            session.add(TrialOutcome(grading_run_id=grading_id, trial_id=trial.id, outcome=outcome["outcome"],
                                     reason=outcome["reason"], invariant_failures=invariant_failures))
        maybe_finalize_grading(session, grading_id)
        maybe_finalize(session, trial.run_id)
        return outcome


async def run_grade_job(app: AppContext, job, worker_id: str) -> dict[str, Any]:
    data = await asyncio.to_thread(_load, app, job.payload["grading_run_id"], job.payload["trial_id"])
    if data is None:
        return {"skipped": True}
    if "defer" in data:
        raise Defer(1.0, data["defer"])
    loop = asyncio.get_running_loop()
    results = await asyncio.to_thread(_grade_all, data, app, loop)
    outcome = await asyncio.to_thread(_persist, app, data, results)
    return {"outcome": outcome["outcome"]}


def create_grading_run(db, run_id: str, grader_ids: list[str]) -> GradingRun:
    """Regrade immutable outputs with (possibly new) grader versions. Makes zero target calls."""
    with db.write() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise KeyError(run_id)
        graders = [session.get(GraderVersion, gid) for gid in grader_ids]
        if any(g is None or g.project_id != run.project_id for g in graders):
            raise ValueError("every grader must exist in the run's project")
        grading = GradingRun(run_id=run_id, source="regrade", grader_ids=grader_ids,
                             grader_hashes=[g.hash for g in graders], status="queued")
        session.add(grading)
        session.flush()
        trials = session.scalars(select(Trial).where(Trial.run_id == run_id)).all()
        for trial in trials:
            if trial.status in TRIAL_TERMINAL:
                jobs.enqueue(session, JobKind.GRADE, {"trial_id": trial.id, "grading_run_id": grading.id},
                             run_id=None, concurrency_key="grading", concurrency_limit=4, priority=-1)
        events.emit(session, run_id, "grading.started", grading.id, {"grading_run_id": grading.id})
        if not any(t.status in TRIAL_TERMINAL for t in trials):
            grading.status = "completed"
        return grading


__all__ = ["run_grade_job", "create_grading_run", "TrialStatus"]
