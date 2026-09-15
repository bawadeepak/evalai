"""JSON shapes returned by the API. Secrets never appear: configs expose credential
reference names and whether they are set, never values."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import func, select

from eval_triage.db.models import (
    Attempt,
    Case,
    DatasetVersion,
    Grade,
    GraderVersion,
    GradingRun,
    Project,
    Run,
    RunCandidate,
    ScenarioVersion,
    TargetConfigVersion,
    Trial,
    TrialOutcome,
)
from eval_triage.db.types import iso


def project(row: Project) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "description": row.description, "is_demo": row.is_demo,
            "source_identity": row.source_identity, "created_at": iso(row.created_at)}


def scenario(row: ScenarioVersion, full: bool = False) -> dict[str, Any]:
    out = {"id": row.id, "project_id": row.project_id, "logical_id": row.logical_id, "version": row.version,
           "name": row.name, "pack": row.pack, "contract": row.contract, "slice_keys": row.slice_keys,
           "critical_invariants": row.critical_invariants, "grader_refs": row.grader_refs, "hash": row.hash,
           "parent_id": row.parent_id, "reason": row.reason, "is_demo": row.is_demo,
           "created_at": iso(row.created_at)}
    if full:
        out["definition"] = row.definition
    return out


def dataset(row: DatasetVersion) -> dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "logical_id": row.logical_id, "version": row.version,
            "name": row.name, "scenario_id": row.scenario_id, "pass_rule": row.pass_rule,
            "split_manifest": row.split_manifest, "provenance": row.provenance, "case_count": row.case_count,
            "hash": row.hash, "parent_id": row.parent_id, "reason": row.reason, "is_demo": row.is_demo,
            "created_at": iso(row.created_at)}


def case(row: Case) -> dict[str, Any]:
    return {"id": row.id, "dataset_id": row.dataset_id, "ordinal": row.ordinal, "external_id": row.external_id,
            "purpose": row.purpose, "input": row.input, "episode": row.episode, "expected": row.expected,
            "alternatives": row.alternatives, "evidence": row.evidence, "tags": row.tags, "severity": row.severity,
            "cluster_id": row.cluster_id, "weight": row.weight, "split": row.split,
            "fixture_options": row.fixture_options, "case_hash": row.case_hash}


def target_config(row: TargetConfigVersion) -> dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "logical_id": row.logical_id, "version": row.version,
            "name": row.name, "adapter": row.adapter, "adapter_version": row.adapter_version,
            "endpoint_type": row.endpoint_type, "model": row.model, "base_url": row.base_url,
            "credential_ref": row.credential_ref,
            "credential_status": ("not_required" if not row.credential_ref
                                  else "set" if os.environ.get(row.credential_ref) else "missing"),
            "parameters": row.parameters, "prompt_template": row.prompt_template, "tools": row.tools,
            "memory_config": row.memory_config, "capabilities": row.capabilities,
            "experimental": row.experimental, "hash": row.hash, "parent_id": row.parent_id,
            "is_demo": row.is_demo, "created_at": iso(row.created_at)}


def grader(row: GraderVersion) -> dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "logical_id": row.logical_id, "version": row.version,
            "name": row.name, "kind": row.kind, "implementation_version": row.implementation_version,
            "config": row.config, "judge_config_id": row.judge_config_id, "rubric": row.rubric,
            "output_schema": row.output_schema, "hash": row.hash, "is_demo": row.is_demo,
            "created_at": iso(row.created_at)}


def trial_counts(session, run_id: str) -> dict[str, int]:
    return dict(session.execute(select(Trial.status, func.count()).where(Trial.run_id == run_id)
                                .group_by(Trial.status)).all())


def run(session, row: Run, full: bool = False) -> dict[str, Any]:
    candidates = session.scalars(select(RunCandidate).where(RunCandidate.run_id == row.id)
                                 .order_by(RunCandidate.ordinal)).all()
    names = {c["key"]: c["config"]["name"] for c in row.manifest.get("candidates", [])}
    gradings = session.scalars(select(GradingRun).where(GradingRun.run_id == row.id)
                               .order_by(GradingRun.created_at)).all()
    counts = trial_counts(session, row.id)
    out = {
        "id": row.id, "project_id": row.project_id, "scenario_id": row.scenario_id, "dataset_id": row.dataset_id,
        "name": row.name, "status": row.status, "planned_trial_count": row.planned_trial_count,
        "terminal_trials": sum(v for k, v in counts.items() if k not in ("pending", "running")),
        "trial_counts": counts, "is_demo": row.is_demo,
        "demo_notice": row.manifest.get("demo_notice"), "manifest_hash": row.manifest_hash,
        "parent_run_id": row.parent_run_id, "usage": row.usage, "error": row.error,
        "candidates": [{"key": c.candidate_key, "target_config_id": c.target_config_id,
                        "name": names.get(c.candidate_key)} for c in candidates],
        "grading_runs": [{"id": g.id, "source": g.source, "status": g.status, "grader_ids": g.grader_ids,
                          "created_at": iso(g.created_at), "finished_at": iso(g.finished_at)} for g in gradings],
        "created_at": iso(row.created_at), "started_at": iso(row.started_at), "finished_at": iso(row.finished_at),
        "cancel_requested_at": iso(row.cancel_requested_at),
        "repeats": row.manifest.get("execution", {}).get("repeats"),
        "warnings": row.manifest.get("warnings", []),
    }
    if full:
        out["manifest"] = row.manifest
    return out


def trial_brief(row: Trial, case_row: Case, outcome: TrialOutcome | None = None) -> dict[str, Any]:
    return {"id": row.id, "run_id": row.run_id, "case_id": row.case_id, "external_id": case_row.external_id,
            "severity": case_row.severity, "cluster_id": case_row.cluster_id, "tags": case_row.tags,
            "candidate_key": row.candidate_key, "repeat_index": row.repeat_index, "status": row.status,
            "latency_ms": row.latency_ms, "error_code": (row.error or {}).get("code"),
            "outcome": outcome.outcome if outcome else None, "outcome_reason": outcome.reason if outcome else None,
            "invariant_failures": outcome.invariant_failures if outcome else []}


def grade(row: Grade, grader_row: GraderVersion | None) -> dict[str, Any]:
    return {"id": row.id, "grading_run_id": row.grading_run_id, "trial_id": row.trial_id,
            "grader_id": row.grader_id, "grader_name": grader_row.name if grader_row else None,
            "grader_kind": grader_row.kind if grader_row else None,
            "grader_version": grader_row.version if grader_row else None, "verdict": row.verdict,
            "reason": row.reason, "metric": row.metric, "checks": row.checks, "evidence_refs": row.evidence_refs,
            "explanation": row.explanation, "error": row.error, "judge_attempts": row.judge_attempts,
            "created_at": iso(row.created_at)}


def attempt(row: Attempt) -> dict[str, Any]:
    return {"id": row.id, "stage": row.stage, "attempt_index": row.attempt_index, "status": row.status,
            "request_id": row.request_id, "requested_model": row.requested_model, "actual_model": row.actual_model,
            "started_at": iso(row.started_at), "finished_at": iso(row.finished_at), "latency_ms": row.latency_ms,
            "usage": row.usage, "cost": row.cost, "retry_reason": row.retry_reason,
            "mutation_outcome_known": row.mutation_outcome_known, "error": row.error,
            "request_artifact": row.request_artifact, "response_artifact": row.response_artifact}


def trial_detail(session, row: Trial) -> dict[str, Any]:
    case_row = session.get(Case, row.case_id)
    run_row = session.get(Run, row.run_id)
    attempts = session.scalars(select(Attempt).where(Attempt.trial_id == row.id)
                               .order_by(Attempt.started_at, Attempt.stage, Attempt.attempt_index)).all()
    grades = session.scalars(select(Grade).where(Grade.trial_id == row.id).order_by(Grade.created_at)).all()
    graders = {g.id: g for g in session.scalars(select(GraderVersion).where(
        GraderVersion.id.in_([x.grader_id for x in grades])))}
    outcomes = session.scalars(select(TrialOutcome).where(TrialOutcome.trial_id == row.id)
                               .order_by(TrialOutcome.created_at)).all()
    siblings = session.scalars(select(Trial).where(Trial.run_id == row.run_id, Trial.case_id == row.case_id)
                               .order_by(Trial.candidate_key, Trial.repeat_index)).all()
    return {
        # The headline outcome is the latest grading run's; every run's outcome is listed below.
        **trial_brief(row, case_row, outcomes[-1] if outcomes else None), "case": case(case_row),
        "scenario_contract": run_row.manifest["scenario"], "is_demo": run_row.is_demo,
        "output": row.output, "steps": row.steps, "output_artifacts": row.output_artifacts,
        "state_artifacts": row.state_artifacts, "error": row.error, "selected_attempt_id": row.selected_attempt_id,
        "started_at": iso(row.started_at), "finished_at": iso(row.finished_at),
        "attempts": [attempt(a) for a in attempts],
        "grades": [grade(g, graders.get(g.grader_id)) for g in grades],
        "outcomes": [{"grading_run_id": o.grading_run_id, "outcome": o.outcome, "reason": o.reason,
                      "invariant_failures": o.invariant_failures} for o in outcomes],
        "siblings": [{"id": s.id, "candidate_key": s.candidate_key, "repeat_index": s.repeat_index,
                      "status": s.status} for s in siblings],
    }
