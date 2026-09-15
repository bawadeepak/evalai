"""Target adapter contracts.

Capabilities are declared per model and endpoint as ``supported``,
``unsupported`` or ``unknown``, each with the source of the claim and when it
was verified. Requested unsupported settings fail validation; unknown settings
need a connection probe or explicit experimental mode (recorded in the
manifest). Parameters are never dropped silently.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from eval_triage.domain.enums import CapabilityState

CAPABILITY_KEYS = (
    "structured_output", "tools", "images", "temperature", "top_p", "seed", "token_logprobs", "prompt_logprobs",
    "usage", "state_inspection", "isolation", "cancellation", "episodes", "retrieval",
)

#: Request parameter -> capability that must be supported to send it.
PARAMETER_CAPABILITIES = {
    "temperature": "temperature", "top_p": "top_p", "seed": "seed", "logprobs": "token_logprobs",
    "top_logprobs": "token_logprobs",
}


@dataclass
class Capability:
    state: CapabilityState
    source: str
    verified_at: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "source": self.source, "verified_at": self.verified_at, "note": self.note}


def cap(state: str | CapabilityState, source: str, note: str = "", verified_at: str | None = None) -> Capability:
    return Capability(CapabilityState(state), source, verified_at, note)


@dataclass
class TargetRequest:
    messages: list[dict[str, Any]]
    parameters: dict[str, Any] = field(default_factory=dict)
    response_format: dict[str, Any] | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    stage: str = "target"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetResult:
    status: str  # success | provider_error | timeout | invalid_output | unsupported | cancelled
    text: str | None = None
    content_blocks: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None
    refusal: str | None = None
    truncated: bool = False
    request_id: str | None = None
    actual_model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    logprobs: list[dict[str, Any]] | None = None
    raw_request: dict[str, Any] | None = None
    raw_response: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    retryable: bool = False
    latency_ms: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunContext:
    run_id: str
    trial_id: str
    candidate_key: str
    repeat_index: int
    case_external_id: str
    attempt_index: int
    data_dir: Path
    fixture_options: dict[str, Any] = field(default_factory=dict)
    is_demo: bool = False
    cancel_requested: Callable[[], bool] = lambda: False


@dataclass
class TargetConfig:
    """Resolved, immutable target configuration (a TargetConfigVersion row as a value)."""

    id: str
    name: str
    adapter: str
    adapter_version: str
    endpoint_type: str = ""
    model: str = ""
    base_url: str | None = None
    credential_ref: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    prompt_template: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)
    memory_config: dict[str, Any] = field(default_factory=dict)
    experimental: bool = False

    @classmethod
    def from_row(cls, row) -> TargetConfig:
        return cls(id=row.id, name=row.name, adapter=row.adapter, adapter_version=row.adapter_version,
                   endpoint_type=row.endpoint_type, model=row.model, base_url=row.base_url,
                   credential_ref=row.credential_ref, parameters=dict(row.parameters or {}),
                   prompt_template=row.prompt_template or "", tools=list(row.tools or []),
                   memory_config=dict(row.memory_config or {}), experimental=bool(row.experimental))

    def hash_payload(self) -> dict[str, Any]:
        return {"adapter": self.adapter, "adapter_version": self.adapter_version,
                "endpoint_type": self.endpoint_type, "model": self.model, "base_url": self.base_url,
                "credential_ref": self.credential_ref, "parameters": self.parameters,
                "prompt_template": self.prompt_template, "tools": self.tools, "memory_config": self.memory_config,
                "experimental": self.experimental}


class TargetAdapter(Protocol):
    name: str
    version: str

    def capabilities(self, config: TargetConfig) -> dict[str, Capability]: ...

    async def prepare(self, config: TargetConfig, context: RunContext) -> Any: ...

    async def execute(self, request: TargetRequest, session: Any) -> TargetResult: ...

    async def inspect_state(self, session: Any) -> dict[str, Any] | None: ...

    async def close(self, session: Any) -> None: ...


class EpisodeBackend(Protocol):
    """Stateful memory backend used for ``memory_lifecycle`` episodes."""

    name: str
    version: str

    async def prepare(self, stores: list[str], context: RunContext) -> Any: ...

    async def execute_action(self, session: Any, step: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]: ...

    async def inspect_state(self, session: Any, store: str) -> dict[str, Any]: ...

    async def close(self, session: Any) -> dict[str, Any]: ...
