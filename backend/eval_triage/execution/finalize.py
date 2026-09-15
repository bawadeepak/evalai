"""Run and grading-run completion.

A run is ``completed`` when every planned slot is terminal and graded — that
does not mean everything passed. ``completed_with_errors`` means some slots
ended in provider/timeout/indeterminate/skipped states or some grades errored.
A run with a cancel request ends ``cancelled`` and keeps its partial results.
"""

from __future__ import annotations

from sqlalchemy import func, select

from eval_triage.db.models import Grade, GradingRun, Job, Run, Trial
from eval_triage.db.types import utcnow
from eval_triage.domain.enums import RUN_TERMINAL, JobKind, JobStatus, RunStatus, TrialStatus
from eval_triage.execution import events

PROBLEM_STATUSES = {TrialStatus.PROVIDER_ERROR, TrialStatus.TIMEOUT, TrialStatus.UNSUPPORTED,
                    TrialStatus.INDETERMINATE, TrialStatus.SKIPPED}
OPEN_JOBS = (JobStatus.QUEUED, JobStatus.RUNNING)


def trial_counts(session, run_id: str) -> dict[str, int]:
    return dict(session.execute(select(Trial.status, func.count()).where(Trial.run_id == run_id)
                                .group_by(Trial.status)).all())


def maybe_finalize_grading(session, grading_run_id: str) -> bool:
    grading = session.get(GradingRun, grading_run_id)
    if grading is None or grading.status == "completed":
        return False
    open_jobs = session.scalar(select(func.count()).select_from(Job).where(
        Job.kind == JobKind.GRADE, Job.status.in_(OPEN_JOBS),
        Job.payload["grading_run_id"].as_string() == grading_run_id))
    trials_open = session.scalar(select(func.count()).select_from(Trial).where(
        Trial.run_id == grading.run_id, Trial.status.in_([TrialStatus.PENDING, TrialStatus.RUNNING])))
    if open_jobs or (grading.source == "initial" and trials_open):
        return False
    grading.status = "completed"
    grading.finished_at = utcnow()
    events.emit(session, grading.run_id, "grading.finished", grading_run_id, {"grading_run_id": grading_run_id})
    return True


def reconcile_failed_jobs(session) -> list[str]:
    """Close out work whose job failed permanently so runs can still finish.

    A trial whose execution job exhausted its attempts becomes ``provider_error``
    (its attempt history is kept) and is still graded, which records it as
    unresolved rather than silently dropping it. Failed grade jobs simply let the
    run finalise with reduced grade coverage.
    """
    from eval_triage.db.models import Attempt
    from eval_triage.execution.trial_runner import terminate

    touched: set[str] = set()
    failed = session.scalars(select(Job).where(Job.status == JobStatus.FAILED,
                                               Job.kind.in_([JobKind.TRIAL, JobKind.GRADE]))).all()
    for job in failed:
        if (job.result or {}).get("reconciled"):
            continue
        job.result = {**(job.result or {}), "reconciled": True}
        if job.kind == JobKind.TRIAL:
            trial = session.get(Trial, job.payload.get("trial_id"))
            if trial is not None and trial.status in (TrialStatus.PENDING, TrialStatus.RUNNING):
                for attempt in session.scalars(select(Attempt).where(Attempt.trial_id == trial.id,
                                                                     Attempt.status == "running")):
                    attempt.finished_at = utcnow()
                    attempt.error = {"code": "interrupted", "message": "execution job failed"}
                    attempt.status = "interrupted"
                session.flush()
                message = (job.error or {}).get("message", "execution job failed repeatedly")
                terminate(session, trial, TrialStatus.PROVIDER_ERROR,
                          {"code": "execution_failed", "message": message}, job.payload["grading_run_id"])
                touched.add(trial.run_id)
        elif job.run_id:
            touched.add(job.run_id)
    for run_id in touched:
        maybe_finalize(session, run_id)
    return sorted(touched)


def maybe_finalize(session, run_id: str) -> bool:
    run = session.get(Run, run_id)
    if run is None or run.status in RUN_TERMINAL:
        return False
    counts = trial_counts(session, run_id)
    if counts.get(TrialStatus.PENDING, 0) or counts.get(TrialStatus.RUNNING, 0):
        return False
    open_jobs = session.scalar(select(func.count()).select_from(Job).where(Job.run_id == run_id,
                                                                           Job.status.in_(OPEN_JOBS)))
    if open_jobs:
        return False
    grading_ids = [g.id for g in session.scalars(select(GradingRun).where(GradingRun.run_id == run_id))]
    for gid in grading_ids:
        maybe_finalize_grading(session, gid)
    grade_errors = session.scalar(select(func.count()).select_from(Grade).where(
        Grade.grading_run_id.in_(grading_ids), Grade.verdict == "error")) if grading_ids else 0
    if run.cancel_requested_at is not None:
        run.status = RunStatus.CANCELLED
        event = "run.cancelled"
    elif any(counts.get(s, 0) for s in PROBLEM_STATUSES) or grade_errors:
        run.status = RunStatus.COMPLETED_WITH_ERRORS
        event = "run.finished"
    else:
        run.status = RunStatus.COMPLETED
        event = "run.finished"
    run.finished_at = utcnow()
    events.emit(session, run_id, event, run_id, {"status": run.status, "counts": counts})
    return True
