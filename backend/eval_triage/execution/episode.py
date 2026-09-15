"""Sequential episode runner for stateful (memory lifecycle) scenarios.

Each step runs with its own timeout and records a ``StepOutput``. Steps that
depend on a failed step are skipped with a reason. A **mutating** step that
times out has unknown completion: the episode stops as ``indeterminate`` and is
never replayed in the same store. Generation uses a separately configured
adapter (MemoryAI's recall returns context, not an answer) unless the backend
itself handles generation (demo).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import TypeAdapter

from eval_triage.adapters.base import TargetResult
from eval_triage.domain.episode import MUTATING_ACTIONS, Step, step_dependencies, step_timeout
from eval_triage.domain.refs import RefError, resolve_ref

_steps = TypeAdapter(list[Step])

GenerateCall = Callable[[str, list[dict[str, str]]], Awaitable[TargetResult]]


async def run_episode(backend, case: dict[str, Any], *, prepare_kwargs: dict[str, Any], context,
                      generate: GenerateCall | None) -> dict[str, Any]:
    steps = _steps.validate_python(case.get("episode") or [])
    stores = sorted({s.store for s in steps}) or ["main"]
    session = await backend.prepare(stores, context, **prepare_kwargs)
    outputs: dict[str, Any] = {}
    event_ids: dict[str, list[int]] = {}
    failed: set[str] = set()
    records: list[dict[str, Any]] = []
    status, error = "ok", None
    try:
        for step in steps:
            raw = step.model_dump(mode="json")
            record: dict[str, Any] = {"step_id": step.id, "action": step.action, "store": step.store,
                                      "status": "ok", "output": {}, "new_event_ids": [], "error": None,
                                      "skip_reason": None, "elapsed_ms": None}
            if status == "indeterminate":
                record.update(status="skipped", skip_reason="episode ended: an earlier mutation has unknown outcome")
                records.append(record)
                continue
            blocked = step_dependencies(step) & failed
            if blocked:
                record.update(status="skipped", skip_reason=f"depends on failed step(s) {sorted(blocked)}")
                failed.add(step.id)
                records.append(record)
                continue
            resolved: dict[str, Any] = {}
            target = getattr(step.args, "step", None)
            if target:
                ids = event_ids.get(target) or []
                resolved["target_event_id"] = ids[0] if ids else None
                resolved["target_step"] = target
            started = time.monotonic()
            try:
                if step.action == "generate" and not getattr(backend, "handles_generate", False):
                    context_text = resolve_ref(step.args.context_ref, outputs) if step.args.context_ref else None
                    if generate is None:
                        raise RuntimeError("no generation target is configured for this memory episode")
                    from eval_triage.execution.prompts import memory_answer_messages

                    result = await generate(step.id, memory_answer_messages(step.args.question, context_text,
                                                                            step.args.system_prompt))
                    if result.status != "success":
                        raise _StepFailure(result.status, result.error or {"message": "generation failed"})
                    out = {"text": result.text, "actual_model": result.actual_model, "request_id": result.request_id}
                else:
                    if step.action == "generate" and step.args.context_ref:
                        resolved["context"] = resolve_ref(step.args.context_ref, outputs)
                    out = await asyncio.wait_for(backend.execute_action(session, raw, resolved),
                                                 timeout=step_timeout(step))
                record["output"] = out
                record["new_event_ids"] = list(out.get("new_event_ids", []))
                outputs[step.id] = out
                event_ids[step.id] = record["new_event_ids"]
            except TimeoutError:
                if step.action in MUTATING_ACTIONS:
                    record.update(status="indeterminate", error={
                        "code": "mutation_timeout", "message": f"{step.action} timed out; completion is unknown "
                                                               "and the step will not be replayed in this store"})
                    status, error = "indeterminate", record["error"]
                else:
                    record.update(status="timeout", error={"code": "timeout", "message": f"{step.action} timed out"})
                failed.add(step.id)
            except _StepFailure as exc:
                record.update(status="error", error={"code": exc.status, **exc.error})
                failed.add(step.id)
            except RefError as exc:
                record.update(status="error", error={"code": "reference_error", "message": str(exc)})
                failed.add(step.id)
            except Exception as exc:  # noqa: BLE001 - backend failures are recorded as step errors
                record.update(status="error", error={"code": type(exc).__name__, "message": str(exc)[:500]})
                failed.add(step.id)
            record["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            records.append(record)
        final_states = {}
        if status != "indeterminate":
            for store in stores:
                try:
                    final_states[store] = await backend.inspect_state(session, store)
                except Exception as exc:  # noqa: BLE001
                    final_states[store] = None
                    error = error or {"code": "state_capture_failed", "message": str(exc)[:500]}
    finally:
        close_info = await backend.close(session)
    answers = [r["output"].get("text") for r in records if r["action"] == "generate" and r["status"] == "ok"]
    errored = [r for r in records if r["status"] in ("error", "timeout")]
    if status != "indeterminate" and errored:
        status = "error"
        error = error or errored[0]["error"]
    return {"status": status, "error": error, "steps": records, "stores": final_states,
            "text": answers[-1] if answers else None, "event_ids": event_ids, "close": close_info}


class _StepFailure(Exception):
    def __init__(self, status: str, error: dict[str, Any]) -> None:
        super().__init__(status)
        self.status = status
        self.error = error
