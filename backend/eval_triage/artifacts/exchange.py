"""Portable project export and safe import.

Archive layout (ZIP)::

    manifest.json            schema version, source identity, counts, checksums, redaction
    records/<table>.json     one JSON array per table
    artifacts/<sha256>       evidence files (omitted when text redaction is requested)

Import safety: size and member-count caps, no absolute paths, ``..``,
backslashes, symlinks or executable/code payloads, strict JSON (no NaN), and
every checksum verified before anything is written. Imports always create a new
project with fresh ids (a namespace) that records the source identity; existing
immutable records are never overwritten, and imported endpoint URLs are only
configuration — nothing is called.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import uuid
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from eval_triage import SCHEMA_VERSION, __version__
from eval_triage.artifacts.store import ArtifactStore
from eval_triage.db import models as m
from eval_triage.db.types import iso, utcnow
from eval_triage.domain.importers import ImportFormatError, _no_duplicates, _reject_constant
from eval_triage.statistics.registry import registry_payload

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024
MAX_MEMBERS = 50_000
MEMBER = re.compile(r"^(manifest\.json|records/[a-z_]+\.json|artifacts/[0-9a-f]{64})$")
FORBIDDEN_SUFFIX = re.compile(r"\.(py|pyc|sh|bash|zsh|exe|dll|so|dylib|js|mjs|bat|cmd|ps1|jar|app|pkl|pickle)$", re.I)
REDACTED = "[REDACTED — excluded by the export redaction option]"

# Table -> model, in dependency order. Foreign keys are remapped using ID_COLUMNS.
TABLES: list[tuple[str, type]] = [
    ("target_config_versions", m.TargetConfigVersion), ("grader_versions", m.GraderVersion),
    ("scenario_versions", m.ScenarioVersion), ("dataset_versions", m.DatasetVersion), ("cases", m.Case),
    ("release_policies", m.ReleasePolicy), ("runs", m.Run), ("run_candidates", m.RunCandidate),
    ("grading_runs", m.GradingRun), ("trials", m.Trial), ("attempts", m.Attempt), ("grades", m.Grade),
    ("trial_outcomes", m.TrialOutcome), ("reviews", m.Review), ("comparisons", m.Comparison),
    ("calibration_versions", m.CalibrationVersion), ("probability_records", m.ProbabilityRecord),
    ("artifact_refs", m.ArtifactRef),
]
ID_COLUMNS: dict[str, dict[str, str]] = {
    "target_config_versions": {"parent_id": "target_config_versions"},
    "grader_versions": {"judge_config_id": "target_config_versions", "parent_id": "grader_versions"},
    "scenario_versions": {"parent_id": "scenario_versions"},
    "dataset_versions": {"scenario_id": "scenario_versions", "parent_id": "dataset_versions"},
    "cases": {"dataset_id": "dataset_versions"},
    "runs": {"scenario_id": "scenario_versions", "dataset_id": "dataset_versions", "parent_run_id": "runs"},
    "run_candidates": {"run_id": "runs", "target_config_id": "target_config_versions"},
    "grading_runs": {"run_id": "runs"},
    "trials": {"run_id": "runs", "case_id": "cases", "selected_attempt_id": "attempts"},
    "attempts": {"trial_id": "trials"},
    "grades": {"grading_run_id": "grading_runs", "trial_id": "trials", "grader_id": "grader_versions"},
    "trial_outcomes": {"grading_run_id": "grading_runs", "trial_id": "trials"},
    "reviews": {"trial_id": "trials", "supersedes_id": "reviews"},
    "comparisons": {"baseline_run_id": "runs", "candidate_run_id": "runs", "policy_id": "release_policies"},
    "calibration_versions": {},
    "probability_records": {"dataset_id": "dataset_versions", "case_id": "cases", "trial_id": "trials"},
    "artifact_refs": {},
}
LIST_COLUMNS = {("scenario_versions", "grader_refs"): "grader_versions",
                ("grading_runs", "grader_ids"): "grader_versions", ("reviews", "grade_ids"): "grades",
                ("comparisons", "grading_run_ids"): "grading_runs"}
ENTITY_TABLES = {"attempt": "attempts", "trial": "trials"}


class ArchiveError(ValueError):
    pass


def _row_dict(row) -> dict[str, Any]:
    out = {}
    for attr in sa_inspect(row).mapper.column_attrs:
        value = getattr(row, attr.key)
        out[attr.key] = iso(value) if isinstance(value, datetime) else value
    return out


def _dump(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")


def _project_rows(session, project_id: str) -> dict[str, list]:
    run_ids = list(session.scalars(select(m.Run.id).where(m.Run.project_id == project_id)))
    dataset_ids = list(session.scalars(select(m.DatasetVersion.id).where(m.DatasetVersion.project_id == project_id)))
    trial_ids = list(session.scalars(select(m.Trial.id).where(m.Trial.run_id.in_(run_ids)))) if run_ids else []
    grading_ids = list(session.scalars(select(m.GradingRun.id).where(m.GradingRun.run_id.in_(run_ids)))) \
        if run_ids else []
    attempt_ids = list(session.scalars(select(m.Attempt.id).where(m.Attempt.trial_id.in_(trial_ids)))) \
        if trial_ids else []

    def rows(model, *where):
        return list(session.scalars(select(model).where(*where))) if all(w is not None for w in where) else []

    by_project = lambda model: rows(model, model.project_id == project_id)  # noqa: E731
    return {
        "target_config_versions": by_project(m.TargetConfigVersion), "grader_versions": by_project(m.GraderVersion),
        "scenario_versions": by_project(m.ScenarioVersion), "dataset_versions": by_project(m.DatasetVersion),
        "cases": rows(m.Case, m.Case.dataset_id.in_(dataset_ids)),
        "release_policies": by_project(m.ReleasePolicy), "runs": by_project(m.Run),
        "run_candidates": rows(m.RunCandidate, m.RunCandidate.run_id.in_(run_ids)),
        "grading_runs": rows(m.GradingRun, m.GradingRun.run_id.in_(run_ids)),
        "trials": rows(m.Trial, m.Trial.id.in_(trial_ids)),
        "attempts": rows(m.Attempt, m.Attempt.id.in_(attempt_ids)),
        "grades": rows(m.Grade, m.Grade.grading_run_id.in_(grading_ids)),
        "trial_outcomes": rows(m.TrialOutcome, m.TrialOutcome.grading_run_id.in_(grading_ids)),
        "reviews": rows(m.Review, m.Review.trial_id.in_(trial_ids)),
        "comparisons": by_project(m.Comparison), "calibration_versions": by_project(m.CalibrationVersion),
        "probability_records": by_project(m.ProbabilityRecord),
        "artifact_refs": rows(m.ArtifactRef, m.ArtifactRef.entity_id.in_(trial_ids + attempt_ids)),
    }


def _redact_text(table: str, record: dict[str, Any]) -> dict[str, Any]:
    if table == "cases":
        record.update(input=REDACTED, episode=[], expected=REDACTED, alternatives=[], evidence=[])
    elif table == "trials":
        record.update(output=None if record.get("output") is None else {"redacted": REDACTED}, steps=[])
    elif table == "grades":
        record.update(explanation=REDACTED, evidence_refs=[], judge_attempts=[])
    elif table == "reviews":
        record.update(explanation=REDACTED)
    return record


def build_export(session, store: ArtifactStore, project_id: str, *, redact_text: bool = False) -> tuple[bytes, dict]:
    project = session.get(m.Project, project_id)
    if project is None:
        raise KeyError(project_id)
    tables = _project_rows(session, project_id)
    members: dict[str, bytes] = {}
    counts = {}
    for table, rows in tables.items():
        records = [_row_dict(r) for r in rows]
        if redact_text:
            records = [_redact_text(table, r) for r in records]
        members[f"records/{table}.json"] = _dump(records)
        counts[table] = len(records)
    artifact_hashes = sorted({r.content_hash for r in tables["artifact_refs"]} |
                             {h for r in tables["trials"] for h in (r.output_artifacts or []) + (r.state_artifacts or [])})
    artifact_rows = [session.get(m.Artifact, h) for h in artifact_hashes]
    members["records/artifacts.json"] = _dump([_row_dict(a) for a in artifact_rows if a and not redact_text])
    if not redact_text:
        for row in artifact_rows:
            if row is not None and store.exists(row.content_hash):
                members[f"artifacts/{row.content_hash}"] = store.read_bytes(row.content_hash)
    members["records/metric_definitions.json"] = _dump(registry_payload())
    manifest = {
        "schema_version": SCHEMA_VERSION, "app": "eval-triage", "app_version": __version__,
        "exported_at": iso(utcnow()),
        "source": {"project_id": project.id, "name": project.name, "description": project.description,
                   "is_demo": project.is_demo},
        "counts": counts, "artifacts": 0 if redact_text else len(artifact_hashes),
        "redaction": ({"text_excluded": True, "note": "Case inputs/expectations, outputs, traces, judge text, "
                                                      "review text and artifact files were excluded."}
                      if redact_text else {"text_excluded": False}),
        "credentials": "Only credential reference names are exported; no secret values exist in the store.",
        "checksums": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(members.items())},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _dump(manifest))
        for name, data in sorted(members.items()):
            archive.writestr(name, data)
    return buffer.getvalue(), {k: manifest[k] for k in ("counts", "artifacts", "redaction", "source")}


def _strict_json(data: bytes, name: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError, ImportFormatError) as exc:
        raise ArchiveError(f"{name}: invalid JSON ({exc})") from exc


def read_archive(data: bytes) -> dict[str, Any]:
    """Validate an archive completely before anything is imported."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ArchiveError("archive exceeds the 200 MB limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("not a valid ZIP archive") from exc
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ArchiveError("too many archive members")
    total = 0
    for info in infos:
        name = info.filename
        if name.startswith("/") or "\\" in name or ".." in name.split("/") or ":" in name:
            raise ArchiveError(f"unsafe path in archive: {name!r}")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise ArchiveError(f"symlinks are not allowed: {name!r}")
        if info.is_dir():
            continue
        if FORBIDDEN_SUFFIX.search(name):
            raise ArchiveError(f"executable or code payloads are not allowed: {name!r}")
        if not MEMBER.fullmatch(name):
            raise ArchiveError(f"unexpected archive member {name!r}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise ArchiveError(f"{name} exceeds the per-file size limit")
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise ArchiveError("archive expands beyond the uncompressed size limit")
    if "manifest.json" not in archive.namelist():
        raise ArchiveError("manifest.json is missing")
    manifest = _strict_json(archive.read("manifest.json"), "manifest.json")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("app") != "eval-triage":
        raise ArchiveError("unsupported archive schema or application")
    checksums = manifest.get("checksums") or {}
    members: dict[str, bytes] = {}
    for info in infos:
        if info.is_dir() or info.filename == "manifest.json":
            continue
        payload = archive.read(info.filename)
        if len(payload) != info.file_size:
            raise ArchiveError(f"{info.filename}: size mismatch")
        expected = checksums.get(info.filename)
        if expected is None or hashlib.sha256(payload).hexdigest() != expected:
            raise ArchiveError(f"{info.filename}: checksum mismatch or not listed in the manifest")
        if info.filename.startswith("artifacts/") and hashlib.sha256(payload).hexdigest() != info.filename[10:]:
            raise ArchiveError(f"{info.filename}: content does not match its address")
        members[info.filename] = payload
    missing = set(checksums) - set(members)
    if missing:
        raise ArchiveError(f"archive is missing listed members: {sorted(missing)[:5]}")
    records = {name[8:-5]: _strict_json(payload, name) for name, payload in members.items()
               if name.startswith("records/")}
    for table, _model in TABLES:
        if not isinstance(records.get(table, []), list):
            raise ArchiveError(f"records/{table}.json must be a list")
    return {"manifest": manifest, "records": records,
            "artifacts": {name[10:]: payload for name, payload in members.items() if name.startswith("artifacts/")}}


def _to_datetime(model, record: dict[str, Any]) -> dict[str, Any]:
    columns = {c.key: c for c in sa_inspect(model).mapper.column_attrs}
    out = {}
    for key, value in record.items():
        if key not in columns:
            raise ArchiveError(f"unknown column {model.__tablename__}.{key}")
        column_type = columns[key].columns[0].type
        if isinstance(value, str) and column_type.__class__.__name__ == "UTCDateTime":
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        out[key] = value
    return out


def import_archive(session, store: ArtifactStore, parsed: dict[str, Any], *, name: str | None = None) -> dict:
    manifest, records = parsed["manifest"], parsed["records"]
    source = manifest["source"]
    project = m.Project(name=name or f"{source['name']} (imported)", description=source.get("description", ""),
                        is_demo=bool(source.get("is_demo")),
                        source_identity={"project_id": source["project_id"], "name": source["name"],
                                         "exported_at": manifest["exported_at"],
                                         "app_version": manifest.get("app_version"),
                                         "redaction": manifest.get("redaction")})
    session.add(project)
    session.flush()
    id_map: dict[str, dict[str, str]] = {table: {} for table, _ in TABLES}
    for table, _model in TABLES:
        for record in records.get(table, []):
            if not isinstance(record.get("id"), str):
                raise ArchiveError(f"{table}: record without id")
            id_map[table][record["id"]] = str(uuid.uuid4())
    logical: dict[str, str] = {}

    def remap(table: str, value: Any, target: str) -> Any:
        if value is None:
            return None
        if value not in id_map[target]:
            raise ArchiveError(f"{table} references a {target} id that is not in the archive")
        return id_map[target][value]

    for digest, payload in parsed["artifacts"].items():
        blob = store.put_bytes(payload)
        if blob.content_hash != digest:
            raise ArchiveError("artifact hash mismatch after write")
    for artifact in records.get("artifacts", []):
        if session.get(m.Artifact, artifact["content_hash"]) is None:
            session.add(m.Artifact(**_to_datetime(m.Artifact, artifact)))
    session.flush()

    inserted = {}
    for table, model in TABLES:
        rows = records.get(table, [])
        for record in rows:
            record = dict(record)
            record["id"] = id_map[table][record["id"]]
            if "project_id" in record:
                record["project_id"] = project.id
            if "logical_id" in record and record["logical_id"]:
                record["logical_id"] = logical.setdefault(f"{table}:{record['logical_id']}", str(uuid.uuid4()))
            for column, target in ID_COLUMNS.get(table, {}).items():
                if column in record:
                    record[column] = remap(table, record[column], target)
            for (tbl, column), target in LIST_COLUMNS.items():
                if tbl == table and isinstance(record.get(column), list):
                    record[column] = [remap(table, v, target) if v else v for v in record[column]]
            if table == "target_config_versions" and (record.get("memory_config") or {}).get(
                    "generation_target_config_id"):
                record["memory_config"] = {**record["memory_config"], "generation_target_config_id": remap(
                    table, record["memory_config"]["generation_target_config_id"], "target_config_versions")}
            if table == "artifact_refs":
                entity_table = ENTITY_TABLES.get(record["entity_type"])
                if entity_table is None:
                    continue
                record["entity_id"] = remap(table, record["entity_id"], entity_table)
            if table == "runs":
                record["manifest"] = {**record["manifest"], "imported_from": {
                    "project_id": source["project_id"], "run_id": next(k for k, v in id_map["runs"].items()
                                                                       if v == record["id"])}}
                record["manifest_hash"] = record["manifest_hash"]
            session.add(model(**_to_datetime(model, record)))
        session.flush()
        inserted[table] = len(rows)
    mapping_hash = store.put_json({"source_project_id": source["project_id"], "id_map": id_map}).content_hash
    return {"project_id": project.id, "inserted": inserted, "id_map_artifact": mapping_hash,
            "note": "Imported into a new project namespace; nothing existing was overwritten and no endpoint "
                    "was contacted."}
