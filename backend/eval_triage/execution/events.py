"""Append-only run events. Persisted before emission; SSE streams them by sequence id."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from eval_triage.db.models import Event

EVENT_TYPES = frozenset({
    "run.queued", "run.started", "trial.started", "attempt.finished", "artifact.created", "grade.created",
    "run.progress", "run.finished", "run.cancelled", "run.error", "grading.started", "grading.finished",
})

_ALLOWED_PAYLOAD_KEYS = frozenset({
    "status", "trial_status", "verdict", "grader", "case", "candidate", "repeat", "attempt", "stage", "reason",
    "counts", "planned", "terminal", "kind", "hash", "grading_run_id", "outcome", "message", "retryable",
})


def sanitize(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Keep events small and free of evidence or secrets: an allow-listed set of short fields."""
    clean: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if key not in _ALLOWED_PAYLOAD_KEYS:
            continue
        if isinstance(value, str):
            value = value[:200]
        clean[key] = value
    return clean


def emit(session, run_id: str | None, type_: str, entity_id: str | None = None,
         payload: dict[str, Any] | None = None) -> Event:
    if type_ not in EVENT_TYPES:
        raise ValueError(f"unknown event type {type_!r}")
    event = Event(run_id=run_id, type=type_, entity_id=entity_id, payload=sanitize(payload))
    session.add(event)
    session.flush()
    return event


def events_after(session, run_id: str, after_seq: int = 0, limit: int = 500) -> list[Event]:
    return list(session.scalars(select(Event).where(Event.run_id == run_id, Event.seq > after_seq)
                                .order_by(Event.seq).limit(limit)))
