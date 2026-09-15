"""MemoryAI target adapter: memory episodes run through the isolated bridge.

MemoryAI's ``recall`` returns assembled context, not an answer, so ``generate``
steps use a separately configured generation target. MemoryAI resolves only
local runners (Ollama / llama.cpp); a cloud provider *inside* MemoryAI would
need a separately reviewed MemoryAI patch and is reported as unsupported.
"""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select

from eval_triage.adapters.base import Capability, RunContext, TargetConfig, TargetRequest, TargetResult, cap
from eval_triage.adapters.memoryai.bridge_client import BridgeError, pool
from eval_triage.db.models import MemoryStoreOwnership
from eval_triage.db.types import utcnow
from eval_triage.domain.episode import DEFAULT_TIMEOUT_SECONDS

VERSION = "memoryai-bridge-1"
CLOUD_BOUNDARY = ("MemoryAI resolves only local runners (Ollama or llama.cpp). Running a cloud provider inside "
                  "MemoryAI needs a separately reviewed MemoryAI patch; configure cloud models as the generation "
                  "target instead.")


class MemoryAIAdapter:
    name = "memoryai"
    version = VERSION

    def capabilities(self, config: TargetConfig) -> dict[str, Capability]:
        src = "Eval Triage MemoryAI bridge over memoryai d14259d (as of 2026-09-15)"
        via_generation = "answers come from the configured generation target"
        caps = {
            "episodes": cap("supported", src, "remember, assert, approve, reject, wrong, forget, rebuild, recall"),
            "state_inspection": cap("supported", src, "paged fact listing with truncation detection"),
            "isolation": cap("supported", src, "new data directory, bank and Postgres instance per episode"),
            "cancellation": cap("supported", src, "between steps; a running mutation is never interrupted"),
            "retrieval": cap("supported", src, "MemoryAI recall"),
            "usage": cap("unsupported", src, "MemoryAI does not report token usage"),
            "structured_output": cap("unsupported", src, via_generation),
            "tools": cap("unsupported", src, via_generation),
            "images": cap("unsupported", src),
            "temperature": cap("unsupported", src, via_generation),
            "top_p": cap("unsupported", src, via_generation),
            "seed": cap("unsupported", src),
            "token_logprobs": cap("unsupported", src),
            "prompt_logprobs": cap("unsupported", src),
            "cloud_models_inside_memoryai": cap("unsupported", src, CLOUD_BOUNDARY),
        }
        for value in caps.values():
            value.verified_at = "2026-09-15"
        return caps

    async def prepare(self, config: TargetConfig, context: RunContext) -> dict[str, Any]:
        return {"config": config}

    async def execute(self, request: TargetRequest, session: Any) -> TargetResult:
        return TargetResult(status="unsupported", error={
            "code": "episodes_only", "message": "the MemoryAI adapter runs memory episodes, not single prompts"})

    async def inspect_state(self, session: Any) -> None:
        return None

    async def close(self, session: Any) -> None:
        return None


class BridgeBackend:
    """EpisodeBackend implemented by the bridge subprocess."""

    name = "memoryai-bridge"
    version = VERSION
    handles_generate = False

    def __init__(self, app, config: TargetConfig) -> None:
        self.app = app
        self.config = config
        self.memory = dict(config.memory_config or {})
        self.backend = self.memory.get("backend", "real")

    async def prepare(self, stores: list[str], context: RunContext) -> dict[str, Any]:
        key = (self.config.id, self.backend)
        process = await pool().acquire(self.app.settings, key, self.backend, self.memory.get("bridge_env"))
        fault = (context.fixture_options or {}).get("fault_injection")
        episode_id = f"{context.run_id[:8]}-{context.trial_id[:8]}-a{context.attempt_index}"
        nonce = secrets.token_hex(16)
        try:
            result = await process.request("prepare", {
                "episode_id": episode_id, "stores": stores, "nonce": nonce,
                "settings": {k: self.memory.get(k) for k in ("llm_model", "consolidation_model", "llm_base_url",
                                                              "small_talk_filter") if k in self.memory},
                "owner": {"run_id": context.run_id, "trial_id": context.trial_id},
                "fault_injection": fault, "test_mode": bool(fault),
            }, timeout=float(self.memory.get("prepare_timeout_seconds", 600)))
        except BaseException:
            await pool().release(key, process, healthy=False)
            raise
        self._record_ownership(context, result, nonce)
        return {"process": process, "key": key, "session_id": result["session_id"], "nonce": nonce,
                "stores": result["stores"], "event_steps": {}, "fault_injection": fault, "healthy": True}

    def _record_ownership(self, context: RunContext, result: dict[str, Any], nonce: str) -> None:
        with self.app.db.write() as session:
            for info in result["stores"].values():
                session.add(MemoryStoreOwnership(run_id=context.run_id, trial_id=context.trial_id,
                                                 data_dir=info["data_dir"], instance=info["instance"],
                                                 bank=info["bank"], nonce=nonce, state="active"))

    def _annotate(self, session: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
        steps = session["event_steps"]
        for line in output.get("facts", []):
            if isinstance(line, dict) and "source_event_id" in line:
                line["source_step"] = steps.get(line.get("source_event_id"))
        for line in output.get("window", []):
            line["source_step"] = steps.get(line.get("event_id"))
        for event in output.get("events", []) if output.get("exhaustive") is not None else []:
            event["source_step"] = steps.get(event.get("id"))
        return output

    async def execute_action(self, session: dict[str, Any], step: dict[str, Any],
                             resolved: dict[str, Any]) -> dict[str, Any]:
        timeout = step.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS.get(step["action"], 120)
        clean = {k: v for k, v in resolved.items() if k in ("target_event_id", "target_step")}
        try:
            output = await session["process"].request("execute_action", {
                "session_id": session["session_id"], "step": step, "resolved": clean}, timeout=float(timeout) + 5)
        except (TimeoutError, BridgeError):
            session["healthy"] = False
            raise
        for event_id in output.get("new_event_ids", []):
            session["event_steps"][event_id] = step["id"]
        if step["action"] == "inspect_state":
            for fact in output.get("facts", []):
                fact["source_step"] = session["event_steps"].get(fact.get("source_event_id"))
        output = self._annotate(session, output)
        if session.get("fault_injection"):
            output["fault_injection"] = session["fault_injection"]
        return output

    async def inspect_state(self, session: dict[str, Any], store: str) -> dict[str, Any]:
        snapshot = await session["process"].request("inspect_state", {"session_id": session["session_id"],
                                                                      "store": store}, timeout=300)
        for fact in snapshot.get("facts", []):
            fact["source_step"] = session["event_steps"].get(fact.get("source_event_id"))
        for event in snapshot.get("events", []):
            event["source_step"] = session["event_steps"].get(event.get("id"))
        return snapshot

    async def close(self, session: dict[str, Any]) -> dict[str, Any]:
        process, key = session["process"], session["key"]
        retain = bool(self.memory.get("retain_stores", True))
        report: dict[str, Any] = {"retained": retain}
        healthy = session.get("healthy", True) and process.alive
        try:
            if healthy:
                report = await process.request("close", {"session_id": session["session_id"], "retain": retain,
                                                         "nonce": session["nonce"]}, timeout=300)
            else:
                report = {"error": "bridge was not healthy; the store was left in place for inspection",
                          "stderr": process.diagnostics()}
        finally:
            await pool().release(key, process, healthy=healthy)
        self._update_ownership(session, report, retain)
        return report

    def _update_ownership(self, session: dict[str, Any], report: dict[str, Any], retain: bool) -> None:
        stores = report.get("stores") or {}
        with self.app.db.write() as db:
            for name, info in session["stores"].items():
                row = db.scalars(select(MemoryStoreOwnership).where(
                    MemoryStoreOwnership.instance == info["instance"])).first()
                if row is None:
                    continue
                closed = stores.get(name) or {}
                row.disk_bytes = closed.get("disk_bytes")
                if closed.get("drop"):
                    row.state, row.dropped_at = "dropped", utcnow()
                else:
                    row.state = "retained" if closed else "orphaned"


def memory_backend(app, config: TargetConfig) -> BridgeBackend:
    return BridgeBackend(app, config)
