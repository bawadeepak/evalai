"""ORM models.

Definitions (scenario/dataset/case/target/grader/policy/calibration versions),
grades, reviews, comparisons, probability records, events and artifacts are
immutable: database triggers created in the initial migration abort any UPDATE
or DELETE. Runs, trials, attempts and jobs carry operational status; trials and
attempts additionally refuse updates once terminal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from eval_triage.db.types import UTCDateTime, new_id, utcnow


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON, datetime: UTCDateTime}


def _id() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


def _created() -> Mapped[datetime]:
    return mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = _created()


# --- immutable versioned definitions -------------------------------------------------


class ScenarioVersion(Base):
    __tablename__ = "scenario_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "logical_id", "version"),
        Index("ix_scenario_project_hash", "project_id", "hash"),
    )
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    logical_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    pack: Mapped[str] = mapped_column(String(40), nullable=False)
    contract: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    episode_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    grader_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    slice_keys: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    critical_invariants: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_versions.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "logical_id", "version"),
        Index("ix_dataset_project_hash", "project_id", "hash"),
    )
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    logical_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenario_versions.id"), nullable=False)
    pass_rule: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    split_manifest: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_versions.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("dataset_id", "external_id"),
        Index("ix_case_dataset_ordinal", "dataset_id", "ordinal"),
        Index("ix_case_hash", "case_hash"),
    )
    id: Mapped[str] = _id()
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    episode: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expected: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    alternatives: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tags: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    cluster_id: Mapped[str] = mapped_column(String(200), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    split: Mapped[str] = mapped_column(String(40), nullable=False, default="test")
    fixture_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    case_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class TargetConfigVersion(Base):
    __tablename__ = "target_config_versions"
    __table_args__ = (UniqueConstraint("project_id", "logical_id", "version"),)
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    logical_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    adapter: Mapped[str] = mapped_column(String(40), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(40), nullable=False)
    endpoint_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    memory_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    capabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    experimental: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("target_config_versions.id"), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class GraderVersion(Base):
    __tablename__ = "grader_versions"
    __table_args__ = (UniqueConstraint("project_id", "logical_id", "version"),)
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    logical_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    implementation_version: Mapped[str] = mapped_column(String(40), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    judge_config_id: Mapped[str | None] = mapped_column(ForeignKey("target_config_versions.id"), nullable=True)
    rubric: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("grader_versions.id"), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class ReleasePolicy(Base):
    __tablename__ = "release_policies"
    __table_args__ = (UniqueConstraint("project_id", "logical_id", "version"),)
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    logical_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    policy: Mapped[dict] = mapped_column(JSON, nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()


class CalibrationVersion(Base):
    __tablename__ = "calibration_versions"
    __table_args__ = (UniqueConstraint("project_id", "logical_id", "version"),)
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    logical_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_definition: Mapped[str] = mapped_column(Text, nullable=False)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    fit_method: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="fit")
    split_hashes: Mapped[dict] = mapped_column(JSON, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    model_artifact: Mapped[str | None] = mapped_column(ForeignKey("artifacts.content_hash"), nullable=True)
    validation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()


class ProbabilityRecord(Base):
    """A probability of a named binary event, recorded before its label is known."""

    __tablename__ = "probability_records"
    __table_args__ = (Index("ix_prob_project_event", "project_id", "event_definition"),)
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_versions.id"), nullable=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    trial_id: Mapped[str | None] = mapped_column(ForeignKey("trials.id"), nullable=True)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(200), nullable=False)
    split: Mapped[str] = mapped_column(String(40), nullable=False)
    event_definition: Mapped[str] = mapped_column(Text, nullable=False)
    score_type: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(String(200), nullable=False)
    source_version: Mapped[str] = mapped_column(String(200), nullable=False)
    predicted_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_feature: Mapped[float | None] = mapped_column(Float, nullable=True)
    label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    labeled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    unavailable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


# --- runs, trials, attempts, grades ----------------------------------------------------


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_run_status_created", "status", "created_at"), Index("ix_run_project", "project_id"))
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenario_versions.id"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    planned_trial_count: Mapped[int] = mapped_column(Integer, nullable=False)
    budget: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RunCandidate(Base):
    __tablename__ = "run_candidates"
    __table_args__ = (UniqueConstraint("run_id", "candidate_key"),)
    id: Mapped[str] = _id()
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    candidate_key: Mapped[str] = mapped_column(String(100), nullable=False)
    target_config_id: Mapped[str] = mapped_column(ForeignKey("target_config_versions.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class GradingRun(Base):
    __tablename__ = "grading_runs"
    __table_args__ = (Index("ix_grading_run_run", "run_id"),)
    id: Mapped[str] = _id()
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="initial")
    grader_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    grader_hashes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Trial(Base):
    __tablename__ = "trials"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", "candidate_key", "repeat_index", name="uq_trial_identity"),
        Index("ix_trial_run_case_candidate_repeat", "run_id", "case_id", "candidate_key", "repeat_index"),
        Index("ix_trial_run_status", "run_id", "status"),
    )
    id: Mapped[str] = _id()
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False)
    candidate_key: Mapped[str] = mapped_column(String(100), nullable=False)
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    schedule_order: Mapped[int] = mapped_column(Integer, nullable=False)
    episode_id: Mapped[str] = mapped_column(String(36), nullable=False, default=new_id)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_artifacts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    state_artifacts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    selected_attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("trial_id", "stage", "attempt_index"), Index("ix_attempt_trial", "trial_id"))
    id: Mapped[str] = _id()
    trial_id: Mapped[str] = mapped_column(ForeignKey("trials.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(60), nullable=False, default="target")
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requested_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actual_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    usage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cost: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retry_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mutation_outcome_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_artifact: Mapped[str | None] = mapped_column(ForeignKey("artifacts.content_hash"), nullable=True)
    response_artifact: Mapped[str | None] = mapped_column(ForeignKey("artifacts.content_hash"), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Grade(Base):
    __tablename__ = "grades"
    __table_args__ = (
        UniqueConstraint("grading_run_id", "trial_id", "grader_id"),
        Index("ix_grade_trial_grader", "trial_id", "grader_id"),
    )
    id: Mapped[str] = _id()
    grading_run_id: Mapped[str] = mapped_column(ForeignKey("grading_runs.id"), nullable=False)
    trial_id: Mapped[str] = mapped_column(ForeignKey("trials.id"), nullable=False)
    grader_id: Mapped[str] = mapped_column(ForeignKey("grader_versions.id"), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    metric: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    checks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    judge_attempts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()


class TrialOutcome(Base):
    """Result of applying the dataset pass rule to one trial within one grading run."""

    __tablename__ = "trial_outcomes"
    __table_args__ = (UniqueConstraint("grading_run_id", "trial_id"),
                      Index("ix_trial_outcome_trial", "trial_id"))
    id: Mapped[str] = _id()
    grading_run_id: Mapped[str] = mapped_column(ForeignKey("grading_runs.id"), nullable=False)
    trial_id: Mapped[str] = mapped_column(ForeignKey("trials.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    invariant_failures: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = _created()


# --- evidence ---------------------------------------------------------------------------


class Artifact(Base):
    __tablename__ = "artifacts"
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(200), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    redaction_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = _created()


class ArtifactRef(Base):
    __tablename__ = "artifact_refs"
    __table_args__ = (Index("ix_artifact_ref_entity", "entity_type", "entity_id"),)
    id: Mapped[str] = _id()
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[str] = mapped_column(String(60), nullable=False)
    content_hash: Mapped[str] = mapped_column(ForeignKey("artifacts.content_hash"), nullable=False)
    created_at: Mapped[datetime] = _created()


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_event_run_seq", "run_id", "seq"),)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


# --- human review and decisions --------------------------------------------------------


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (Index("ix_review_trial_created", "trial_id", "created_at"),)
    id: Mapped[str] = _id()
    trial_id: Mapped[str] = mapped_column(ForeignKey("trials.id"), nullable=False)
    grade_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("reviews.id"), nullable=True)
    links: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created()


class Comparison(Base):
    __tablename__ = "comparisons"
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    baseline_run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    candidate_run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    baseline_candidate_key: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_candidate_key: Mapped[str] = mapped_column(String(100), nullable=False)
    grading_run_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("release_policies.id"), nullable=True)
    compatibility: Mapped[dict] = mapped_column(JSON, nullable=False)
    pairing: Mapped[dict] = mapped_column(JSON, nullable=False)
    method: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics: Mapped[list] = mapped_column(JSON, nullable=False)
    exclusions: Mapped[list] = mapped_column(JSON, nullable=False)
    case_changes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = _created()


# --- operational -------------------------------------------------------------------------


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_job_claim", "status", "next_available_at", "priority"),
        Index("ix_job_run", "run_id"),
    )
    id: Mapped[str] = _id()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    payload_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    concurrency_key: Mapped[str] = mapped_column(String(200), nullable=False, default="default")
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_available_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = _created()
    heartbeat_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    info: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = _created()


class ConnectionTest(Base):
    __tablename__ = "connection_tests"
    id: Mapped[str] = _id()
    target_config_id: Mapped[str] = mapped_column(ForeignKey("target_config_versions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ExportRecord(Base):
    __tablename__ = "exports"
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    archive_hash: Mapped[str | None] = mapped_column(ForeignKey("artifacts.content_hash"), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ImportRecord(Base):
    __tablename__ = "imports"
    id: Mapped[str] = _id()
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    archive_hash: Mapped[str] = mapped_column(ForeignKey("artifacts.content_hash"), nullable=False)
    source_identity: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class MemoryStoreOwnership(Base):
    """Isolated MemoryAI stores created by Eval Triage. Only these may be dropped."""

    __tablename__ = "memory_store_ownership"
    id: Mapped[str] = _id()
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    trial_id: Mapped[str | None] = mapped_column(ForeignKey("trials.id"), nullable=True)
    data_dir: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    instance: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    bank: Mapped[str] = mapped_column(String(100), nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    disk_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _created()
    dropped_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ExternalImport(Base):
    """A result file imported from an external tool (Inspect log, Promptfoo results).

    Keeps the upstream identity and the original file as an artifact. Immutable.
    """

    __tablename__ = "external_imports"
    __table_args__ = (Index("ix_external_import_project", "project_id", "created_at"),)
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    plugin: Mapped[str] = mapped_column(String(40), nullable=False)
    plugin_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_identity: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_hash: Mapped[str] = mapped_column(ForeignKey("artifacts.content_hash"), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class ExternalResult(Base):
    """One normalized upstream result: assertions and scores exactly as the tool reported them."""

    __tablename__ = "external_results"
    __table_args__ = (UniqueConstraint("import_id", "ordinal", name="uq_external_result_ordinal"),)
    id: Mapped[str] = _id()
    import_id: Mapped[str] = mapped_column(ForeignKey("external_imports.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    upstream_id: Mapped[str] = mapped_column(String(200), nullable=False)
    case_external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    input: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    assertions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scores: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


#: Tables whose rows may never be updated or deleted.
IMMUTABLE_TABLES = (
    "scenario_versions",
    "dataset_versions",
    "cases",
    "target_config_versions",
    "grader_versions",
    "release_policies",
    "calibration_versions",
    "probability_records",
    "grades",
    "trial_outcomes",
    "reviews",
    "comparisons",
    "artifacts",
    "artifact_refs",
    "events",
    "external_imports",
    "external_results",
)
