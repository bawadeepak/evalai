"""OpenAI adapter (native SDK).

Endpoint modes are explicit: ``responses`` (default, general generation) and
``chat_completions`` (where features differ, e.g. seeds and token logprobs).
The model name always comes from the user's configuration. Capability claims are
per endpoint, dated, and conservative: seeds and logprobs are never assumed.
"""

from __future__ import annotations

import json
import time
from typing import Any

import openai

from eval_triage.adapters import transport
from eval_triage.adapters.base import Capability, RunContext, TargetConfig, TargetRequest, TargetResult, cap

VERSION = "openai-1"
RESPONSES_PARAMETERS = {"temperature", "top_p", "top_logprobs", "max_output_tokens", "max_tokens", "reasoning",
                        "effort"}
CHAT_PARAMETERS = {"temperature", "top_p", "seed", "logprobs", "top_logprobs", "max_tokens",
                   "max_completion_tokens", "stop", "effort"}


def _source(endpoint: str) -> str:
    return (f"openai SDK {openai.__version__} {endpoint} request surface and provider documentation "
            f"(as of {transport.CAPABILITIES_AS_OF})")


class OpenAIAdapter:
    name = "openai"
    version = VERSION
    default_endpoint = "responses"

    def endpoint(self, config: TargetConfig) -> str:
        return config.endpoint_type or self.default_endpoint

    def capabilities(self, config: TargetConfig) -> dict[str, Capability]:
        endpoint = self.endpoint(config)
        src = _source(endpoint)
        sampling = "some reasoning models reject sampling parameters; the provider error is recorded"
        caps = {
            "structured_output": cap("supported", src, "JSON schema output format"),
            "tools": cap("supported", src),
            "images": cap("supported", src, "model-dependent"),
            "temperature": cap("supported", src, sampling),
            "top_p": cap("supported", src, sampling),
            "usage": cap("supported", src),
            "prompt_logprobs": cap("unsupported", src),
            "state_inspection": cap("unsupported", src),
            "isolation": cap("supported", src, "stateless requests (store=false)"),
            "cancellation": cap("supported", src, "client-side abort; an aborted request may still be billed"),
            "episodes": cap("unsupported", src, "use the MemoryAI adapter with this configuration as its "
                                                "generation target"),
            "retrieval": cap("unsupported", src, "Eval Triage's lexical retriever supplies documents"),
        }
        if endpoint == "chat_completions":
            caps["seed"] = cap("unknown", src, "best effort only; determinism is not guaranteed")
            caps["token_logprobs"] = cap("unknown", src, "model-dependent")
        else:
            caps["seed"] = cap("unsupported", src, "not a Responses API parameter")
            caps["token_logprobs"] = cap("unknown", src, "top_logprobs availability is model-dependent")
        for value in caps.values():
            value.verified_at = transport.CAPABILITIES_AS_OF
        return caps

    async def prepare(self, config: TargetConfig, context: RunContext) -> dict[str, Any]:
        try:
            key = transport.credential(config)
        except transport.CredentialMissing as exc:
            return {"config": config, "error": transport.credential_error(str(exc))}
        client = openai.AsyncOpenAI(api_key=key or "not-required", base_url=config.base_url or None,
                                    **transport.client_kwargs(openai))
        return {"config": config, "client": client}

    async def execute(self, request: TargetRequest, session: dict[str, Any]) -> TargetResult:
        if session.get("error") is not None:
            return session["error"]
        config: TargetConfig = session["config"]
        started = time.monotonic()
        endpoint = self.endpoint(config)
        try:
            if endpoint == "chat_completions":
                result = await self._chat(session["client"], config, request)
            else:
                result = await self._responses(session["client"], config, request)
        except openai.APIError as exc:
            result = transport.error_result(exc, self.name)
        result.latency_ms = (time.monotonic() - started) * 1000
        if result.status == "success":
            result.cost = transport.cost_for(self.name, config.model, result.usage)
        return result

    async def inspect_state(self, session: Any) -> None:
        return None

    async def close(self, session: dict[str, Any]) -> None:
        client = session.get("client")
        if client is not None:
            await client.close()

    # --- Responses API ---------------------------------------------------------------------------

    async def _responses(self, client, config: TargetConfig, request: TargetRequest) -> TargetResult:
        extra = sorted(set(request.parameters) - RESPONSES_PARAMETERS)
        if extra:
            return transport.unsupported(f"parameters {extra} are not supported by the Responses endpoint")
        instructions = "\n\n".join(m["content"] for m in request.messages if m["role"] == "system")
        kwargs: dict[str, Any] = {"model": config.model, "input": _responses_input(request.messages), "store": False}
        if instructions:
            kwargs["instructions"] = instructions
        params = dict(request.parameters)
        if "max_tokens" in params:
            params["max_output_tokens"] = params.pop("max_tokens")
        if "effort" in params:
            params["reasoning"] = {**params.get("reasoning", {}), "effort": params.pop("effort")}
        kwargs.update(params)
        if request.response_format:
            kwargs["text"] = {"format": {"type": "json_schema", "name": request.response_format.get("name", "output"),
                                         "schema": request.response_format["schema"], "strict": False}}
        if request.tools:
            kwargs["tools"] = [{"type": "function", "name": t["name"], "description": t.get("description", ""),
                                "parameters": t.get("input_schema") or {"type": "object"}, "strict": False}
                               for t in request.tools]
        response = await client.responses.create(**kwargs)
        tool_calls, refusal, logprobs = [], None, []
        for item in response.output or []:
            if item.type == "function_call":
                tool_calls.append({"id": item.call_id, "tool": item.name,
                                   "arguments": transport.parse_arguments(item.arguments)})
            elif item.type == "message":
                for part in item.content or []:
                    if part.type == "refusal":
                        refusal = part.refusal
                    for token in getattr(part, "logprobs", None) or []:
                        logprobs.append({"token": token.token, "logprob": token.logprob})
        usage = response.usage
        details_in = getattr(usage, "input_tokens_details", None)
        details_out = getattr(usage, "output_tokens_details", None)
        incomplete = getattr(response, "incomplete_details", None)
        return TargetResult(
            status="success", text=response.output_text or None, tool_calls=tool_calls,
            content_blocks=[item.model_dump(mode="json") for item in response.output or []],
            stop_reason=(f"incomplete:{incomplete.reason}" if incomplete else response.status), refusal=refusal,
            truncated=response.status == "incomplete", request_id=response._request_id, actual_model=response.model,
            usage={"input_tokens": getattr(usage, "input_tokens", None),
                   "output_tokens": getattr(usage, "output_tokens", None),
                   "cached_input_tokens": getattr(details_in, "cached_tokens", None),
                   "reasoning_tokens": getattr(details_out, "reasoning_tokens", None)} if usage else {},
            logprobs=logprobs or None, raw_request=transport.request_summary("responses", kwargs),
            raw_response=response.model_dump(mode="json"))

    # --- Chat Completions --------------------------------------------------------------------------

    async def _chat(self, client, config: TargetConfig, request: TargetRequest) -> TargetResult:
        extra = sorted(set(request.parameters) - CHAT_PARAMETERS)
        if extra:
            return transport.unsupported(f"parameters {extra} are not supported by the Chat Completions endpoint")
        kwargs: dict[str, Any] = {"model": config.model, "messages": _chat_messages(request.messages)}
        params = dict(request.parameters)
        if "effort" in params:
            params["reasoning_effort"] = params.pop("effort")
        kwargs.update(params)
        if request.response_format:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": request.response_format.get("name", "output"), "schema": request.response_format["schema"],
                "strict": False}}
        if request.tools:
            kwargs["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object"}}} for t in request.tools]
        completion = await client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        message = choice.message
        tool_calls = [{"id": call.id, "tool": call.function.name,
                       "arguments": transport.parse_arguments(call.function.arguments)}
                      for call in (message.tool_calls or []) if getattr(call, "function", None)]
        logprobs = None
        if choice.logprobs and choice.logprobs.content:
            logprobs = [{"token": t.token, "logprob": t.logprob} for t in choice.logprobs.content]
        usage = completion.usage
        return TargetResult(
            status="success", text=message.content, tool_calls=tool_calls, stop_reason=choice.finish_reason,
            refusal=getattr(message, "refusal", None), truncated=choice.finish_reason == "length",
            request_id=completion._request_id, actual_model=completion.model,
            usage={"input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens,
                   "cached_input_tokens": getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)}
            if usage else {},
            logprobs=logprobs, raw_request=transport.request_summary("chat_completions", kwargs),
            raw_response=completion.model_dump(mode="json"))


def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "system":
            continue
        if role == "tool":
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                          "output": message["content"]})
        elif role == "assistant" and message.get("tool_calls"):
            if message.get("content"):
                items.append({"role": "assistant", "content": message["content"]})
            for call in message["tool_calls"]:
                items.append({"type": "function_call", "call_id": call["id"], "name": call["tool"],
                              "arguments": json.dumps(call.get("arguments") or {})})
        else:
            items.append({"role": role, "content": message["content"]})
    return items


def _chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            out.append({"role": "tool", "tool_call_id": message["tool_call_id"], "content": message["content"]})
        elif role == "assistant" and message.get("tool_calls"):
            out.append({"role": "assistant", "content": message.get("content") or None, "tool_calls": [
                {"id": call["id"], "type": "function",
                 "function": {"name": call["tool"], "arguments": json.dumps(call.get("arguments") or {})}}
                for call in message["tool_calls"]]})
        else:
            out.append({"role": role, "content": message["content"]})
    return out
