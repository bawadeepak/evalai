"""Human review (append-only, supersedable) and promotion of confirmed failures into regression datasets."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from eval_triage.api import serializers as ser
from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope
from eval_triage.api.errors import ApiError, conflict, not_found, validation_error
from eval_triage.api.routes.definitions import _export_cases, _validate_rows
from eval_triage.db.models import Case, DatasetVersion, Grade, Review, Run, Trial, TrialOutcome
from eval_triage.db.repositories import create_dataset_version
from eval_triage.db.types import iso
from eval_triage.domain.enums import REVIEW_REASON_REQUIRED, ReviewDecision, Severity

router = APIRouter(tags=["reviews"])
PROMOTABLE = {ReviewDecision.PROMOTE_TO_REGRESSION, ReviewDecision.CONFIRM_FAILURE}


class ReviewRequest(BaseModel):
    trial_id: str
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=200)
    explanation: str = Field(default="", max_length=10000)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    grade_ids: list[str] = Field(default_factory=list)
    supersedes_id: str | None = None


def _review(row: Review, superseded_by: str | None = None) -> dict[str, Any]:
    return {"id": row.id, "trial_id": row.trial_id, "decision": row.decision, "reviewer": row.reviewer,
            "explanation": row.explanation, "evidence_refs": row.evidence_refs, "grade_ids": row.grade_ids,
            "supersedes_id": row.supersedes_id, "superseded_by": superseded_by, "links": row.links,
            "created_at": iso(row.created_at)}


@router.post("/reviews", status_code=201)
def create_review(body: ReviewRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    if body.decision in REVIEW_REASON_REQUIRED and not body.explanation.strip():
        raise validation_error(f"a reason is required for '{body.decision.value}'",
                               [{"loc": ["explanation"], "msg": "required for this decision"}])
    with ctx.db.write() as session:
        trial = session.get(Trial, body.trial_id)
        if trial is None:
            raise not_found("trial", body.trial_id)
        if body.supersedes_id:
            previous = session.get(Review, body.supersedes_id)
            if previous is None or previous.trial_id != trial.id:
                raise validation_error("supersedes_id must be an earlier review of the same trial")
            if session.scalars(select(Review).where(Review.supersedes_id == previous.id)).first():
                raise conflict("that review was already superseded; supersede the latest review instead")
        if body.grade_ids:
            owned = set(session.scalars(select(Grade.id).where(Grade.trial_id == trial.id)))
            if not set(body.grade_ids) <= owned:
                raise validation_error("grade_ids must belong to this trial")
        links = {}
        if body.decision == ReviewDecision.REQUEST_MORE_TRIALS:
            links["more_trials"] = f"POST /api/v1/runs/{trial.run_id}/more-trials"
        row = Review(trial_id=trial.id, grade_ids=body.grade_ids, reviewer=body.reviewer.strip(),
                     decision=body.decision.value, explanation=body.explanation, evidence_refs=body.evidence_refs,
                     supersedes_id=body.supersedes_id, links=links)
        session.add(row)
        session.flush()
        return envelope(_review(row))


@router.get("/reviews")
def list_reviews(ctx: AppContext = Depends(get_ctx), trial_id: str | None = None, run_id: str | None = None,
                 project_id: str | None = None, case_id: str | None = None) -> dict:
    with ctx.db.read() as session:
        query = select(Review).join(Trial, Trial.id == Review.trial_id)
        if trial_id:
            query = query.where(Review.trial_id == trial_id)
        if run_id:
            query = query.where(Trial.run_id == run_id)
        if case_id:
            query = query.where(Trial.case_id == case_id)
        if project_id:
            query = query.join(Run, Run.id == Trial.run_id).where(Run.project_id == project_id)
        rows = session.scalars(query.order_by(Review.created_at)).all()
        superseded = {r.supersedes_id: r.id for r in rows if r.supersedes_id}
        return envelope([_review(r, superseded.get(r.id)) for r in rows])


@router.get("/trials/{trial_id}/adjudicated")
def adjudicated(trial_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    """Machine outcomes next to the latest human review. Reviews never overwrite grades."""
    with ctx.db.read() as session:
        trial = session.get(Trial, trial_id)
        if trial is None:
            raise not_found("trial", trial_id)
        outcomes = session.scalars(select(TrialOutcome).where(TrialOutcome.trial_id == trial_id)
                                   .order_by(TrialOutcome.created_at)).all()
        reviews = session.scalars(select(Review).where(Review.trial_id == trial_id).order_by(Review.created_at)).all()
        superseded = {r.supersedes_id for r in reviews if r.supersedes_id}
        current = [r for r in reviews if r.id not in superseded]
        latest = current[-1] if current else None
        machine = outcomes[-1].outcome if outcomes else None
        human = {"confirm_failure": "fail", "acceptable_variation": "pass", "grader_incorrect": "disputed",
                 "ambiguous": "ambiguous"}.get(latest.decision) if latest else None
        return envelope({
            "trial_id": trial_id, "machine_outcome": machine,
            "machine_provenance": [{"grading_run_id": o.grading_run_id, "outcome": o.outcome, "reason": o.reason}
                                   for o in outcomes],
            "human_review": _review(latest) if latest else None,
            "adjudicated_outcome": human if human in ("pass", "fail") else machine,
            "adjudication_source": "human review" if human in ("pass", "fail") else "machine grades",
            "disagreement": human in ("pass", "fail") and machine in ("pass", "fail") and human != machine,
            "note": "The adjudicated view combines records; neither grades nor reviews are modified.",
        })


class PromotionItem(BaseModel):
    trial_id: str
    review_id: str
    expected: dict[str, Any]
    external_id: str | None = None
    severity: Severity | None = None
    purpose: str | None = None


class RegressionRequest(BaseModel):
    run_id: str
    items: list[PromotionItem] = Field(min_length=1)
    target_dataset_id: str | None = None
    name: str | None = None
    reason: str = "promoted from triage"


@router.post("/regressions", status_code=201)
def promote(body: RegressionRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.write() as session:
        run = session.get(Run, body.run_id)
        if run is None:
            raise not_found("run", body.run_id)
        target = None
        if body.target_dataset_id:
            target = session.get(DatasetVersion, body.target_dataset_id)
            if target is None or target.project_id != run.project_id:
                raise not_found("dataset", body.target_dataset_id)
            if target.scenario_id != run.scenario_id:
                raise validation_error("the target dataset belongs to a different scenario version")
        cases = _export_cases(session, target.id) if target else []
        by_id = {c["external_id"]: i for i, c in enumerate(cases)}
        links = []
        superseded = set(session.scalars(select(Review.supersedes_id).where(Review.supersedes_id.is_not(None))))
        for item in body.items:
            trial = session.get(Trial, item.trial_id)
            review = session.get(Review, item.review_id)
            if trial is None or trial.run_id != run.id:
                raise validation_error(f"trial {item.trial_id} is not part of run {run.id}")
            if review is None or review.trial_id != trial.id:
                raise validation_error(f"review {item.review_id} does not belong to trial {trial.id}")
            if review.id in superseded:
                raise validation_error(f"review {review.id} has been superseded; use the latest review")
            if review.decision not in PROMOTABLE:
                raise validation_error("promotion requires a 'confirm_failure' or 'promote_to_regression' review")
            source = session.get(Case, trial.case_id)
            external_id = item.external_id or source.external_id
            new_case = {"external_id": external_id,
                        "purpose": item.purpose or f"Regression from {run.name or run.id} (trial {trial.id[:8]}): "
                                                   f"{source.purpose}",
                        "severity": (item.severity.value if item.severity else source.severity),
                        "cluster_id": source.cluster_id, "weight": source.weight, "split": "regression",
                        "tags": source.tags, "input": source.input, "episode": source.episode,
                        "expected": item.expected, "alternatives": source.alternatives,
                        "evidence": source.evidence + [{"role": "regression_source", "run_id": run.id,
                                                        "trial_id": trial.id, "review_id": review.id}]}
            if source.fixture_options:
                new_case["fixture_options"] = source.fixture_options
            if external_id in by_id:
                cases[by_id[external_id]] = new_case
            else:
                by_id[external_id] = len(cases)
                cases.append(new_case)
            links.append({"trial_id": trial.id, "review_id": review.id, "source_case_id": source.id,
                          "external_id": external_id})
        scenario_row, report = _validate_rows(session, run.scenario_id, cases)
        if report.errors:
            raise ApiError(422, "validation_error", "promoted cases failed validation", report.to_dict())
        dataset = create_dataset_version(
            session, run.project_id, scenario_row, body.name or (target.name if target else
                                                                 f"regression · {scenario_row.name}"),
            report.cases, report.scenario.pass_rule(),
            provenance={"source": "regression_promotion", "run_id": run.id, "items": links},
            logical_id=target.logical_id if target else None, parent_id=target.id if target else None,
            reason=body.reason)
        return envelope({"dataset": ser.dataset(dataset), "links": links,
                         "note": "A new dataset version was created; the source run is unchanged."})
