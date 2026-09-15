"""Versioned definitions: scenarios, datasets and cases, target configs, graders,
release policies, and the reference vocabularies the UI needs."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from eval_triage.adapters.base import PARAMETER_CAPABILITIES
from eval_triage.adapters.registry import ADAPTERS
from eval_triage.api import serializers as ser
from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope
from eval_triage.api.errors import ApiError, not_found, validation_error
from eval_triage.db.models import (
    Case,
    ConnectionTest,
    DatasetVersion,
    GraderVersion,
    Project,
    ReleasePolicy,
    ScenarioVersion,
    TargetConfigVersion,
)
from eval_triage.db.repositories import (
    DefinitionError,
    DocumentInvalid,
    create_dataset_version,
    create_grader_version,
    create_release_policy,
    create_target_config,
    import_document,
)
from eval_triage.domain.canonical import canonical_json
from eval_triage.domain.checks import CHECKS
from eval_triage.domain.enums import JobKind, Pack
from eval_triage.domain.importers import ImportFormatError, detect_format, parse_bytes
from eval_triage.domain.packs import INVARIANTS, PACK_SPECS
from eval_triage.domain.scenario import (
    GraderSpec,
    ScenarioDocument,
    ValidationReport,
    validate_cases,
    validate_document,
)
from eval_triage.domain.splits import apply_cluster_split
from eval_triage.execution import jobs
from eval_triage.statistics.bootstrap import ReleasePolicyConfig
from eval_triage.statistics.core import StatisticsError
from eval_triage.statistics.registry import registry_payload

router = APIRouter(tags=["definitions"])


def _project(session, project_id: str) -> Project:
    row = session.get(Project, project_id)
    if row is None:
        raise not_found("project", project_id)
    return row


def _definition_error(exc: Exception) -> ApiError:
    if isinstance(exc, DocumentInvalid):
        return ApiError(422, "validation_error", "document failed validation", exc.report.to_dict())
    if isinstance(exc, DefinitionError):
        return ApiError(422, "validation_error", str(exc), exc.details)
    return ApiError(422, "validation_error", str(exc))


# --- reference vocabularies ---------------------------------------------------------------


@router.get("/packs")
def packs() -> dict:
    return envelope({
        "packs": [{"pack": p.value, "title": s.title, "summary": s.summary, "requires_episode": s.requires_episode,
                   "expected_schema": s.expected_model.model_json_schema()} for p, s in PACK_SPECS.items()],
        "checks": [{"name": name, "packs": sorted(p.value for p in packs) if packs else None, "description": desc}
                   for name, (packs, desc) in CHECKS.items()],
        "invariants": [{"name": k, "description": v} for k, v in INVARIANTS.items()],
    })


@router.get("/metrics")
def metrics() -> dict:
    return envelope(registry_payload())


@router.get("/adapters")
def adapters() -> dict:
    return envelope([{"name": name, **info, "parameter_capabilities": PARAMETER_CAPABILITIES,
                      "credential_default_status": ("not_required" if not info["credential_default"] else
                                                    "set" if os.environ.get(info["credential_default"])
                                                    else "missing")}
                     for name, info in ADAPTERS.items()])


# --- scenarios -----------------------------------------------------------------------------


class DocumentRequest(BaseModel):
    document: dict[str, Any]


class ScenarioCreate(BaseModel):
    project_id: str
    document: dict[str, Any]
    judges: dict[str, str] = Field(default_factory=dict)
    dataset_name: str | None = None
    parent_id: str | None = None  # "edit as new version": the new row joins the parent's logical id
    reason: str = Field(default="", max_length=2000)


class TextImport(BaseModel):
    project_id: str
    filename: str
    content: str = Field(max_length=10 * 1024 * 1024)
    scenario_id: str | None = None
    dataset_name: str | None = None
    judges: dict[str, str] = Field(default_factory=dict)


@router.post("/scenarios/validate")
def validate_scenario(body: DocumentRequest) -> dict:
    return envelope(validate_document(body.document).to_dict())


@router.get("/scenarios")
def list_scenarios(project_id: str, latest_only: bool = True, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        rows = session.scalars(select(ScenarioVersion).where(ScenarioVersion.project_id == project_id)
                               .order_by(ScenarioVersion.created_at.desc())).all()
        if latest_only:
            seen, latest = set(), []
            for row in sorted(rows, key=lambda r: (r.logical_id, -r.version)):
                if row.logical_id not in seen:
                    seen.add(row.logical_id)
                    latest.append(row)
            rows = sorted(latest, key=lambda r: r.created_at, reverse=True)
        out = []
        for row in rows:
            datasets = session.scalars(select(DatasetVersion).where(DatasetVersion.scenario_id == row.id)).all()
            out.append({**ser.scenario(row), "dataset_count": len(datasets),
                        "case_count": sum(d.case_count for d in datasets)})
        return envelope(out)


@router.post("/scenarios", status_code=201)
def create_scenario(body: ScenarioCreate, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        with ctx.db.write() as session:
            _project(session, body.project_id)
            logical_id = None
            if body.parent_id:
                parent = session.get(ScenarioVersion, body.parent_id)
                if parent is None or parent.project_id != body.project_id:
                    raise not_found("scenario", body.parent_id)
                logical_id = parent.logical_id
            result = import_document(session, body.project_id, body.document, judges=body.judges,
                                     dataset_name=body.dataset_name, provenance={"source": "api"},
                                     logical_id=logical_id, parent_id=body.parent_id, reason=body.reason)
            return envelope({"scenario": ser.scenario(result["scenario"], full=True),
                             "dataset": ser.dataset(result["dataset"]) if result["dataset"] else None,
                             "graders": [ser.grader(g) for g in result["graders"]],
                             "warnings": result["report"].to_dict()["warnings"]})
    except (DocumentInvalid, DefinitionError) as exc:
        raise _definition_error(exc) from exc


@router.post("/imports/documents", status_code=201)
def import_text(body: TextImport, ctx: AppContext = Depends(get_ctx)) -> dict:
    """Import a JSON/JSONL/YAML file: a full scenario document, or cases for an existing scenario."""
    try:
        parsed = parse_bytes(body.content.encode("utf-8"), detect_format(body.filename))
    except ImportFormatError as exc:
        raise validation_error(str(exc), {"line": exc.line}) from exc
    try:
        with ctx.db.write() as session:
            _project(session, body.project_id)
            if isinstance(parsed, dict) and "pack" in parsed:
                result = import_document(session, body.project_id, parsed, judges=body.judges,
                                         dataset_name=body.dataset_name,
                                         provenance={"source": "import", "filename": body.filename})
                return envelope({"scenario": ser.scenario(result["scenario"]),
                                 "dataset": ser.dataset(result["dataset"]) if result["dataset"] else None,
                                 "warnings": result["report"].to_dict()["warnings"]})
            if body.scenario_id is None:
                raise validation_error("a list of cases needs scenario_id")
            cases = parsed if isinstance(parsed, list) else (parsed or {}).get("cases")
            dataset = _create_dataset(session, body.project_id, body.scenario_id,
                                      body.dataset_name or body.filename.rsplit(".", 1)[0], cases,
                                      provenance={"source": "import", "filename": body.filename})
            return envelope({"dataset": ser.dataset(dataset)})
    except (DocumentInvalid, DefinitionError) as exc:
        raise _definition_error(exc) from exc


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(ScenarioVersion, scenario_id)
        if row is None:
            raise not_found("scenario", scenario_id)
        graders = [session.get(GraderVersion, g) for g in row.grader_refs]
        datasets = session.scalars(select(DatasetVersion).where(DatasetVersion.scenario_id == row.id)
                                   .order_by(DatasetVersion.created_at.desc())).all()
        versions = session.scalars(select(ScenarioVersion).where(ScenarioVersion.logical_id == row.logical_id)
                                   .order_by(ScenarioVersion.version)).all()
        return envelope({**ser.scenario(row, full=True), "graders": [ser.grader(g) for g in graders if g],
                         "datasets": [ser.dataset(d) for d in datasets],
                         "versions": [{"id": v.id, "version": v.version, "created_at": v.created_at.isoformat(),
                                       "reason": v.reason} for v in versions]})


def _scenario_document(row: ScenarioVersion) -> ScenarioDocument:
    return ScenarioDocument.model_validate({**row.definition})


def _validate_rows(session, scenario_id: str, cases: Any) -> tuple[ScenarioVersion, ValidationReport]:
    scenario_row = session.get(ScenarioVersion, scenario_id)
    if scenario_row is None:
        raise not_found("scenario", scenario_id)
    report = ValidationReport(scenario=_scenario_document(scenario_row))
    if not isinstance(cases, list):
        raise validation_error("cases must be a list")
    report.cases = validate_cases(cases, report, pack=Pack(scenario_row.pack), scenario=report.scenario,
                                  prefix="cases")
    return scenario_row, report


def _create_dataset(session, project_id: str, scenario_id: str, name: str, cases: Any, *, provenance: dict,
                    logical_id: str | None = None, parent_id: str | None = None, reason: str = "",
                    pass_rule: dict | None = None) -> DatasetVersion:
    scenario_row, report = _validate_rows(session, scenario_id, cases)
    if scenario_row.project_id != project_id:
        raise not_found("scenario", scenario_id)
    if report.errors:
        raise DocumentInvalid(report)
    rule = pass_rule or report.scenario.pass_rule()
    return create_dataset_version(session, project_id, scenario_row, name, report.cases, rule,
                                  provenance=provenance, logical_id=logical_id, parent_id=parent_id, reason=reason)


# --- datasets and cases -----------------------------------------------------------------------


class CasesValidate(BaseModel):
    scenario_id: str
    cases: list[Any]


class DatasetCreate(BaseModel):
    project_id: str
    scenario_id: str
    name: str = Field(min_length=1, max_length=200)
    cases: list[Any] = Field(min_length=1)
    logical_id: str | None = None
    parent_id: str | None = None
    reason: str = ""


class SplitRequest(BaseModel):
    fractions: dict[str, float] = Field(default_factory=lambda: {"calibration": 0.5, "test": 0.5})
    seed: int = 42
    dry_run: bool = True
    reason: str = "cluster-aware split"


@router.post("/datasets/validate")
def validate_dataset(body: CasesValidate, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        _, report = _validate_rows(session, body.scenario_id, body.cases)
        return envelope({**report.to_dict(), "ok": not report.errors})


@router.get("/datasets")
def list_datasets(project_id: str, scenario_id: str | None = None, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        query = select(DatasetVersion).where(DatasetVersion.project_id == project_id)
        if scenario_id:
            query = query.where(DatasetVersion.scenario_id == scenario_id)
        return envelope([ser.dataset(d) for d in session.scalars(query.order_by(DatasetVersion.created_at.desc()))])


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetCreate, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        with ctx.db.write() as session:
            _project(session, body.project_id)
            if body.parent_id:
                parent = session.get(DatasetVersion, body.parent_id)
                if parent is None:
                    raise not_found("dataset", body.parent_id)
                logical_id = body.logical_id or parent.logical_id
            else:
                logical_id = body.logical_id
            row = _create_dataset(session, body.project_id, body.scenario_id, body.name, body.cases,
                                  provenance={"source": "editor"}, logical_id=logical_id, parent_id=body.parent_id,
                                  reason=body.reason)
            return envelope(ser.dataset(row))
    except (DocumentInvalid, DefinitionError) as exc:
        raise _definition_error(exc) from exc


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(DatasetVersion, dataset_id)
        if row is None:
            raise not_found("dataset", dataset_id)
        versions = session.scalars(select(DatasetVersion).where(DatasetVersion.logical_id == row.logical_id)
                                   .order_by(DatasetVersion.version)).all()
        cases = session.scalars(select(Case).where(Case.dataset_id == row.id)).all()
        hashes: dict[str, list[str]] = {}
        for c in cases:
            hashes.setdefault(c.case_hash, []).append(c.external_id)
        return envelope({**ser.dataset(row), "versions": [{"id": v.id, "version": v.version, "reason": v.reason,
                                                           "case_count": v.case_count} for v in versions],
                         "duplicates": [ids for ids in hashes.values() if len(ids) > 1],
                         "scenario": ser.scenario(session.get(ScenarioVersion, row.scenario_id))})


@router.get("/datasets/{dataset_id}/cases")
def dataset_cases(dataset_id: str, ctx: AppContext = Depends(get_ctx), limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0), split: str | None = None) -> dict:
    with ctx.db.read() as session:
        row = session.get(DatasetVersion, dataset_id)
        if row is None:
            raise not_found("dataset", dataset_id)
        query = select(Case).where(Case.dataset_id == dataset_id)
        if split:
            query = query.where(Case.split == split)
        rows = session.scalars(query.order_by(Case.ordinal).offset(offset).limit(limit)).all()
        next_offset = offset + limit if offset + limit < row.case_count else None
        return envelope([ser.case(c) for c in rows], limit=limit, offset=offset, total=row.case_count,
                        next_cursor=str(next_offset) if next_offset is not None else None)


def _export_cases(session, dataset_id: str) -> list[dict[str, Any]]:
    cases = session.scalars(select(Case).where(Case.dataset_id == dataset_id).order_by(Case.ordinal)).all()
    out = []
    for c in cases:
        item = {"external_id": c.external_id, "purpose": c.purpose, "severity": c.severity, "cluster_id": c.cluster_id,
                "weight": c.weight, "split": c.split, "tags": c.tags, "input": c.input, "episode": c.episode,
                "expected": c.expected, "alternatives": c.alternatives, "evidence": c.evidence}
        if c.fixture_options:
            item["fixture_options"] = c.fixture_options
        out.append(item)
    return out


@router.get("/datasets/{dataset_id}/export")
def export_dataset(dataset_id: str, format: str = Query(default="json", pattern="^(json|jsonl)$"),
                   ctx: AppContext = Depends(get_ctx)):
    with ctx.db.read() as session:
        if session.get(DatasetVersion, dataset_id) is None:
            raise not_found("dataset", dataset_id)
        cases = _export_cases(session, dataset_id)
    if format == "jsonl":
        return PlainTextResponse("\n".join(canonical_json(c) for c in cases) + "\n", media_type="application/x-ndjson")
    return envelope(cases)


@router.post("/datasets/{dataset_id}/split")
def split_dataset(dataset_id: str, body: SplitRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        with ctx.db.write() as session:
            row = session.get(DatasetVersion, dataset_id)
            if row is None:
                raise not_found("dataset", dataset_id)
            cases = _export_cases(session, dataset_id)
            updated, manifest = apply_cluster_split(cases, body.fractions, body.seed)
            if body.dry_run:
                return envelope({"dry_run": True, "split_manifest": manifest})
            new = _create_dataset(session, row.project_id, row.scenario_id, row.name, updated,
                                  provenance={"source": "split", "parent": row.id, "split": manifest},
                                  logical_id=row.logical_id, parent_id=row.id, reason=body.reason,
                                  pass_rule=row.pass_rule)
            return envelope({"dry_run": False, "dataset": ser.dataset(new), "split_manifest": manifest})
    except ValueError as exc:
        raise validation_error(str(exc)) from exc


# --- target configurations -------------------------------------------------------------------


class TargetCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=200)
    adapter: str
    model: str = ""
    endpoint_type: str = ""
    base_url: str | None = None
    credential_ref: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    prompt_template: str = ""
    tools: list[dict[str, Any]] = Field(default_factory=list)
    memory_config: dict[str, Any] = Field(default_factory=dict)
    experimental: bool = False
    logical_id: str | None = None
    parent_id: str | None = None


@router.get("/target-configs")
def list_targets(project_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        rows = session.scalars(select(TargetConfigVersion).where(TargetConfigVersion.project_id == project_id)
                               .order_by(TargetConfigVersion.created_at.desc())).all()
        return envelope([ser.target_config(r) for r in rows])


@router.post("/target-configs", status_code=201)
def create_target(body: TargetCreate, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        with ctx.db.write() as session:
            _project(session, body.project_id)
            logical_id = body.logical_id
            if body.parent_id and not logical_id:
                parent = session.get(TargetConfigVersion, body.parent_id)
                logical_id = parent.logical_id if parent else None
            row = create_target_config(session, body.project_id, name=body.name, adapter=body.adapter,
                                       model=body.model, endpoint_type=body.endpoint_type, base_url=body.base_url,
                                       credential_ref=body.credential_ref, parameters=body.parameters,
                                       prompt_template=body.prompt_template, tools=body.tools,
                                       memory_config=body.memory_config, experimental=body.experimental,
                                       logical_id=logical_id, parent_id=body.parent_id)
            return envelope(ser.target_config(row))
    except (DefinitionError, ModuleNotFoundError) as exc:
        raise _definition_error(exc) from exc


@router.get("/target-configs/{config_id}")
def get_target(config_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(TargetConfigVersion, config_id)
        if row is None:
            raise not_found("target config", config_id)
        return envelope(ser.target_config(row))


@router.get("/target-configs/{config_id}/capabilities")
def target_capabilities(config_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(TargetConfigVersion, config_id)
        if row is None:
            raise not_found("target config", config_id)
        tests = session.scalars(select(ConnectionTest).where(ConnectionTest.target_config_id == config_id)
                                .order_by(ConnectionTest.created_at.desc()).limit(5)).all()
        return envelope({"target_config_id": row.id, "adapter": row.adapter, "model": row.model,
                         "endpoint_type": row.endpoint_type, "capabilities": row.capabilities,
                         "parameter_capabilities": PARAMETER_CAPABILITIES,
                         "recent_connection_tests": [{"id": t.id, "status": t.status, "result": t.result,
                                                      "created_at": t.created_at.isoformat()} for t in tests]})


@router.post("/target-configs/{config_id}/connection-tests", status_code=202)
def connection_test(config_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.write() as session:
        row = session.get(TargetConfigVersion, config_id)
        if row is None:
            raise not_found("target config", config_id)
        test = ConnectionTest(target_config_id=config_id, status="queued")
        session.add(test)
        session.flush()
        jobs.enqueue(session, JobKind.CONNECTION_TEST, {"connection_test_id": test.id},
                     concurrency_key=f"target:{config_id}", concurrency_limit=1, max_attempts=1)
        return envelope({"id": test.id, "status": test.status,
                         "note": "explicit, bounded request to the configured endpoint"})


@router.get("/connection-tests/{test_id}")
def get_connection_test(test_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(ConnectionTest, test_id)
        if row is None:
            raise not_found("connection test", test_id)
        return envelope({"id": row.id, "target_config_id": row.target_config_id, "status": row.status,
                         "result": row.result, "created_at": row.created_at.isoformat(),
                         "finished_at": row.finished_at.isoformat() if row.finished_at else None})


# --- graders and release policies ---------------------------------------------------------------


class GraderCreate(BaseModel):
    project_id: str
    spec: dict[str, Any]
    judge_config_id: str | None = None
    logical_id: str | None = None


@router.get("/graders")
def list_graders(project_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        rows = session.scalars(select(GraderVersion).where(GraderVersion.project_id == project_id)
                               .order_by(GraderVersion.created_at.desc())).all()
        return envelope([ser.grader(g) for g in rows])


@router.post("/graders", status_code=201)
def create_grader(body: GraderCreate, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        spec = GraderSpec.model_validate(body.spec)
    except ValidationError as exc:
        raise validation_error("invalid grader spec", [{"loc": list(e["loc"]), "msg": e["msg"]}
                                                       for e in exc.errors()]) from exc
    try:
        with ctx.db.write() as session:
            _project(session, body.project_id)
            row = create_grader_version(session, body.project_id, spec, body.judge_config_id, body.logical_id)
            return envelope(ser.grader(row))
    except DefinitionError as exc:
        raise _definition_error(exc) from exc


@router.get("/graders/{grader_id}")
def get_grader(grader_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(GraderVersion, grader_id)
        if row is None:
            raise not_found("grader", grader_id)
        return envelope(ser.grader(row))


class PolicyCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=200)
    policy: dict[str, Any]


@router.get("/release-policies")
def list_policies(project_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        rows = session.scalars(select(ReleasePolicy).where(ReleasePolicy.project_id == project_id)
                               .order_by(ReleasePolicy.created_at.desc())).all()
        return envelope([{"id": r.id, "name": r.name, "version": r.version, "policy": r.policy, "hash": r.hash,
                          "created_at": r.created_at.isoformat()} for r in rows])


@router.post("/release-policies", status_code=201)
def create_policy(body: PolicyCreate, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        ReleasePolicyConfig.from_dict(body.policy)
        with ctx.db.write() as session:
            _project(session, body.project_id)
            row = create_release_policy(session, body.project_id, body.name, body.policy)
            return envelope({"id": row.id, "name": row.name, "version": row.version, "policy": row.policy,
                             "hash": row.hash})
    except (StatisticsError, TypeError) as exc:
        raise validation_error(f"invalid release policy: {exc}") from exc
