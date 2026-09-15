"""Normalised memory evidence shared by the MemoryAI bridge, fake bridge and demo adapter.

These shapes are what graders and the Memory state/Trace tabs consume, so the
demo fixtures, fake bridge and real bridge must all produce them identically.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FactState = Literal["active", "historical", "rejected", "withdrawn", "invalidated"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryFact(_Model):
    memory_id: str | None = None
    claim: str
    state: FactState = "active"
    source_event_id: int | None = None
    source_step: str | None = None
    document_id: str | None = None
    fact_type: str | None = None


class QueueItem(_Model):
    event_id: int
    claim: str
    source_step: str | None = None


class MemoryEvent(_Model):
    id: int
    kind: str
    actor: str
    text: str
    note: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    source_step: str | None = None


class MemoryStateSnapshot(_Model):
    backend: Literal["memoryai", "fake", "demo"]
    store: str = "main"
    exhaustive: bool
    truncated_in_memoryai_state: bool = False
    facts: list[MemoryFact] = Field(default_factory=list)
    queue: list[QueueItem] = Field(default_factory=list)
    events: list[MemoryEvent] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def active_facts(self) -> list[MemoryFact]:
        return [f for f in self.facts if f.state == "active"]


class RecallFactLine(_Model):
    label: str
    text: str
    hit_id: str | None = None
    document_id: str | None = None
    source_step: str | None = None


class RecallWindowLine(_Model):
    label: str
    event_id: int | None = None
    actor: str
    text: str
    retracted: bool = False
    skipped: bool = False
    source_step: str | None = None


class RecallOutput(_Model):
    context: str
    used: int
    budget: int
    facts: list[RecallFactLine] = Field(default_factory=list)
    window: list[RecallWindowLine] = Field(default_factory=list)
    token_counts: dict[str, int] = Field(default_factory=dict)
    tokenizer: str = "cl100k_base"
    recorder: list[dict[str, Any]] = Field(default_factory=list)
    suppressed: list[dict[str, Any]] = Field(default_factory=list)
    dropped: list[dict[str, Any]] = Field(default_factory=list)


class SmalltalkVerdict(_Model):
    outcome: Literal["kept", "skipped", "fallback", "not_checked"]
    reason: str = ""
    method: Literal["rule", "model", "fallback", "disabled", "demo", "fake"] = "model"


class StepOutput(_Model):
    """Recorded outcome of one episode step (stored on the trial, referenced by later steps)."""

    step_id: str
    action: str
    store: str = "main"
    status: Literal["ok", "error", "skipped", "timeout", "indeterminate"]
    elapsed_ms: float | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    new_event_ids: list[int] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    skip_reason: str | None = None
