"""Runs, trials, events (SSE), grading runs and artifacts."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from eval_triage.api import serializers as ser
from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope, paginate
from eval_triage.api.errors import ApiError, not_found
from eval_triage.artifacts.store import ArtifactError, validate_hash
from eval_triage.db.models import Artifact, Case, GradingRun, Run, Trial, TrialOutcome
from eval_triage.domain.enums import RUN_TERMINAL
from eval_triage.execution.events import events_after
from eval_triage.execution.grading import create_grading_run
from eval_triage.execution.runs import RunRequest, RunValidationError, cancel_run, create_run, validate_run

router = APIRouter(tags=["runs"])


def _validation_error(exc: RunValidationError) -> ApiError:
    code = {409: "conflict", 404: "not_found"}.get(exc.status, "validation_error")
    return ApiError(exc.status, code, str(exc) or "run validation failed", {"errors": exc.errors})


@router.post("/runs/validate")
def validate(body: RunRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        with ctx.db.read() as session:
            result = validate_run(session, ctx.settings, body)
    except RunValidationError as exc:
        raise _validation_error(exc) from exc
    return envelope({"ok": True, "plan": result["plan"], "warnings": result["warnings"],
                     "manifest": result["manifest"], "manifest_hash": result["manifest_hash"],
                     "is_demo": result["is_demo"]})


@router.post("/runs", status_code=201)
def create(body: RunRequest, ctx: AppContext = Depends(get_ctx),
           idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200)):
    try:
        status, response = create_run(ctx.db, ctx.settings, body, idempotency_key)
    except RunValidationError as exc:
        raise _validation_error(exc) from exc
    return JSONResponse(response, status_code=status)


@router.get("/runs")
def list_runs(ctx: AppContext = Depends(get_ctx), project_id: str | None = None, status: str | None = None,
              limit: int | None = None, cursor: str | None = None) -> dict:
    with ctx.db.read() as session:
        stmt = select(Run)
        if project_id:
            stmt = stmt.where(Run.project_id == project_id)
        if status:
            stmt = stmt.where(Run.status == status)
        items, meta = paginate(session, stmt, Run.created_at, Run.id, limit, cursor,
                               serialize=lambda r: ser.run(session, r))
    return envelope(items, **meta)


def _run_or_404(session, run_id: str) -> Run:
    row = session.get(Run, run_id)
    if row is None:
        raise not_found("run", run_id)
    return row


@router.get("/runs/{run_id}")
def get_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        return envelope(ser.run(session, _run_or_404(session, run_id), full=True))


@router.get("/runs/{run_id}/trials")
def run_trials(run_id: str, ctx: AppContext = Depends(get_ctx), grading_run_id: str | None = None,
               limit: int = Query(default=200, ge=1, le=2000), offset: int = Query(default=0, ge=0)) -> dict:
    with ctx.db.read() as session:
        run_row = _run_or_404(session, run_id)
        if grading_run_id is None:
            latest = session.scalars(select(GradingRun).where(GradingRun.run_id == run_id)
                                     .order_by(GradingRun.created_at.desc())).first()
            grading_run_id = latest.id if latest else None
        rows = session.execute(select(Trial, Case).join(Case, Case.id == Trial.case_id)
                               .where(Trial.run_id == run_id)
                               .order_by(Case.ordinal, Trial.candidate_key, Trial.repeat_index)
                               .offset(offset).limit(limit)).all()
        outcomes = {o.trial_id: o for o in session.scalars(select(TrialOutcome).where(
            TrialOutcome.grading_run_id == grading_run_id))} if grading_run_id else {}
        items = [ser.trial_brief(t, c, outcomes.get(t.id)) for t, c in rows]
        return envelope(items, grading_run_id=grading_run_id, total=run_row.planned_trial_count, offset=offset,
                        limit=limit)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    row = cancel_run(ctx.db, run_id)
    if row is None:
        raise not_found("run", run_id)
    with ctx.db.read() as session:
        return envelope(ser.run(session, session.get(Run, run_id)))


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, ctx: AppContext = Depends(get_ctx),
                     after: int = Query(default=0, ge=0)):
    with ctx.db.read() as session:
        _run_or_404(session, run_id)
    header = request.headers.get("last-event-id")
    last = int(header) if header and header.isdigit() else after
    poll = max(ctx.settings.worker_poll_seconds, 0.05)

    def fetch(since: int):
        with ctx.db.read() as session:
            rows = events_after(session, run_id, since)
            status = session.get(Run, run_id).status
            return [(e.seq, e.type, {"id": e.seq, "type": e.type, "timestamp": e.timestamp.isoformat(),
                                     "run_id": e.run_id, "entity_id": e.entity_id, "payload": e.payload})
                    for e in rows], status

    async def stream():
        nonlocal last
        idle_after_terminal = 0
        while True:
            if await request.is_disconnected():
                return
            batch, status = await asyncio.to_thread(fetch, last)
            for seq, type_, data in batch:
                last = seq
                yield {"id": str(seq), "event": type_, "data": json.dumps(data)}
            if status in RUN_TERMINAL and not batch:
                idle_after_terminal += 1
                if idle_after_terminal >= 2:
                    yield {"event": "stream.end", "data": json.dumps({"status": status,
                                                                      "note": "refetch the run snapshot"})}
                    return
            await asyncio.sleep(poll)

    return EventSourceResponse(stream(), ping=15)


@router.get("/trials/{trial_id}")
def get_trial(trial_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(Trial, trial_id)
        if row is None:
            raise not_found("trial", trial_id)
        return envelope(ser.trial_detail(session, row))


class GradingRunRequest(BaseModel):
    run_id: str
    grader_ids: list[str] = Field(min_length=1)


@router.post("/grading-runs", status_code=201)
def regrade(body: GradingRunRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        grading = create_grading_run(ctx.db, body.run_id, body.grader_ids)
    except KeyError as exc:
        raise not_found("run", body.run_id) from exc
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    return envelope({"id": grading.id, "run_id": grading.run_id, "status": grading.status,
                     "grader_ids": grading.grader_ids, "note": "regrading reuses stored outputs; no target calls"})


@router.get("/grading-runs")
def list_grading(run_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        rows = session.scalars(select(GradingRun).where(GradingRun.run_id == run_id)
                               .order_by(GradingRun.created_at)).all()
        return envelope([{"id": g.id, "run_id": g.run_id, "source": g.source, "status": g.status,
                          "grader_ids": g.grader_ids, "grader_hashes": g.grader_hashes} for g in rows])


@router.get("/artifacts/{content_hash}")
def get_artifact(content_hash: str, ctx: AppContext = Depends(get_ctx)):
    try:
        validate_hash(content_hash)
    except ArtifactError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    with ctx.db.read() as session:
        row = session.get(Artifact, content_hash)
    if row is None:
        raise not_found("artifact", content_hash)
    try:
        data = ctx.store.read_bytes(content_hash)
    except (FileNotFoundError, ArtifactError) as exc:
        raise ApiError(410, "artifact_unavailable", f"artifact file is missing or corrupt: {exc}") from exc
    media = row.media_type if row.media_type in ("application/json", "text/plain") else "application/octet-stream"
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f'inline; filename="{content_hash}"', "Cache-Control": "private, max-age=3600"})
