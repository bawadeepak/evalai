"""Deterministic demo adapter, demo memory backend and demo judge.

Everything here is **synthetic and clearly labelled**. Outputs come from the
fixture files in ``fixtures/demo`` (stable-wrong, flaky, malformed output,
provider error, absent probabilities, judge failure) or from a generic
fallback derived from the case contract. The repeat index controls variation.
Demo runs never call a provider and every manifest and export says so.

Only the demo adapter receives ``demo_expected`` in request metadata, so it can
produce illustrative outputs for arbitrary fixtures; real adapters never see the
expected answer.
"""

from __future__ import annotations

import asyncio
import json
import time
from functools import lru_cache
from typing import Any

from eval_triage.adapters.base import Capability, RunContext, TargetConfig, TargetRequest, TargetResult, cap
from eval_triage.domain.fixtures import FIXTURES_DIR
from eval_triage.domain.importers import parse_file

VERSION = "demo-1"
_FILLER = {"thanks", "thank", "you", "ok", "okay", "cool", "great", "hi", "hello", "bye", "yes", "no", "sure"}


@lru_cache(maxsize=1)
def demo_outputs() -> dict[str, Any]:
    return {
        "memory": parse_file(FIXTURES_DIR / "demo" / "memory_outputs.yaml"),
        "classification": parse_file(FIXTURES_DIR / "demo" / "routing_outputs.yaml"),
    }


def _scheduled(entry: dict[str, Any] | None, repeat: int) -> Any:
    if not entry:
        return None
    return (entry.get("repeats") or {}).get(str(repeat), entry.get("default"))


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class DemoAdapter:
    name = "demo"
    version = VERSION

    def capabilities(self, config: TargetConfig) -> dict[str, Capability]:
        src = "demo adapter declaration"
        fixed = "accepted and recorded; demo outputs are fixed fixtures and ignore sampling"
        return {
            "structured_output": cap("supported", src),
            "tools": cap("supported", src, "demo returns fixture tool behaviour only"),
            "images": cap("unsupported", src),
            "temperature": cap("supported", src, fixed),
            "top_p": cap("supported", src, fixed),
            "seed": cap("unsupported", src, "demo outputs are fully deterministic by repeat index"),
            "token_logprobs": cap("unsupported", src, "demonstrates the absent-probabilities path"),
            "prompt_logprobs": cap("unsupported", src),
            "usage": cap("supported", src, "approximate character-based token counts"),
            "state_inspection": cap("supported", src),
            "isolation": cap("supported", src),
            "cancellation": cap("supported", src),
            "episodes": cap("supported", src),
            "retrieval": cap("supported", src),
        }

    async def prepare(self, config: TargetConfig, context: RunContext) -> dict[str, Any]:
        return {"config": config, "context": context}

    async def execute(self, request: TargetRequest, session: dict[str, Any]) -> TargetResult:
        config: TargetConfig = session["config"]
        context: RunContext = session["context"]
        started = time.monotonic()
        delay = config.parameters.get("delay_ms")
        if delay:
            await asyncio.sleep(float(delay) / 1000)
        meta = request.metadata
        profile = config.parameters.get("profile", "baseline")
        text, extra, error = self._output(meta, profile, context.repeat_index)
        prompt_chars = sum(len(str(m.get("content", ""))) for m in request.messages)
        common = dict(
            request_id=f"demo-{context.trial_id[:8]}-{context.attempt_index}",
            actual_model=config.model or "demo",
            raw_request={"demo": True, "messages": request.messages, "parameters": request.parameters,
                         "tools": [t.get("name") for t in request.tools]},
            latency_ms=(time.monotonic() - started) * 1000,
        )
        if error:
            return TargetResult(status="provider_error", error={**error, "demo": True},
                                retryable=bool(error.get("retryable")), raw_response={"demo": True, "error": error},
                                **common)
        usage = {"input_tokens": _tokens("x" * prompt_chars), "output_tokens": _tokens(text or ""),
                 "estimated": True}
        return TargetResult(status="success", text=text, stop_reason="end_turn", usage=usage,
                            cost={"amount": 0.0, "currency": "USD", "source": "demo adapter (free)"},
                            raw_response={"demo": True, "text": text}, extra=extra, logprobs=None, **common)

    def _output(self, meta: dict[str, Any], profile: str, repeat: int):
        pack, ext = meta.get("pack"), meta.get("external_id")
        expected = meta.get("demo_expected") or {}
        inp = meta.get("demo_input") or {}
        extra: dict[str, Any] = {}
        if pack == "exact_classification":
            override = _scheduled(demo_outputs()["classification"]["profiles"].get(profile, {}).get(ext), repeat)
            if override and "provider_error" in override:
                return None, extra, override["provider_error"]
            if override and "malformed" in override:
                return override["malformed"], extra, None
            label = (override or {}).get("label", expected.get("label", "other"))
            return json.dumps({"label": label}), extra, None
        if pack == "structured_extraction":
            return json.dumps({"facts": expected.get("facts", [])}), extra, None
        if pack == "reference_answer":
            if expected.get("should_abstain"):
                return "I don't know of anyone who has done that; the premise appears to be false.", extra, None
            return f"{expected.get('reference', '')}", extra, None
        if pack == "rag":
            extra["retrieved_ids"] = list(expected.get("relevant_ids", []))
            if expected.get("should_abstain") or expected.get("intentional_no_answer"):
                return "I don't know; the documents do not say.", extra, None
            return "According to the documents: " + "; ".join(expected.get("answer_contains", [])) + ".", extra, None
        if pack == "robustness_security":
            if expected.get("expected_label"):
                return json.dumps({"label": expected["expected_label"]}), extra, None
            return "Summary: " + " ".join(expected.get("required_outputs", []) or ["Done."]), extra, None
        if pack == "tool_agent":
            if expected.get("should_refuse"):
                return "Please confirm that you want this irreversible action before I continue.", extra, None
            return "The demo adapter does not call tools, so this task was not completed.", extra, None
        if pack == "pairwise_preference":
            return f"[{profile}] Demo response to: {inp.get('prompt', '')[:80]}", extra, None
        if pack == "probability_calibration":
            base = 0.8 if expected.get("label") == 1 else 0.25
            return json.dumps({"probability": round(min(0.99, base + 0.02 * (repeat % 3)), 3)}), extra, None
        return f"Demo output for {ext}", extra, None

    async def inspect_state(self, session: Any) -> dict[str, Any] | None:
        return None

    async def close(self, session: Any) -> None:
        return None


class DemoMemoryBackend:
    """Memory backend for demo episodes. Scheduled variants come from memory_outputs.yaml;
    other cases get a simple, clearly synthetic in-memory store."""

    name = "demo-memory"
    version = VERSION
    handles_generate = True

    async def prepare(self, stores: list[str], context: RunContext, *, profile: str,
                      external_id: str) -> dict[str, Any]:
        spec = demo_outputs()["memory"]["cases"].get(external_id)
        variant_name = _scheduled(spec["schedule"].get(profile), context.repeat_index) if spec else None
        variant = spec["variants"][variant_name] if variant_name else None
        return {"variant": variant, "variant_name": variant_name, "next_event": 1, "profile": profile,
                "stores": {s: {"facts": [], "events": [], "queue": []} for s in stores}}

    def _store(self, session, step) -> dict[str, Any]:
        return session["stores"].setdefault(step.get("store", "main"), {"facts": [], "events": [], "queue": []})

    def _facts(self, session, store_name: str) -> list[dict[str, Any]]:
        variant = session["variant"]
        if variant is not None and store_name == "main":
            return [{"claim": f["claim"], "state": f.get("state", "active"), "source_step": f.get("source_step"),
                     "memory_id": f"demo-fact-{i}"} for i, f in enumerate(variant["facts"])]
        return session["stores"][store_name]["facts"]

    async def execute_action(self, session: dict[str, Any], step: dict[str, Any],
                             resolved: dict[str, Any]) -> dict[str, Any]:
        action, args, store = step["action"], step.get("args") or {}, self._store(session, step)
        variant = session["variant"]
        if action in ("remember", "assert"):
            event_id = session["next_event"]
            session["next_event"] += 1
            store["events"].append({"id": event_id, "kind": "message" if action == "remember" else "assertion",
                                    "actor": args.get("actor", "user"), "text": args["text"],
                                    "source_step": step["id"]})
            if action == "assert":
                if args.get("status") == "approved":
                    store["facts"].append({"claim": args["text"], "state": "active", "source_step": step["id"],
                                           "source_event_id": event_id})
                else:
                    store["queue"].append({"event_id": event_id, "claim": args["text"], "source_step": step["id"]})
                return {"message": "asserted", "new_event_ids": [event_id]}
            verdict = ((variant or {}).get("smalltalk") or {}).get(step["id"])
            if verdict is None:
                words = [w.strip(".,!?").lower() for w in args["text"].split()]
                filler = bool(words) and all(w in _FILLER for w in words)
                verdict = {"outcome": "skipped" if filler else "kept", "method": "demo",
                           "reason": "demo rule: only filler words" if filler else "demo rule: content words"}
            if verdict["outcome"] != "skipped":
                store["facts"].append({"claim": args["text"], "state": "active", "source_step": step["id"],
                                       "source_event_id": event_id})
            return {"message": f"remembered turn {event_id}", "smalltalk": verdict, "new_event_ids": [event_id]}
        if action in ("approve", "reject"):
            target = resolved.get("target_event_id")
            item = next((q for q in store["queue"] if q["event_id"] == target), None)
            if item:
                store["queue"].remove(item)
                store["facts"].append({"claim": item["claim"], "source_step": item["source_step"],
                                       "state": "active" if action == "approve" else "rejected"})
            return {"message": f"{action}d", "target_event_id": target}
        if action in ("wrong", "forget"):
            source = args["step"]
            for fact in store["facts"]:
                if fact.get("source_step") == source and fact["state"] == "active":
                    fact["state"] = "invalidated" if action == "wrong" else "withdrawn"
            if action == "forget":
                store["facts"] = [f for f in store["facts"] if f.get("source_step") != source]
            return {"message": f"{action} recorded", "target_step": source}
        if action == "rebuild":
            return {"message": "demo rebuild (no persistent store)", "unresolved": []}
        if action == "recall":
            facts = [f for f in self._facts(session, step.get("store", "main")) if f["state"] == "active"]
            lines = [{"label": f"F{i + 1}", "text": f["claim"], "hit_id": f.get("memory_id"),
                      "source_step": f.get("source_step")} for i, f in enumerate(facts)]
            window = [{"label": f"W{i + 1}", "event_id": e["id"], "actor": e["actor"], "text": e["text"],
                       "source_step": e.get("source_step")} for i, e in enumerate(store["events"][-6:])]
            context = "## What is known about this person\n" + "\n".join(f"[{x['label']}] {x['text']}" for x in lines)
            if window:
                context += "\n## Recent conversation\n" + "\n".join(
                    f"[{w['label']}] {w['actor']}: {w['text']}" for w in window)
            used = _tokens(context)
            return {"context": context, "used": used, "budget": args.get("budget", 400), "facts": lines,
                    "window": window, "token_counts": {"total": used}, "tokenizer": "demo_chars_div_4",
                    "recorder": [], "suppressed": [], "dropped": []}
        if action == "generate":
            if variant is not None:
                return {"text": variant["answer"]}
            facts = [f for f in self._facts(session, step.get("store", "main")) if f["state"] == "active"]
            return {"text": facts[0]["claim"] if facts else "I don't know; nothing in memory answers that."}
        if action == "inspect_state":
            return await self.inspect_state(session, step.get("store", "main"))
        if action == "assert_state":
            snapshot = await self.inspect_state(session, step.get("store", "main"))
            checks = []
            for check in args.get("checks", []):
                matching = [f for f in snapshot["facts"]
                            if (check.get("claim_contains") or "").lower() in f["claim"].lower()
                            and (check.get("state") is None or f["state"] == check["state"])]
                passed = {"fact_present": bool(matching), "fact_absent": not matching,
                          "queue_empty": not snapshot["queue"],
                          "fact_count": len(matching) == check.get("equals")}[check["kind"]]
                checks.append({**check, "passed": passed})
            return {"checks": checks}
        if action == "tool_call":
            return {"error": "demo memory backend has no tools"}
        raise ValueError(f"unsupported action {action}")

    async def inspect_state(self, session: dict[str, Any], store: str) -> dict[str, Any]:
        facts = self._facts(session, store)
        data = session["stores"].get(store, {"events": [], "queue": []})
        return {"backend": "demo", "store": store, "exhaustive": True, "facts": facts,
                "queue": data["queue"], "events": data["events"],
                "counts": {"facts": len([f for f in facts if f["state"] == "active"]), "events": len(data["events"])},
                "notes": ["demo fixture state; not a MemoryAI measurement"]}

    async def close(self, session: dict[str, Any]) -> dict[str, Any]:
        return {"retained": False, "note": "demo backend holds no persistent store"}


def demo_judge(external_id: str, profile: str, repeat: int, deterministic_outcome: str) -> Any:
    """A judge that agrees with the deterministic outcome except for scheduled failures,
    which reply with malformed JSON (becoming grading errors after one retry)."""
    from eval_triage.graders.judge import JudgeReply

    failures = demo_outputs()["memory"].get("judge", {}).get("failures", [])
    fails = any(f["case"] == external_id and f["repeat"] == repeat and f["profile"] == profile for f in failures)

    def call(messages, meta):
        if fails:
            return JudgeReply(text="The answer seems fine to me!", model="demo-judge-v1",
                              request_id=f"demo-judge-{meta.get('attempt')}")
        verdict = {"pass": "pass", "fail": "fail"}.get(deterministic_outcome, "abstain")
        body = {"verdict": verdict, "evidence": [{"source": "deterministic graders",
                                                  "quote": f"outcome {deterministic_outcome}"}],
                "explanation": "Demo judge mirrors the deterministic outcome (synthetic)."}
        return JudgeReply(text=json.dumps(body), model="demo-judge-v1", request_id=f"demo-judge-{meta.get('attempt')}",
                          usage={"input_tokens": 0, "output_tokens": 0}, cost={"amount": 0.0, "currency": "USD"})

    return call
