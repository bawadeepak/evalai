"""Run summaries, triage queue, linked "more trials" runs, comparisons and the statistics query."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from eval_triage.analysis import comparison as cmp
from eval_triage.analysis.summaries import case_candidate_summary, load_rows, run_summary, triage_queue
from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope
from eval_triage.api.errors import ApiError, not_found, validation_error
from eval_triage.db.models import Case, Comparison, GradingRun, ReleasePolicy, Run
from eval_triage.db.types import iso
from eval_triage.execution.runs import RunRequest, RunValidationError, create_run
from eval_triage.statistics.registry import METRICS, definition

router = APIRouter(tags=["analysis"])
Representation = Literal["raw", "json", "semantic"]


def _run(session, run_id: str) -> Run:
    row = session.get(Run, run_id)
    if row is None:
        raise not_found("run", run_id)
    return row


@router.get("/runs/{run_id}/summary")
def summary(run_id: str, ctx: AppContext = Depends(get_ctx), grading_run_id: str | None = None,
            representation: Representation = "raw") -> dict:
    with ctx.db.read() as session:
        _run(session, run_id)
        return envelope(run_summary(session, run_id, grading_run_id, representation))


@router.get("/runs/{run_id}/triage")
def triage(run_id: str, ctx: AppContext = Depends(get_ctx), grading_run_id: str | None = None,
           representation: Representation = "raw", severity: str | None = None, candidate: str | None = None,
           flaky: bool | None = None, stable_wrong: bool | None = None, changed: bool | None = None,
           grading_error: bool | None = None, provider_error: bool | None = None,
           review: Literal["confirmed", "unreviewed"] | None = None, slice: str | None = None) -> dict:
    filters = {"severity": severity, "candidate": candidate, "flaky": flaky, "stable_wrong": stable_wrong,
               "changed": changed, "grading_error": grading_error, "provider_error": provider_error,
               "review": review, "slice": slice}
    with ctx.db.read() as session:
        _run(session, run_id)
        return envelope(triage_queue(session, run_id, grading_run_id, filters, representation))


class MoreTrials(BaseModel):
    case_ids: list[str] = Field(min_length=1)
    repeats: int = Field(default=5, ge=1, le=200)


@router.post("/runs/{run_id}/more-trials", status_code=201)
def more_trials(run_id: str, body: MoreTrials, ctx: AppContext = Depends(get_ctx),
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    """A linked run with fresh repeats for selected cases; the original run is unchanged."""
    with ctx.db.read() as session:
        parent = _run(session, run_id)
        initial = session.scalars(select(GradingRun).where(GradingRun.run_id == run_id,
                                                           GradingRun.source == "initial")).first()
        request = RunRequest(
            project_id=parent.project_id, scenario_id=parent.scenario_id, dataset_id=parent.dataset_id,
            name=f"More trials · {parent.name}",
            candidates=[{"key": c["key"], "target_config_id": c["config"]["id"]}
                        for c in sorted(parent.manifest["candidates"], key=lambda c: c["ordinal"])],
            grader_ids=initial.grader_ids if initial else None,
            execution={**parent.manifest["execution"], "repeats": body.repeats},
            limits=parent.manifest["limits"], case_ids=body.case_ids, parent_run_id=parent.id)
    try:
        status, response = create_run(ctx.db, ctx.settings, request, idempotency_key or str(uuid.uuid4()))
    except RunValidationError as exc:
        raise ApiError(exc.status, "validation_error", str(exc), {"errors": exc.errors}) from exc
    response["data"]["sampling_note"] = ("Fresh repeats in a linked run. Combined analysis must state that "
                                         "these trials were requested after inspecting the original results.")
    return JSONResponse(response, status_code=status)


class ComparisonRequest(BaseModel):
    project_id: str
    baseline_run_id: str
    baseline_key: str
    candidate_run_id: str
    candidate_key: str
    baseline_grading_run_id: str | None = None
    candidate_grading_run_id: str | None = None
    policy_id: str | None = None


def _policy(session, body: ComparisonRequest) -> dict | None:
    if not body.policy_id:
        return None
    row = session.get(ReleasePolicy, body.policy_id)
    if row is None or row.project_id != body.project_id:
        raise not_found("release policy", body.policy_id)
    return row.policy


@router.post("/comparisons/validate")
def validate_comparison(body: ComparisonRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        for run_id in (body.baseline_run_id, body.candidate_run_id):
            if _run(session, run_id).project_id != body.project_id:
                raise not_found("run", run_id)
        try:
            result = cmp.evaluate(session, baseline_run_id=body.baseline_run_id, baseline_key=body.baseline_key,
                                  candidate_run_id=body.candidate_run_id, candidate_key=body.candidate_key,
                                  baseline_grading_run_id=body.baseline_grading_run_id,
                                  candidate_grading_run_id=body.candidate_grading_run_id,
                                  policy=_policy(session, body))
        except ValueError as exc:
            raise validation_error(str(exc)) from exc
        return envelope({**result, "preview": True})


def _comparison(row: Comparison) -> dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "baseline_run_id": row.baseline_run_id,
            "candidate_run_id": row.candidate_run_id, "baseline_key": row.baseline_candidate_key,
            "candidate_key": row.candidate_candidate_key, "grading_run_ids": row.grading_run_ids,
            "policy_id": row.policy_id, "compatibility": row.compatibility, "pairing": row.pairing,
            "method": row.method, "metrics": row.metrics, "exclusions": row.exclusions,
            "case_changes": row.case_changes, "decision": row.decision, "created_at": iso(row.created_at)}


@router.post("/comparisons", status_code=201)
def create_comparison(body: ComparisonRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.write() as session:
        try:
            row = cmp.create_comparison(session, body.project_id, baseline_run_id=body.baseline_run_id,
                                        baseline_key=body.baseline_key, candidate_run_id=body.candidate_run_id,
                                        candidate_key=body.candidate_key,
                                        baseline_grading_run_id=body.baseline_grading_run_id,
                                        candidate_grading_run_id=body.candidate_grading_run_id,
                                        policy_id=body.policy_id)
        except KeyError as exc:
            raise not_found("run or policy", str(exc)) from exc
        except ValueError as exc:
            raise validation_error(str(exc)) from exc
        return envelope(_comparison(row))


@router.get("/comparisons")
def list_comparisons(project_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        rows = session.scalars(select(Comparison).where(Comparison.project_id == project_id)
                               .order_by(Comparison.created_at.desc())).all()
        return envelope([_comparison(r) for r in rows])


@router.get("/comparisons/{comparison_id}")
def get_comparison(comparison_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(Comparison, comparison_id)
        if row is None:
            raise not_found("comparison", comparison_id)
        return envelope(_comparison(row))


@router.get("/comparisons/{comparison_id}/export")
def export_comparison(comparison_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    """Decision evidence: the comparison, both manifests' hashes and links to every contributing trial."""
    with ctx.db.read() as session:
        row = session.get(Comparison, comparison_id)
        if row is None:
            raise not_found("comparison", comparison_id)
        runs = {rid: session.get(Run, rid) for rid in {row.baseline_run_id, row.candidate_run_id}}
        return envelope({
            "comparison": _comparison(row),
            "manifests": {rid: {"manifest_hash": r.manifest_hash, "status": r.status, "is_demo": r.is_demo,
                                "dataset": r.manifest["dataset"], "scenario": r.manifest["scenario"]}
                          for rid, r in runs.items()},
            "evidence_links": {"trials": "/api/v1/trials/{trial_id}",
                               "artifacts": "/api/v1/artifacts/{content_hash}"},
        })


class StatisticsQuery(BaseModel):
    run_id: str
    metric: str
    group_by: Literal["candidate", "case", "slice"] = "candidate"
    slice_key: str | None = None
    grading_run_id: str | None = None
    representation: Representation = "raw"
    k: int = Field(default=1, ge=1, le=100)
    combine_with: list[str] = Field(default_factory=list)


SUPPORTED = {"observed_pass_rate": "pass_rate", "modal_agreement": "modal_agreement",
             "pairwise_agreement": "pairwise_agreement", "output_entropy": "entropy", "latency_p50": "latency_p50",
             "beta_posterior": "posterior", "pass_at_k": "pass_at_{k}", "pass_all_k": "pass_all_{k}"}


@router.post("/statistics/query")
def statistics_query(body: StatisticsQuery, ctx: AppContext = Depends(get_ctx)) -> dict:
    if body.metric not in METRICS:
        raise validation_error(f"unknown metric {body.metric!r}", {"known": sorted(METRICS)})
    base_type = definition(body.metric).score_type
    mixed = [m for m in body.combine_with if m not in METRICS or definition(m).score_type != base_type]
    if mixed:
        raise validation_error(f"cannot combine {body.metric} ({base_type.value}) with {mixed}: incompatible "
                               "score types are never averaged or plotted on one axis")
    if body.metric not in SUPPORTED:
        raise validation_error(f"{body.metric} is not available through this query", {"supported": sorted(SUPPORTED)})
    key = SUPPORTED[body.metric].format(k=body.k)
    with ctx.db.read() as session:
        run, grading_id, rows = load_rows(session, body.run_id, body.grading_run_id)
        groups: dict[str, list] = {}
        for r in rows:
            if body.group_by == "candidate":
                label = r.candidate_key
            elif body.group_by == "case":
                label = f"{r.external_id} · {r.candidate_key}"
            else:
                if not body.slice_key:
                    raise validation_error("group_by=slice needs slice_key")
                if body.slice_key not in r.tags:
                    continue
                label = f"{body.slice_key}={r.tags[body.slice_key]} · {r.candidate_key}"
            groups.setdefault(label, []).append(r)
        values = []
        for label, group in groups.items():
            summary_ = case_candidate_summary(group, body.representation, k_values=(body.k,))
            value = summary_["metrics"].get(key) or {"name": body.metric, "value": None,
                                                     "unavailable_reason": f"k={body.k} exceeds graded repeats"}
            value["contributing_case_ids"] = sorted({r.case_id for r in group})
            values.append({"group": label, "metric": value})
        external = {c.id: c.external_id for c in session.scalars(select(Case).where(
            Case.id.in_({r.case_id for r in rows})))}
        return envelope({"run_id": run.id, "grading_run_id": grading_id, "definition": definition(body.metric).to_dict(),
                         "group_by": body.group_by, "values": values, "case_external_ids": external,
                         "note": ("Groups pool repeats of several cases; case-level summaries remain the unit for "
                                  "inference." if body.group_by != "case" else "")})
