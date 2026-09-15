"""Application-owned scenario/dataset documents and their validation.

``validate_document`` never stops at the first problem: it returns every
header, row and field error (plus warnings) so an editor can show them all.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from eval_triage.domain.canonical import content_hash, hash_payload
from eval_triage.domain.checks import CHECKS
from eval_triage.domain.enums import GraderKind, Pack, Severity, Split
from eval_triage.domain.episode import Step, episode_errors
from eval_triage.domain.packs import INVARIANTS, PACK_SPECS, MemoryExpected, ToolAgentExpected

SLUG = r"^[a-z0-9][a-z0-9_.-]{0,99}$"
EXTERNAL_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


TagValue = str | int | float | bool | None


class FaultInjection(_Strict):
    smalltalk: Literal["timeout", "malformed", "http_500"] | None = None


class FixtureOptions(_Strict):
    fault_injection: FaultInjection | None = None


class CaseModel(_Strict):
    external_id: str = Field(pattern=EXTERNAL_ID)
    purpose: str = ""
    severity: Severity = Severity.MEDIUM
    cluster_id: str | None = Field(default=None, min_length=1, max_length=200)
    weight: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    split: Split = Split.TEST
    tags: dict[str, TagValue] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)
    episode: list[Step] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    alternatives: list[Any] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    fixture_options: FixtureOptions = Field(default_factory=FixtureOptions)

    @property
    def effective_cluster(self) -> str:
        return self.cluster_id or self.external_id

    def content(self) -> dict[str, Any]:
        """The task-defining content; changes here make a case 'changed' across versions."""
        return {
            "input": self.input,
            "episode": [step.model_dump(mode="json") for step in self.episode],
            "expected": self.expected,
            "alternatives": self.alternatives,
            "fixture_options": self.fixture_options.model_dump(mode="json", exclude_none=True),
        }

    def case_hash(self) -> str:
        return content_hash(self.content())

    def stored(self, ordinal: int) -> dict[str, Any]:
        return {
            "ordinal": ordinal,
            "external_id": self.external_id,
            "purpose": self.purpose,
            "severity": self.severity.value,
            "cluster_id": self.effective_cluster,
            "weight": self.weight,
            "split": self.split.value,
            "tags": self.tags,
            **{k: v for k, v in self.content().items()},
            "evidence": self.evidence,
            "case_hash": self.case_hash(),
        }


class ToolFixture(_Strict):
    when: dict[str, Any] = Field(default_factory=dict)
    returns: Any = None


class ToolContract(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str = ""
    arguments_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    fixtures: list[ToolFixture] = Field(default_factory=list)
    default_return: Any = None
    effects: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False

    @field_validator("arguments_schema")
    @classmethod
    def _schema(cls, value):
        jsonschema.Draft202012Validator.check_schema(value)
        return value


class CorpusDocument(_Strict):
    id: str = Field(pattern=EXTERNAL_ID)
    title: str = ""
    text: str = Field(min_length=1)


class GraderSpec(_Strict):
    name: str = Field(pattern=SLUG)
    kind: GraderKind
    mandatory: bool | None = None
    checks: list[str] = Field(default_factory=list)
    rubric: str = ""
    judge: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_mandatory(self) -> bool:
        if self.mandatory is not None:
            return self.mandatory
        return self.kind in (GraderKind.DETERMINISTIC, GraderKind.STRUCTURED)

    @model_validator(mode="after")
    def _kind_fields(self):
        if self.kind in (GraderKind.DETERMINISTIC, GraderKind.STRUCTURED):
            if not self.checks:
                raise ValueError("deterministic graders need at least one check")
            unknown = [c for c in self.checks if c not in CHECKS]
            if unknown:
                raise ValueError(f"unknown checks {unknown}; known: {sorted(CHECKS)}")
        if self.kind in (GraderKind.MODEL, GraderKind.PAIRWISE) and not self.rubric.strip():
            raise ValueError(f"{self.kind.value} graders need a rubric")
        if self.kind is GraderKind.EXTERNAL and not self.config.get("plugin"):
            raise ValueError("external graders need config.plugin")
        return self


class PassRuleSpec(_Strict):
    mandatory_graders: list[str] = Field(min_length=1)


class DatasetSpec(_Strict):
    name: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, ge=1)
    description: str = ""
    pass_rule: PassRuleSpec | None = None
    cases: list[Any] = Field(default_factory=list)


class ScenarioDocument(_Strict):
    schema_version: Literal[1]
    name: str = Field(min_length=1, max_length=200)
    pack: Pack
    contract: str = Field(min_length=1)
    description: str = ""
    slice_keys: list[str] = Field(default_factory=list)
    critical_invariants: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    allowed_labels: list[str] = Field(default_factory=list)
    event_definition: str | None = None
    tools: list[ToolContract] = Field(default_factory=list)
    corpus: list[CorpusDocument] = Field(default_factory=list)
    graders: list[GraderSpec] = Field(min_length=1)
    dataset: DatasetSpec | None = None

    @field_validator("input_schema", "output_schema")
    @classmethod
    def _json_schema(cls, value):
        if value:
            jsonschema.Draft202012Validator.check_schema(value)
        return value

    def definition(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"dataset"})

    def scenario_hash(self) -> str:
        return hash_payload(self.definition())

    def pass_rule(self) -> dict[str, Any]:
        if self.dataset and self.dataset.pass_rule:
            mandatory = list(self.dataset.pass_rule.mandatory_graders)
        else:
            mandatory = [g.name for g in self.graders if g.is_mandatory]
        return {"policy": "all_mandatory_pass", "mandatory_graders": mandatory}


@dataclass
class Issue:
    path: str
    message: str
    code: str = "invalid"
    row: int | None = None
    external_id: str | None = None


@dataclass
class ValidationReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    scenario: ScenarioDocument | None = None
    cases: list[CaseModel] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.scenario is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [asdict(i) for i in self.errors],
            "warnings": [asdict(i) for i in self.warnings],
            "case_count": len(self.cases),
        }


def _path(prefix: str, loc) -> str:
    out = prefix
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _pydantic_issues(exc: ValidationError, prefix: str, row: int | None = None,
                     external_id: str | None = None) -> list[Issue]:
    return [Issue(_path(prefix, err["loc"]), err["msg"], err["type"], row, external_id) for err in exc.errors()]


def validate_document(raw: Any) -> ValidationReport:
    report = ValidationReport()
    if not isinstance(raw, dict):
        report.errors.append(Issue("", "a scenario document must be a mapping/object", "type_error"))
        return report
    dataset_raw = raw.get("dataset")
    raw_cases: Any = []
    header = dict(raw)
    if isinstance(dataset_raw, dict):
        raw_cases = dataset_raw.get("cases", [])
        header["dataset"] = {**dataset_raw, "cases": []}
    try:
        report.scenario = ScenarioDocument.model_validate(header)
    except ValidationError as exc:
        report.errors.extend(_pydantic_issues(exc, ""))
    if not isinstance(raw_cases, list):
        report.errors.append(Issue("dataset.cases", "cases must be a list", "type_error"))
        raw_cases = []
    pack = Pack(raw["pack"]) if raw.get("pack") in {p.value for p in Pack} else None
    report.cases = validate_cases(raw_cases, report, pack=pack, scenario=report.scenario)
    if report.scenario is not None:
        _scenario_checks(report.scenario, report)
    return report


def validate_cases(raw_cases: list[Any], report: ValidationReport, pack: Pack | None,
                   scenario: ScenarioDocument | None, prefix: str = "dataset.cases") -> list[CaseModel]:
    cases: list[CaseModel] = []
    seen_ids: dict[str, int] = {}
    seen_hashes: dict[str, str] = {}
    cluster_splits: dict[str, set[str]] = {}
    spec = PACK_SPECS.get(pack) if pack else None
    for row, raw_case in enumerate(raw_cases):
        path = f"{prefix}[{row}]"
        external_id = raw_case.get("external_id") if isinstance(raw_case, dict) else None
        try:
            case = CaseModel.model_validate(raw_case)
        except ValidationError as exc:
            report.errors.extend(_pydantic_issues(exc, path, row, external_id))
            continue
        row_errors_before = len(report.errors)
        for loc, message in episode_errors(case.episode):
            report.errors.append(Issue(_path(f"{path}.episode", loc), message, "episode", row, case.external_id))
        if spec is not None:
            _pack_case_checks(case, spec, scenario, path, row, report)
        if case.external_id in seen_ids:
            report.errors.append(Issue(f"{path}.external_id",
                                       f"duplicate external_id (also row {seen_ids[case.external_id]})",
                                       "duplicate_id", row, case.external_id))
        else:
            seen_ids[case.external_id] = row
        digest = case.case_hash()
        if digest in seen_hashes:
            report.warnings.append(Issue(path, f"same content as case {seen_hashes[digest]!r}",
                                         "duplicate_content", row, case.external_id))
        else:
            seen_hashes[digest] = case.external_id
        cluster_splits.setdefault(case.effective_cluster, set()).add(case.split.value)
        if len(report.errors) == row_errors_before:
            cases.append(case)
    for cluster, splits in sorted(cluster_splits.items()):
        if len(splits) > 1:
            report.errors.append(Issue(prefix, f"cluster {cluster!r} spans splits {sorted(splits)}; split by "
                                               "cluster so related cases cannot leak across splits",
                                       "cluster_split_leak"))
    return cases


def _pack_case_checks(case: CaseModel, spec, scenario: ScenarioDocument | None, path: str, row: int,
                      report: ValidationReport) -> None:
    def err(sub: str, message: str, code: str = "pack") -> None:
        report.errors.append(Issue(f"{path}{sub}", message, code, row, case.external_id))

    try:
        spec.input_model.model_validate(case.input)
    except ValidationError as exc:
        report.errors.extend(_pydantic_issues(exc, f"{path}.input", row, case.external_id))
    expected = None
    try:
        expected = spec.expected_model.model_validate(case.expected)
    except ValidationError as exc:
        report.errors.extend(_pydantic_issues(exc, f"{path}.expected", row, case.external_id))
    if spec.requires_episode and not case.episode:
        err(".episode", f"{spec.title} cases need an episode of steps")
    if not spec.requires_episode and case.episode and spec.pack is not Pack.TOOL_AGENT:
        err(".episode", f"{spec.title} cases take 'input', not an episode")
    step_ids = {s.id for s in case.episode}
    if isinstance(expected, MemoryExpected):
        missing = sorted(expected.referenced_steps() - step_ids)
        if missing:
            err(".expected", f"expected refers to unknown steps {missing}")
        unknown = [i for i in expected.invariants if i not in INVARIANTS]
        if unknown:
            err(".expected.invariants", f"unknown invariants {unknown}")
    if scenario is None or expected is None:
        return
    if scenario.input_schema:
        for error in jsonschema.Draft202012Validator(scenario.input_schema).iter_errors(case.input):
            err(".input", f"input_schema: {error.message}", "input_schema")
    if spec.pack is Pack.EXACT_CLASSIFICATION and scenario.allowed_labels:
        labels = set(scenario.allowed_labels)
        if expected.label not in labels:
            err(".expected.label", f"label {expected.label!r} is not in allowed_labels")
        bad = [a for a in case.alternatives if a not in labels]
        if bad:
            err(".alternatives", f"alternatives {bad} are not in allowed_labels")
    if spec.pack is Pack.RAG:
        corpus_ids = {d.id for d in scenario.corpus}
        missing = [d for d in list(expected.relevant_ids) + list(expected.relevance) if d not in corpus_ids]
        if missing:
            err(".expected.relevant_ids", f"documents {sorted(set(missing))} are not in the scenario corpus")
    if isinstance(expected, ToolAgentExpected):
        tool_names = {t.name for t in scenario.tools}
        missing = sorted(expected.tool_names() - tool_names)
        if missing:
            err(".expected", f"tools {missing} are not declared in the scenario")
    if spec.pack is Pack.PROBABILITY_CALIBRATION and not scenario.event_definition:
        err("", "probability cases need a scenario event_definition", "scenario")
    missing_tags = [k for k in scenario.slice_keys if k not in case.tags]
    if missing_tags:
        report.warnings.append(Issue(f"{path}.tags", f"missing slice tags {missing_tags}", "slice_tag", row,
                                     case.external_id))


def _scenario_checks(scenario: ScenarioDocument, report: ValidationReport) -> None:
    names = [g.name for g in scenario.graders]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        report.errors.append(Issue("graders", f"duplicate grader names {duplicates}", "duplicate_grader"))
    rule = scenario.pass_rule()
    if not rule["mandatory_graders"]:
        report.errors.append(Issue("graders", "at least one grader must be mandatory for the pass rule",
                                   "pass_rule"))
    unknown = [g for g in rule["mandatory_graders"] if g not in names]
    if unknown:
        report.errors.append(Issue("dataset.pass_rule.mandatory_graders", f"unknown graders {unknown}",
                                   "pass_rule"))
    bad_invariants = [i for i in scenario.critical_invariants if i not in INVARIANTS]
    if bad_invariants:
        report.errors.append(Issue("critical_invariants", f"unknown invariants {bad_invariants}; known: "
                                                          f"{sorted(INVARIANTS)}", "invariant"))
    for index, grader in enumerate(scenario.graders):
        for check in grader.checks:
            packs = CHECKS[check][0]
            if packs is not None and scenario.pack not in packs:
                report.warnings.append(Issue(f"graders[{index}].checks", f"check {check!r} is not designed for "
                                                                         f"the {scenario.pack.value} pack",
                                             "check_pack"))
    if scenario.pack is Pack.EXACT_CLASSIFICATION and not scenario.allowed_labels:
        report.errors.append(Issue("allowed_labels", "classification scenarios must list allowed_labels",
                                   "scenario"))
    if scenario.pack is Pack.PROBABILITY_CALIBRATION and not scenario.event_definition:
        report.errors.append(Issue("event_definition", "name the binary event being predicted", "scenario"))
    tool_names = [t.name for t in scenario.tools]
    if len(set(tool_names)) != len(tool_names):
        report.errors.append(Issue("tools", "tool names must be unique", "scenario"))
    corpus_ids = [d.id for d in scenario.corpus]
    if len(set(corpus_ids)) != len(corpus_ids):
        report.errors.append(Issue("corpus", "corpus document ids must be unique", "scenario"))


def dataset_hash(scenario_hash: str, name: str, pass_rule: dict, cases: list[CaseModel]) -> str:
    return content_hash({
        "scenario_hash": scenario_hash,
        "name": name,
        "pass_rule": pass_rule,
        "cases": [case.stored(i) for i, case in enumerate(cases)],
    })
