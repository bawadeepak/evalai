"""Pack executors: build requests, call the target (with transport retries and a
timeout), run tool loops or episodes, and normalise the result into the output
shape graders consume."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from eval_triage.adapters.base import TargetConfig, TargetRequest, TargetResult
from eval_triage.execution.prompts import build_messages, parse_output
from eval_triage.execution.retrieval import VERSION as RETRIEVER_VERSION
from eval_triage.execution.retrieval import lexical_retrieve
from eval_triage.execution.retry import with_transport_retries
from eval_triage.execution.sandbox import ToolSandbox
from eval_triage.statistics.core import token_logprob_summary

MAX_TOOL_TURNS = 8
ADAPTER_ONLY_PARAMETERS = {"profile", "delay_ms", "max_turns"}

AttemptCallback = Callable[[str, int, TargetResult], None]


def request_parameters(config: TargetConfig) -> dict[str, Any]:
    return {k: v for k, v in config.parameters.items() if k not in ADAPTER_ONLY_PARAMETERS}


def request_metadata(config: TargetConfig, scenario: dict, case: dict, repeat: int) -> dict[str, Any]:
    meta = {"pack": scenario["pack"], "external_id": case["external_id"], "repeat_index": repeat}
    if config.adapter == "demo":  # only the synthetic demo adapter ever sees the case contract
        meta.update(demo_expected=case.get("expected") or {}, demo_input=case.get("input") or {})
    return meta


async def call_target(adapter, session, request: TargetRequest, *, timeout: float, max_retries: int,
                      on_attempt: AttemptCallback, stage: str) -> TargetResult:
    async def once(_attempt: int) -> TargetResult:
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(adapter.execute(request, session), timeout=timeout)
        except TimeoutError:
            result = TargetResult(status="timeout", retryable=True,
                                  error={"code": "timeout", "message": f"no response within {timeout:.0f} s"})
        if result.latency_ms is None:
            result.latency_ms = (time.monotonic() - started) * 1000
        return result

    return await with_transport_retries(once, max_retries=max_retries,
                                        on_attempt=lambda i, r: on_attempt(stage, i, r))


def normalize_output(scenario: dict, result: TargetResult, **extra: Any) -> tuple[str, dict[str, Any]]:
    parsed = parse_output(scenario, result.text)
    summary = None
    if result.logprobs:
        try:
            summary = token_logprob_summary([t["logprob"] for t in result.logprobs if "logprob" in t])
        except (ValueError, KeyError, TypeError):
            summary = None
    output = {
        "text": result.text,
        "parsed": parsed["parsed"],
        "parse_error": parsed["parse_error"],
        "probability": parsed["probability"],
        "probability_unavailable_reason": parsed["probability_unavailable_reason"],
        "probability_method": "stated probability in output" if parsed["probability"] is not None else None,
        "logprob_summary": summary,
        "logprob_unavailable_reason": None if result.logprobs else "target returned no token log probabilities",
        "tool_calls": extra.get("tool_calls", []),
        "effects": extra.get("effects", []),
        "retrieved_ids": extra.get("retrieved_ids"),
        "retriever": extra.get("retriever"),
        "stores": extra.get("stores", {}),
        "refused": result.refusal is not None if result.refusal is not None else None,
        "stop_reason": result.stop_reason,
        "truncated": result.truncated,
        "actual_model": result.actual_model,
    }
    return ("invalid_output" if parsed["invalid"] else "success"), output


async def execute_stateless(adapter, session, config: TargetConfig, scenario: dict, case: dict, repeat: int, *,
                            timeout: float, max_retries: int, on_attempt: AttemptCallback,
                            capabilities: dict) -> tuple[str, dict[str, Any], TargetResult]:
    extra: dict[str, Any] = {}
    documents = None
    adapter_retrieves = (capabilities.get("retrieval") or {}).get("state") == "supported"
    if scenario["pack"] == "rag" and not adapter_retrieves:
        k = (case.get("expected") or {}).get("k", 5)
        hits = lexical_retrieve(scenario.get("corpus") or [], case["input"]["question"], k)
        corpus = {d["id"]: d for d in scenario.get("corpus") or []}
        documents = [corpus[h["id"]] for h in hits]
        extra.update(retrieved_ids=[h["id"] for h in hits], retriever=RETRIEVER_VERSION)
    response_format = None
    if scenario.get("output_schema") and (capabilities.get("structured_output") or {}).get("state") == "supported":
        response_format = {"type": "json_schema", "name": "output", "schema": scenario["output_schema"]}
    request = TargetRequest(messages=build_messages(scenario, case, config.prompt_template, documents),
                            parameters=request_parameters(config), response_format=response_format,
                            metadata=request_metadata(config, scenario, case, repeat))
    result = await call_target(adapter, session, request, timeout=timeout, max_retries=max_retries,
                               on_attempt=on_attempt, stage="target")
    if result.status != "success":
        return result.status, {"text": None, "error": result.error}, result
    if scenario["pack"] == "rag" and adapter_retrieves:
        extra.update(retrieved_ids=result.extra.get("retrieved_ids"), retriever="target")
    status, output = normalize_output(scenario, result, **extra)
    return status, output, result


async def execute_agent(adapter, session, config: TargetConfig, scenario: dict, case: dict, repeat: int, *,
                        timeout: float, max_retries: int, on_attempt: AttemptCallback,
                        capabilities: dict) -> tuple[str, dict[str, Any], TargetResult]:
    sandbox = ToolSandbox(scenario.get("tools") or [])
    messages = build_messages(scenario, case, config.prompt_template)
    max_turns = int(config.parameters.get("max_turns", MAX_TOOL_TURNS))
    result = TargetResult(status="provider_error", error={"message": "no turns executed"})
    for turn in range(max_turns):
        request = TargetRequest(messages=list(messages), parameters=request_parameters(config),
                                tools=sandbox.definitions(), metadata=request_metadata(config, scenario, case, repeat))
        result = await call_target(adapter, session, request, timeout=timeout, max_retries=max_retries,
                                   on_attempt=on_attempt, stage=f"turn:{turn + 1}")
        if result.status != "success":
            return result.status, {"text": None, "error": result.error, "tool_calls": sandbox.calls,
                                   "effects": sandbox.effects}, result
        if not result.tool_calls:
            break
        messages.append({"role": "assistant", "content": result.text or "", "tool_calls": result.tool_calls})
        for call in result.tool_calls:
            record = sandbox.call(call.get("tool"), call.get("arguments"), call.get("id"))
            messages.append({"role": "tool", "tool_call_id": record["id"], "name": record["tool"],
                             "content": json.dumps(record["result"], ensure_ascii=False)})
    else:
        result.truncated = True
    status, output = normalize_output(scenario, result, tool_calls=sandbox.calls, effects=sandbox.effects)
    return status, output, result
