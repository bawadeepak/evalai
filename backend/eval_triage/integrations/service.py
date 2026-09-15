"""Persist and read normalized external results (Inspect logs, Promptfoo results).

The original file is stored as an artifact linked to the import. If it contains
secret-like values it is stored redacted instead, and the import records that.
Normalized rows are redacted before storage. Imports are immutable.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select

from eval_triage.artifacts.records import store_bytes, store_json
from eval_triage.db.models import ExternalImport, ExternalResult
from eval_triage.db.types import iso, new_id
from eval_triage.integrations.base import NormalizedImport
from eval_triage.security.redaction import redact


def save_import(session, store, project_id: str, normalized: NormalizedImport, raw: bytes, *,
                filename: str | None = None, run_info: dict[str, Any] | None = None,
                is_demo: bool = False) -> ExternalImport:
    import_id = new_id()
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    redacted_value, _ = redact(parsed) if parsed is not None else (None, {})
    original_redacted = parsed is not None and redacted_value != parsed
    if original_redacted:
        artifact = store_json(session, store, redacted_value, kind="external_original",
                              entity_type="external_import", entity_id=import_id, role="original",
                              redact_secrets=False)
    else:
        artifact = store_bytes(session, store, raw, media_type="application/json", kind="external_original",
                               entity_type="external_import", entity_id=import_id, role="original")
    identity = redact(normalized.source_identity)[0]
    summary = {**normalized.summary, "original_redacted": original_redacted}
    if run_info:
        summary["run"] = redact(run_info)[0]
    row = ExternalImport(id=import_id, project_id=project_id, plugin=normalized.plugin,
                         plugin_version=normalized.plugin_version, source_version=normalized.source_version,
                         source_identity=identity, artifact_hash=artifact, filename=filename, summary=summary,
                         warnings=list(normalized.warnings), is_demo=is_demo)
    session.add(row)
    session.flush()
    for ordinal, result in enumerate(normalized.results):
        data = redact(result.model_dump(mode="json"))[0]
        session.add(ExternalResult(import_id=import_id, ordinal=ordinal, upstream_id=data["upstream_id"],
                                   case_external_id=data["case_external_id"], epoch=data["epoch"],
                                   provider=data["provider"], input=data["input"], expected=data["expected"],
                                   output=data["output"], status=data["status"], assertions=data["assertions"],
                                   scores=data["scores"], error=data["error"], extra=data["extra"]))
    session.flush()
    return row


def serialize_import(row: ExternalImport, result_count: int | None = None) -> dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "plugin": row.plugin, "plugin_version": row.plugin_version,
            "source_version": row.source_version, "source_identity": row.source_identity,
            "artifact_hash": row.artifact_hash, "filename": row.filename, "summary": row.summary,
            "warnings": row.warnings, "is_demo": row.is_demo, "created_at": iso(row.created_at),
            "result_count": result_count}


def serialize_result(row: ExternalResult) -> dict[str, Any]:
    return {"id": row.id, "ordinal": row.ordinal, "upstream_id": row.upstream_id,
            "case_external_id": row.case_external_id, "epoch": row.epoch, "provider": row.provider,
            "input": row.input, "expected": row.expected, "output": row.output, "status": row.status,
            "assertions": row.assertions, "scores": row.scores, "error": row.error, "extra": row.extra}


def list_imports(session, project_id: str) -> list[dict[str, Any]]:
    counts = dict(session.execute(select(ExternalResult.import_id, func.count()).group_by(ExternalResult.import_id)).all())
    rows = session.scalars(select(ExternalImport).where(ExternalImport.project_id == project_id)
                           .order_by(ExternalImport.created_at.desc())).all()
    return [serialize_import(r, counts.get(r.id, 0)) for r in rows]


def import_results(session, import_id: str, status: str | None = None, limit: int = 200,
                   offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    query = select(ExternalResult).where(ExternalResult.import_id == import_id)
    if status:
        query = query.where(ExternalResult.status == status)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(ExternalResult.ordinal).offset(offset).limit(limit)).all()
    return [serialize_result(r) for r in rows], int(total or 0)
