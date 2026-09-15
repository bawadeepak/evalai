"""Write evidence files and reference them from the database in one step."""

from __future__ import annotations

from typing import Any

from eval_triage.artifacts.store import ArtifactStore
from eval_triage.db.models import Artifact, ArtifactRef
from eval_triage.security.redaction import REDACTION_VERSION, redact


def store_json(session, store: ArtifactStore, value: Any, *, kind: str, entity_type: str | None = None,
               entity_id: str | None = None, role: str | None = None, redact_secrets: bool = True) -> str:
    redaction_version = None
    if redact_secrets:
        value, report = redact(value)
        if report["redacted_keys"] or report["redacted_values"]:
            value = {"_redaction": report, "content": value}
            redaction_version = REDACTION_VERSION
    blob = store.put_json(value)
    return _reference(session, blob, "application/json", kind, redaction_version, entity_type, entity_id, role)


def store_bytes(session, store: ArtifactStore, data: bytes, *, media_type: str, kind: str,
                entity_type: str | None = None, entity_id: str | None = None, role: str | None = None) -> str:
    blob = store.put_bytes(data)
    return _reference(session, blob, media_type, kind, None, entity_type, entity_id, role)


def _reference(session, blob, media_type, kind, redaction_version, entity_type, entity_id, role) -> str:
    if session.get(Artifact, blob.content_hash) is None:
        session.add(Artifact(content_hash=blob.content_hash, relative_path=blob.relative_path,
                             media_type=media_type, byte_length=blob.byte_length, kind=kind,
                             redaction_version=redaction_version))
        session.flush()
    if entity_type and entity_id:
        session.add(ArtifactRef(entity_type=entity_type, entity_id=entity_id, role=role or kind,
                                content_hash=blob.content_hash))
    return blob.content_hash
