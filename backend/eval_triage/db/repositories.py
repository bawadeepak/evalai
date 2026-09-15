"""Creation of immutable, versioned definitions.

Editing a definition always creates a new version under the same logical id;
saving content identical to an existing version returns that version. Version
numbers are allocated inside the caller's ``BEGIN IMMEDIATE`` transaction.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, select

from eval_triage.adapters.base import TargetConfig
from eval_triage.adapters.registry import ADAPTERS, get_adapter
from eval_triage.db.models import (
    Case,
    DatasetVersion,
    GraderVersion,
    Project,
    ReleasePolicy,
    ScenarioVersion,
    TargetConfigVersion,
)
from eval_triage.domain.canonical import content_hash, hash_payload
from eval_triage.domain.enums import GraderKind
from eval_triage.domain.scenario import (
    CaseModel,
    GraderSpec,
    ScenarioDocument,
    ValidationReport,
    dataset_hash,
    validate_document,
)
from eval_triage.domain.splits import split_manifest
from eval_triage.graders.judge import JUDGE_OUTPUT_SCHEMA, PAIRWISE_OUTPUT_SCHEMA
from eval_triage.graders.runner import IMPLEMENTATION_VERSION
from eval_triage.statistics.bootstrap import ReleasePolicyConfig

CREDENTIAL_REF = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
SECRET_LIKE = re.compile(r"^(sk-|sk_|xox|ghp_|AKIA)|[A-Za-z0-9+/=_-]{40,}")


class DefinitionError(ValueError):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.details = details


class DocumentInvalid(DefinitionError):
    def __init__(self, report: ValidationReport) -> None:
        super().__init__("document failed validation", report.to_dict())
        self.report = report


def _next_version(session, model, logical_id: str) -> int:
    current = session.scalar(select(func.max(model.version)).where(model.logical_id == logical_id))
    return (current or 0) + 1


def _existing(session, model, project_id: str, logical_id: str | None, digest: str):
    query = select(model).where(model.project_id == project_id, model.hash == digest)
    if logical_id:
        query = query.where(model.logical_id == logical_id)
    return session.scalars(query.order_by(model.version.desc())).first()


def create_project(session, name: str, description: str = "", is_demo: bool = False,
                   source_identity: dict | None = None) -> Project:
    project = Project(name=name.strip() or "Untitled project", description=description, is_demo=is_demo,
                      source_identity=source_identity)
    session.add(project)
    session.flush()
    return project


def validate_credential_ref(ref: str | None) -> str | None:
    if ref in (None, ""):
        return None
    if not CREDENTIAL_REF.fullmatch(ref) or SECRET_LIKE.search(ref):
        raise DefinitionError("credential_ref must be the NAME of an environment variable (for example "
                              "OPENAI_API_KEY), never a key value")
    return ref


def create_target_config(session, project_id: str, *, name: str, adapter: str, model: str = "",
                         endpoint_type: str = "", base_url: str | None = None, credential_ref: str | None = None,
                         parameters: dict | None = None, prompt_template: str = "", tools: list | None = None,
                         memory_config: dict | None = None, experimental: bool = False, logical_id: str | None = None,
                         parent_id: str | None = None, is_demo: bool = False) -> TargetConfigVersion:
    if adapter not in ADAPTERS:
        raise DefinitionError(f"unknown adapter {adapter!r}", {"known": sorted(ADAPTERS)})
    info = ADAPTERS[adapter]
    endpoint_type = endpoint_type or info["endpoint_types"][0]
    if endpoint_type not in info["endpoint_types"]:
        raise DefinitionError(f"{adapter} supports endpoint types {info['endpoint_types']}")
    if adapter in ("openai", "anthropic", "openai_compatible") and not model.strip():
        raise DefinitionError("model is required; Eval Triage never invents a default model name")
    if adapter == "openai_compatible" and not base_url:
        raise DefinitionError("the local OpenAI-compatible adapter needs an explicit base_url")
    if adapter == "memoryai":
        from urllib.parse import urlparse

        from eval_triage.adapters.memoryai.adapter import CLOUD_BOUNDARY

        memory_config = dict(memory_config or {})
        if memory_config.setdefault("backend", "real") not in ("real", "fake"):
            raise DefinitionError("memory_config.backend must be 'real' or 'fake'")
        # MemoryAI's own Settings defaults; stated in the configuration rather than implied.
        memory_config.setdefault("llm_model", model or "gemma3:4b")
        url = memory_config.setdefault("llm_base_url", "http://localhost:11434/v1")
        if urlparse(url).hostname not in ("localhost", "127.0.0.1", "::1"):
            raise DefinitionError(CLOUD_BOUNDARY)
        memory_config.setdefault("small_talk_filter", True)
        memory_config.setdefault("retain_stores", True)
        generation = memory_config.get("generation_target_config_id")
        if generation:
            target = session.get(TargetConfigVersion, generation)
            if target is None or target.project_id != project_id or target.adapter == "memoryai":
                raise DefinitionError("generation_target_config_id must name a non-MemoryAI target in this project")
        model = memory_config["llm_model"]
    credential_ref = validate_credential_ref(credential_ref if credential_ref is not None
                                             else info["credential_default"])
    implementation = get_adapter(adapter)
    config = TargetConfig(id="", name=name, adapter=adapter, adapter_version=implementation.version,
                          endpoint_type=endpoint_type, model=model.strip(), base_url=base_url,
                          credential_ref=credential_ref, parameters=dict(parameters or {}),
                          prompt_template=prompt_template, tools=list(tools or []),
                          memory_config=dict(memory_config or {}), experimental=experimental)
    digest = hash_payload(config.hash_payload())
    existing = _existing(session, TargetConfigVersion, project_id, logical_id, digest)
    if existing is not None and existing.name == name:
        return existing
    logical_id = logical_id or str(uuid.uuid4())
    capabilities = {k: v.to_dict() for k, v in implementation.capabilities(config).items()}
    row = TargetConfigVersion(project_id=project_id, logical_id=logical_id,
                              version=_next_version(session, TargetConfigVersion, logical_id), name=name,
                              adapter=adapter, adapter_version=config.adapter_version, endpoint_type=endpoint_type,
                              model=config.model, base_url=base_url, credential_ref=credential_ref,
                              parameters=config.parameters, prompt_template=prompt_template, tools=config.tools,
                              memory_config=config.memory_config, capabilities=capabilities,
                              experimental=experimental, hash=digest, parent_id=parent_id, is_demo=is_demo)
    session.add(row)
    session.flush()
    return row


def create_grader_version(session, project_id: str, spec: GraderSpec, judge_config_id: str | None = None,
                          logical_id: str | None = None, is_demo: bool = False) -> GraderVersion:
    judge_hash = None
    if judge_config_id:
        judge = session.get(TargetConfigVersion, judge_config_id)
        if judge is None or judge.project_id != project_id:
            raise DefinitionError(f"judge config {judge_config_id} not found in this project")
        judge_hash = judge.hash
    output_schema = {GraderKind.MODEL: JUDGE_OUTPUT_SCHEMA, GraderKind.PAIRWISE: PAIRWISE_OUTPUT_SCHEMA}.get(spec.kind, {})
    config = {"checks": spec.checks, "mandatory": spec.is_mandatory, "config": spec.config, "judge": spec.judge}
    digest = content_hash({"name": spec.name, "kind": spec.kind.value, "implementation": IMPLEMENTATION_VERSION,
                           "config": config, "rubric": spec.rubric, "judge_hash": judge_hash})
    existing = _existing(session, GraderVersion, project_id, logical_id, digest)
    if existing is not None:
        return existing
    logical_id = logical_id or str(uuid.uuid4())
    row = GraderVersion(project_id=project_id, logical_id=logical_id,
                        version=_next_version(session, GraderVersion, logical_id), name=spec.name,
                        kind=spec.kind.value, implementation_version=IMPLEMENTATION_VERSION, config=config,
                        judge_config_id=judge_config_id, rubric=spec.rubric, output_schema=output_schema,
                        hash=digest, is_demo=is_demo)
    session.add(row)
    session.flush()
    return row


def grader_spec(row: GraderVersion) -> dict[str, Any]:
    """The dict shape graders consume at grading time."""
    return {"id": row.id, "name": row.name, "kind": row.kind, "checks": row.config.get("checks", []),
            "mandatory": row.config.get("mandatory"), "config": row.config.get("config", {}),
            "rubric": row.rubric, "judge": row.config.get("judge"), "judge_config_id": row.judge_config_id,
            "hash": row.hash, "implementation_version": row.implementation_version}


def create_scenario_version(session, project_id: str, scenario: ScenarioDocument, grader_ids: list[str], *,
                            logical_id: str | None = None, parent_id: str | None = None, reason: str = "",
                            is_demo: bool = False) -> ScenarioVersion:
    digest = scenario.scenario_hash()
    existing = _existing(session, ScenarioVersion, project_id, logical_id, digest)
    if existing is not None and sorted(existing.grader_refs) == sorted(grader_ids):
        return existing
    logical_id = logical_id or str(uuid.uuid4())
    definition = scenario.definition()
    row = ScenarioVersion(project_id=project_id, logical_id=logical_id,
                          version=_next_version(session, ScenarioVersion, logical_id), name=scenario.name,
                          pack=scenario.pack.value, contract=scenario.contract,
                          input_schema=scenario.input_schema, episode_schema={}, grader_refs=list(grader_ids),
                          slice_keys=scenario.slice_keys, critical_invariants=scenario.critical_invariants,
                          definition=definition, hash=digest, parent_id=parent_id, reason=reason, is_demo=is_demo)
    session.add(row)
    session.flush()
    return row


def create_dataset_version(session, project_id: str, scenario_row: ScenarioVersion, name: str,
                           cases: list[CaseModel], pass_rule: dict, *, provenance: dict | None = None,
                           logical_id: str | None = None, parent_id: str | None = None, reason: str = "",
                           is_demo: bool = False) -> DatasetVersion:
    if not cases:
        raise DefinitionError("a dataset version needs at least one valid case")
    digest = dataset_hash(scenario_row.hash, name, pass_rule, cases)
    existing = _existing(session, DatasetVersion, project_id, logical_id, digest)
    if existing is not None and existing.scenario_id == scenario_row.id:
        return existing
    stored = [case.stored(i) for i, case in enumerate(cases)]
    logical_id = logical_id or str(uuid.uuid4())
    row = DatasetVersion(project_id=project_id, logical_id=logical_id,
                         version=_next_version(session, DatasetVersion, logical_id), name=name,
                         scenario_id=scenario_row.id, pass_rule=pass_rule, split_manifest=split_manifest(stored),
                         provenance=provenance or {}, case_count=len(stored), hash=digest, parent_id=parent_id,
                         reason=reason, is_demo=is_demo)
    session.add(row)
    session.flush()
    for item in stored:
        session.add(Case(dataset_id=row.id, **item))
    session.flush()
    return row


def import_document(session, project_id: str, raw: Any, *, judges: dict[str, str] | None = None,
                    provenance: dict | None = None, dataset_name: str | None = None,
                    is_demo: bool = False, logical_id: str | None = None, parent_id: str | None = None,
                    reason: str = "") -> dict[str, Any]:
    """Validate and store a scenario document (scenario, graders and dataset) atomically.

    ``logical_id``/``parent_id`` make the scenario a new version of an existing one
    ("edit as new version"); earlier versions are never modified.
    """
    report = validate_document(raw)
    if not report.ok:
        raise DocumentInvalid(report)
    scenario = report.scenario
    judges = judges or {}
    graders = [create_grader_version(session, project_id, spec, judges.get(spec.judge) if spec.judge else None,
                                     is_demo=is_demo) for spec in scenario.graders]
    scenario_row = create_scenario_version(session, project_id, scenario, [g.id for g in graders],
                                           logical_id=logical_id, parent_id=parent_id, reason=reason,
                                           is_demo=is_demo)
    dataset_row = None
    if report.cases:
        name = dataset_name or (scenario.dataset.name if scenario.dataset else f"{scenario.name}-cases")
        dataset_row = create_dataset_version(session, project_id, scenario_row, name, report.cases,
                                             scenario.pass_rule(), provenance=provenance, is_demo=is_demo)
    return {"report": report, "scenario": scenario_row, "dataset": dataset_row, "graders": graders}


def create_release_policy(session, project_id: str, name: str, policy: dict,
                          logical_id: str | None = None) -> ReleasePolicy:
    ReleasePolicyConfig.from_dict(policy)  # validates
    digest = content_hash({"name": name, "policy": policy})
    existing = _existing(session, ReleasePolicy, project_id, logical_id, digest)
    if existing is not None:
        return existing
    logical_id = logical_id or str(uuid.uuid4())
    row = ReleasePolicy(project_id=project_id, logical_id=logical_id,
                        version=_next_version(session, ReleasePolicy, logical_id), name=name, policy=policy,
                        hash=digest)
    session.add(row)
    session.flush()
    return row
