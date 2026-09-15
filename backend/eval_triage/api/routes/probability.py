"""Probability Lab: events, probability quality, bin members and calibration versions; job polling."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from eval_triage.analysis import probability as prob
from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope
from eval_triage.api.errors import not_found, validation_error
from eval_triage.db.models import CalibrationVersion, Job, Project
from eval_triage.db.types import iso
from eval_triage.domain.enums import JobKind
from eval_triage.execution import jobs
from eval_triage.statistics import calibration as cal

router = APIRouter(tags=["probability"])


def _calibration(row: CalibrationVersion) -> dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "logical_id": row.logical_id, "version": row.version,
            "event_definition": row.event_definition, "features": row.features, "fit_method": row.fit_method,
            "source": row.source, "split_hashes": row.split_hashes, "parameters": row.parameters,
            "validation": row.validation, "hash": row.hash, "created_at": iso(row.created_at)}


@router.get("/probability/events")
def events(project_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        return envelope(prob.list_events(session, project_id))


@router.get("/probability/quality")
def quality(project_id: str, event_definition: str, ctx: AppContext = Depends(get_ctx), split: str | None = None,
            calibration_id: str | None = None, bins: int = Query(default=10, ge=2, le=50),
            threshold: float = Query(default=0.5, ge=0, le=1)) -> dict:
    with ctx.db.read() as session:
        calibration = None
        if calibration_id:
            row = session.get(CalibrationVersion, calibration_id)
            if row is None or row.project_id != project_id:
                raise not_found("calibration", calibration_id)
            if row.event_definition != event_definition:
                raise validation_error("the calibration was fitted for a different event")
            calibration = {"features": row.features, "parameters": row.parameters}
        records = prob.load_records(session, project_id, event_definition, split)
        result = prob.quality(records, calibration=calibration, bins=bins, threshold=threshold)
        score_types = sorted({r.score_type for r in records})
        return envelope({**result, "event_definition": event_definition, "split": split,
                         "score_types": score_types, "methods": sorted({r.method for r in records}),
                         "calibration_id": calibration_id, "is_demo": any(r.is_demo for r in records)})


@router.get("/probability/records")
def records(project_id: str, event_definition: str, ctx: AppContext = Depends(get_ctx), split: str | None = None,
            external_ids: str | None = None, limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    with ctx.db.read() as session:
        rows = prob.load_records(session, project_id, event_definition, split)
        if external_ids:
            wanted = set(external_ids.split(","))
            rows = [r for r in rows if r.external_id in wanted]
        return envelope([{"id": r.id, "external_id": r.external_id, "cluster_id": r.cluster_id, "split": r.split,
                          "probability": r.probability, "raw_feature": r.raw_feature, "label": r.label,
                          "label_source": r.label_source, "method": r.method, "source_version": r.source_version,
                          "score_type": r.score_type, "predicted_at": iso(r.predicted_at),
                          "labeled_at": iso(r.labeled_at), "trial_id": r.trial_id, "case_id": r.case_id,
                          "unavailable_reason": r.unavailable_reason} for r in rows[:limit]], total=len(rows))


@router.get("/calibrations")
def list_calibrations(project_id: str, ctx: AppContext = Depends(get_ctx), event_definition: str | None = None) -> dict:
    with ctx.db.read() as session:
        query = select(CalibrationVersion).where(CalibrationVersion.project_id == project_id)
        if event_definition:
            query = query.where(CalibrationVersion.event_definition == event_definition)
        return envelope([_calibration(r) for r in session.scalars(query.order_by(
            CalibrationVersion.created_at.desc()))])


@router.get("/calibrations/{calibration_id}")
def get_calibration(calibration_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(CalibrationVersion, calibration_id)
        if row is None:
            raise not_found("calibration", calibration_id)
        return envelope(_calibration(row))


class FitRequest(BaseModel):
    project_id: str
    event_definition: str = Field(min_length=1)
    method: Literal["logistic", "isotonic"] = "isotonic"
    fit_split: str = "calibration"
    eval_split: str = "test"
    feature: Literal["raw_feature", "probability"] = "raw_feature"
    feature_transform: Literal["identity", "logit"] = "identity"
    min_clusters: int = Field(default=cal.MIN_CLUSTERS, ge=2)


@router.post("/calibrations", status_code=202)
def fit(body: FitRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    if body.fit_split in cal.FORBIDDEN_FIT_SPLITS:
        raise validation_error("calibration cannot be fitted on the held-out test split",
                               [{"loc": ["fit_split"], "msg": "choose the calibration split"}])
    if body.fit_split == body.eval_split:
        raise validation_error("the evaluation split must differ from the fitting split")
    with ctx.db.write() as session:
        if session.get(Project, body.project_id) is None:
            raise not_found("project", body.project_id)
        job = jobs.enqueue(session, JobKind.CALIBRATION_FIT, body.model_dump(), concurrency_key="calibration",
                           concurrency_limit=1, max_attempts=1)
        return envelope({"job_id": job.id, "status": job.status})


class ImportCalibration(BaseModel):
    project_id: str
    event_definition: str
    method: Literal["logistic", "isotonic"]
    features: dict[str, Any]
    parameters: dict[str, Any]


@router.post("/calibrations/import", status_code=201)
def import_mapping(body: ImportCalibration, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        with ctx.db.write() as session:
            row = prob.import_calibration(session, body.project_id, event_definition=body.event_definition,
                                          method=body.method, features=body.features, parameters=body.parameters)
            return envelope(_calibration(row))
    except cal.CalibrationError as exc:
        raise validation_error(str(exc)) from exc


@router.get("/jobs/{job_id}")
def get_job(job_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(Job, job_id)
        if row is None:
            raise not_found("job", job_id)
        return envelope({"id": row.id, "kind": row.kind, "status": row.status, "attempts": row.attempts,
                         "result": row.result, "error": {k: v for k, v in (row.error or {}).items()
                                                         if k != "traceback"} or None,
                         "created_at": iso(row.created_at), "finished_at": iso(row.finished_at)})
