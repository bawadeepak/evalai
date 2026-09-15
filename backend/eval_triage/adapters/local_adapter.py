"""Explicit local OpenAI-compatible endpoint (for example Ollama or llama.cpp).

Uses the Chat Completions request shape against a user-supplied base URL. Local
servers implement different subsets of the OpenAI surface, so every optional
feature is ``unknown`` until the user runs a connection test or opts into
experimental mode — nothing is assumed.
"""

from __future__ import annotations

from eval_triage.adapters import transport
from eval_triage.adapters.base import Capability, TargetConfig, cap
from eval_triage.adapters.openai_adapter import OpenAIAdapter

VERSION = "openai-compatible-1"


class LocalOpenAICompatibleAdapter(OpenAIAdapter):
    name = "openai_compatible"
    version = VERSION
    default_endpoint = "chat_completions"

    def endpoint(self, config: TargetConfig) -> str:
        return "chat_completions"

    def capabilities(self, config: TargetConfig) -> dict[str, Capability]:
        src = f"local OpenAI-compatible server at {config.base_url} (not verified; run a connection test)"
        unknown = "server-dependent; not assumed"
        caps = {key: cap("unknown", src, unknown) for key in (
            "structured_output", "tools", "images", "temperature", "top_p", "seed", "token_logprobs", "usage")}
        caps.update({
            "prompt_logprobs": cap("unsupported", src),
            "state_inspection": cap("unsupported", src),
            "isolation": cap("supported", src, "stateless requests"),
            "cancellation": cap("supported", src, "client-side abort"),
            "episodes": cap("unsupported", src, "use the MemoryAI adapter with this configuration as its "
                                                "generation target"),
            "retrieval": cap("unsupported", src, "Eval Triage's lexical retriever supplies documents"),
        })
        for value in caps.values():
            value.verified_at = transport.CAPABILITIES_AS_OF
        return caps
