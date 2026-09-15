"""Plugin interface and the normalized external-result schema.

Every integration declares an id and version, the packs it supports, the
schema of the input it accepts, the normalized result schema it produces and a
capability check. Imported records keep their upstream identifiers, and the
original file is kept as an artifact. External numeric scores are recorded as
scores with their own definition — never as probabilities.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PluginUnavailable(RuntimeError):
    """The optional dependency or explicit configuration for a plugin is missing."""


class PluginInputError(ValueError):
    """The supplied file is not a valid input for this plugin."""

    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


class Assertion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    status: Literal["pass", "fail", "error", "skipped"]
    reason: str = ""
    value: Any = None
    score: float | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class ExternalScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: float | str | bool | None
    kind: Literal["numeric", "binary", "label", "text"]
    definition: str
    implementation_version: str
    judge: dict[str, Any] | None = None
    #: External scores are never probabilities of an event; the field exists so
    #: every consumer can check it rather than assume.
    is_probability: Literal[False] = False
    note: str = ""


class NormalizedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upstream_id: str = Field(min_length=1, max_length=200)
    case_external_id: str | None = None
    epoch: int | None = None
    provider: str | None = None
    input: dict[str, Any]
    expected: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    status: Literal["pass", "fail", "error", "unscored"]
    assertions: list[Assertion] = Field(default_factory=list)
    scores: list[ExternalScore] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plugin: str
    plugin_version: str
    source_version: str | None = None
    source_identity: dict[str, Any]
    results: list[NormalizedResult]
    summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def summarize(results: list[NormalizedResult]) -> dict[str, Any]:
    counts = {"pass": 0, "fail": 0, "error": 0, "unscored": 0}
    for r in results:
        counts[r.status] += 1
    return {"results": len(results), **counts,
            "providers": sorted({r.provider for r in results if r.provider}),
            "note": "Counts are the upstream tool's own verdicts; they are not re-graded by Eval Triage."}


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def module_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:  # noqa: BLE001 - absent or unreadable metadata
        return None


def require(module: str, install: str):
    """Import an optional dependency or raise PluginUnavailable with install guidance."""
    if not module_available(module):
        raise PluginUnavailable(f"{module} is not installed ({install})")
    return importlib.import_module(module)


@dataclass(frozen=True)
class PluginInfo:
    id: str
    version: str
    title: str
    purpose: str
    supported_packs: tuple[str, ...]
    input_description: str
    input_schema: dict[str, Any]
    operations: tuple[str, ...]
    install: str
    checks: dict[str, Any] = field(default_factory=dict)

    def describe(self, capabilities: dict[str, Any]) -> dict[str, Any]:
        return {"id": self.id, "version": self.version, "title": self.title, "purpose": self.purpose,
                "supported_packs": list(self.supported_packs), "input": self.input_description,
                "input_schema": self.input_schema, "result_schema": NormalizedResult.model_json_schema(),
                "operations": list(self.operations), "install": self.install, "capabilities": capabilities}
