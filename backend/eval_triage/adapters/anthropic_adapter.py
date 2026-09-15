"""Anthropic adapter (native Messages SDK).

Preserves content blocks, tool use, stop reasons (including ``refusal`` with its
stop details) and usage. The installed SDK's ``messages.create`` exposes no
sampling parameters and the API has no seeds or token logprobs, so those
capabilities are declared unsupported and requests for them fail validation
instead of being fabricated or dropped. The credential reference defaults to
``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

from eval_triage.adapters import transport
from eval_triage.adapters.base import Capability, RunContext, TargetConfig, TargetRequest, TargetResult, cap

VERSION = "anthropic-1"
SUPPORTED_PARAMETERS = {"max_tokens", "effort", "stop"}


def _source() -> str:
    return (f"anthropic SDK {anthropic.__version__} messages.create signature and Claude API documentation "
            f"(as of {transport.CAPABILITIES_AS_OF})")


class AnthropicAdapter:
    name = "anthropic"
    version = VERSION

    def capabilities(self, config: TargetConfig) -> dict[str, Capability]:
        src = _source()
        no_sampling = "messages.create exposes no sampling parameters; current Claude models reject them"
        caps = {
            "structured_output": cap("supported", src, "output_config.format json_schema"),
            "tools": cap("supported", src),
            "images": cap("supported", src),
            "temperature": cap("unsupported", src, no_sampling),
            "top_p": cap("unsupported", src, no_sampling),
            "seed": cap("unsupported", src, "the Messages API has no seed parameter"),
            "token_logprobs": cap("unsupported", src, "the Messages API returns no token log probabilities"),
            "prompt_logprobs": cap("unsupported", src),
            "usage": cap("supported", src, "input, output and cache token counts"),
            "state_inspection": cap("unsupported", src),
            "isolation": cap("supported", src, "stateless requests"),
            "cancellation": cap("supported", src, "client-side abort; an aborted request may still be billed"),
            "episodes": cap("unsupported", src, "use the MemoryAI adapter with this configuration as its "
                                                "generation target"),
            "retrieval": cap("unsupported", src, "Eval Triage's lexical retriever supplies documents"),
        }
        for value in caps.values():
            value.verified_at = transport.CAPABILITIES_AS_OF
        return caps

    async def prepare(self, config: TargetConfig, context: RunContext) -> dict[str, Any]:
        try:
            key = transport.credential(config)
        except transport.CredentialMissing as exc:
            return {"config": config, "error": transport.credential_error(str(exc))}
        client = anthropic.AsyncAnthropic(api_key=key, base_url=config.base_url or None,
                                          **transport.client_kwargs(anthropic))
        return {"config": config, "client": client}

    async def execute(self, request: TargetRequest, session: dict[str, Any]) -> TargetResult:
        if session.get("error") is not None:
            return session["error"]
        config: TargetConfig = session["config"]
        extra = sorted(set(request.parameters) - SUPPORTED_PARAMETERS)
        if extra:
            return transport.unsupported(f"parameters {extra} are not supported by the Anthropic Messages API")
        started = time.monotonic()
        kwargs = _request_kwargs(config, request)
        try:
            message = await session["client"].messages.create(**kwargs)
        except anthropic.APIError as exc:
            result = transport.error_result(exc, self.name)
            result.latency_ms = (time.monotonic() - started) * 1000
            result.raw_request = transport.request_summary("messages", kwargs)
            return result
        text = "".join(block.text for block in message.content if block.type == "text")
        tool_calls = [{"id": block.id, "tool": block.name, "arguments": transport.parse_arguments(block.input)}
                      for block in message.content if block.type == "tool_use"]
        refusal = None
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            refusal = (getattr(details, "explanation", None) or getattr(details, "category", None)
                       or "the model declined this request")
        usage = message.usage
        usage_dict = {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                      "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
                      "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None)}
        return TargetResult(
            status="success", text=text or None, tool_calls=tool_calls,
            content_blocks=[block.model_dump(mode="json") for block in message.content],
            stop_reason=message.stop_reason, refusal=refusal, truncated=message.stop_reason == "max_tokens",
            request_id=message._request_id, actual_model=message.model, usage=usage_dict,
            cost=transport.cost_for(self.name, config.model, usage_dict), logprobs=None,
            raw_request=transport.request_summary("messages", kwargs), raw_response=message.model_dump(mode="json"),
            latency_ms=(time.monotonic() - started) * 1000)

    async def inspect_state(self, session: Any) -> None:
        return None

    async def close(self, session: dict[str, Any]) -> None:
        client = session.get("client")
        if client is not None:
            await client.close()


def _request_kwargs(config: TargetConfig, request: TargetRequest) -> dict[str, Any]:
    system = "\n\n".join(m["content"] for m in request.messages if m["role"] == "system")
    params = dict(request.parameters)
    kwargs: dict[str, Any] = {"model": config.model, "max_tokens": params.pop("max_tokens", transport.DEFAULT_MAX_TOKENS),
                              "messages": _messages(request.messages)}
    if system:
        kwargs["system"] = system
    output_config: dict[str, Any] = {}
    if "effort" in params:
        output_config["effort"] = params.pop("effort")
    if request.response_format:
        output_config["format"] = {"type": "json_schema", "schema": request.response_format["schema"]}
    if output_config:
        kwargs["output_config"] = output_config
    if "stop" in params:
        stop = params.pop("stop")
        kwargs["stop_sequences"] = stop if isinstance(stop, list) else [stop]
    if request.tools:
        kwargs["tools"] = [{"name": t["name"], "description": t.get("description", ""),
                            "input_schema": t.get("input_schema") or {"type": "object"}} for t in request.tools]
    return kwargs


def _messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert neutral messages. Consecutive tool results go back in a single user turn."""
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "system":
            continue
        if role == "tool":
            block = {"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) and all(
                    b.get("type") == "tool_result" for b in out[-1]["content"]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif role == "assistant" and message.get("tool_calls"):
            content: list[dict[str, Any]] = []
            if message.get("content"):
                content.append({"type": "text", "text": message["content"]})
            content += [{"type": "tool_use", "id": call["id"], "name": call["tool"],
                         "input": call.get("arguments") or {}} for call in message["tool_calls"]]
            out.append({"role": "assistant", "content": content})
        else:
            out.append({"role": role, "content": message["content"]})
    return out
