"""Shared integration helpers: definitions, runs and in-process job draining."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from eval_triage.db.models import Grade, GraderVersion, Trial, TrialOutcome
from eval_triage.db.repositories import create_project, create_target_config, import_document
from eval_triage.domain.fixtures import FIXTURES_DIR, load_source
from eval_triage.execution.runs import RunRequest, create_run
from eval_triage.worker import drain


def make_project(ctx, name: str = "Test project") -> str:
    with ctx.db.write() as session:
        return create_project(session, name).id


def import_fixture(ctx, project_id: str, source: str, include: list[str] | None = None,
                   judge: str | None = None) -> dict[str, Any]:
    path = FIXTURES_DIR / source
    with ctx.db.write() as session:
        judges = {}
        if judge:
            judges["judge"] = create_target_config(session, project_id, name="judge", adapter="demo",
                                                   model="demo-judge").id
        result = import_document(session, project_id, load_source(path, include_cases=include), judges=judges)
        return {"scenario_id": result["scenario"].id, "dataset_id": result["dataset"].id,
                "grader_ids": [g.id for g in result["graders"]]}


def demo_target(ctx, project_id: str, name: str, **parameters) -> str:
    with ctx.db.write() as session:
        return create_target_config(session, project_id, name=name, adapter="demo", model=f"demo-{name}",
                                    parameters=parameters).id


def start_run(ctx, project_id: str, suite: dict[str, Any], candidates: dict[str, str], repeats: int = 2,
              key: str | None = None, **execution) -> str:
    request = RunRequest(project_id=project_id, scenario_id=suite["scenario_id"], dataset_id=suite["dataset_id"],
                         candidates=[{"key": k, "target_config_id": v} for k, v in candidates.items()],
                         execution={"repeats": repeats, **execution})
    _, response = create_run(ctx.db, ctx.settings, request, key or str(uuid.uuid4()))
    return response["data"]["id"]


def run_all(ctx, seconds: float = 60.0) -> None:
    drain(ctx, max_seconds=seconds)


def outcomes(ctx, run_id: str, grading_run_id: str | None = None) -> dict[tuple[str, str], list[str]]:
    """(external_id, candidate) -> outcomes ordered by repeat."""
    from eval_triage.db.models import Case, GradingRun

    with ctx.db.read() as session:
        if grading_run_id is None:
            grading_run_id = session.scalars(select(GradingRun.id).where(GradingRun.run_id == run_id,
                                                                         GradingRun.source == "initial")).first()
        rows = session.execute(select(Trial, Case, TrialOutcome).join(Case, Case.id == Trial.case_id)
                               .join(TrialOutcome, TrialOutcome.trial_id == Trial.id)
                               .where(Trial.run_id == run_id, TrialOutcome.grading_run_id == grading_run_id)
                               .order_by(Trial.repeat_index)).all()
    result: dict[tuple[str, str], list[str]] = {}
    for trial, case, outcome in rows:
        result.setdefault((case.external_id, trial.candidate_key), []).append(outcome.outcome)
    return result


def grades_by_grader(ctx, trial_id: str) -> dict[str, list[str]]:
    with ctx.db.read() as session:
        rows = session.execute(select(Grade, GraderVersion).join(GraderVersion, GraderVersion.id == Grade.grader_id)
                               .where(Grade.trial_id == trial_id)).all()
    out: dict[str, list[str]] = {}
    for grade, grader in rows:
        out.setdefault(grader.name, []).append(grade.verdict)
    return out
