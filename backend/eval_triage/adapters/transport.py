"""Plumbing shared by provider adapters.

* Credentials are read server-side from the environment variable *named* in the
  target configuration; values never leave the process or enter artifacts.
* SDK clients are created with ``max_retries=0`` so every transport attempt is
  visible to (and recorded by) Eval Triage's own retry policy.
* SDK exceptions are mapped to explicit statuses with a retryable flag.
* Tests inject a mock HTTP transport through :data:`HTTP_CLIENT_FACTORY`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from eval_triage.adapters.base import TargetResult

CAPABILITIES_AS_OF = "2026-09-15"
DEFAULT_MAX_TOKENS = 16000
RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})

#: ``factory(sdk_module) -> async http client``; ``None`` uses the SDK default.
HTTP_CLIENT_FACTORY: Callable[[Any], Any] | None = None


class CredentialMissing(Exception):
    pass


def credential(config) -> str | None:
    if not config.credential_ref:
        return None
    value = os.environ.get(config.credential_ref)
    if not value:
        raise CredentialMissing(config.credential_ref)
    return value


def client_kwargs(sdk) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"max_retries": 0}
    if HTTP_CLIENT_FACTORY is not None:
        kwargs["http_client"] = HTTP_CLIENT_FACTORY(sdk)
    return kwargs


def credential_error(ref: str) -> TargetResult:
    return TargetResult(status="provider_error", retryable=False,
                        error={"code": "credential_missing",
                               "message": f"environment variable {ref} is not set on the server"})


def unsupported(message: str, **details: Any) -> TargetResult:
    return TargetResult(status="unsupported", retryable=False,
                        error={"code": "unsupported_parameter", "message": message, **details})


def _code(name: str, status: int | None) -> str:
    if name == "APITimeoutError":
        return "timeout"
    if name == "APIConnectionError":
        return "connection_error"
    return {400: "bad_request", 401: "authentication_failed", 403: "permission_denied", 404: "not_found",
            408: "request_timeout", 409: "conflict", 413: "request_too_large", 422: "unprocessable",
            429: "rate_limited", 529: "overloaded"}.get(status or 0, "server_error" if (status or 0) >= 500
                                                        else "provider_error")


def error_result(exc: Exception, provider: str) -> TargetResult:
    """Map an OpenAI/Anthropic SDK exception (the SDKs share class names) to a TargetResult."""
    name = type(exc).__name__
    status_code = getattr(exc, "status_code", None)
    if name == "APITimeoutError":
        status, retryable = "timeout", True
    elif name == "APIConnectionError":
        status, retryable = "provider_error", True
    else:
        status, retryable = "provider_error", status_code in RETRYABLE_STATUS
    body = getattr(exc, "body", None)
    return TargetResult(
        status=status, retryable=retryable, request_id=getattr(exc, "request_id", None),
        error={"code": _code(name, status_code), "type": name, "status_code": status_code,
               "message": str(getattr(exc, "message", "") or exc)[:1000], "provider": provider,
               "retryable": retryable},
        raw_response={"error": body if isinstance(body, (dict, list, str)) else None, "status_code": status_code},
    )


def parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {"_unparsed_arguments": raw}
    return value if isinstance(value, dict) else {"_unparsed_arguments": raw}


def cost_for(adapter: str, model: str, usage: dict[str, Any]) -> dict[str, Any]:
    from eval_triage.adapters.pricing import estimate_cost, load_pricing
    from eval_triage.config import get_settings

    return estimate_cost(load_pricing(get_settings()), adapter, model, usage)


def request_summary(endpoint: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """What was sent, for the evidence record. Headers (and so credentials) are never included."""
    return {"endpoint": endpoint, "body": kwargs}
