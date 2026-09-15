"""Secret redaction for stored evidence.

Credential values are never persisted: authorization-like keys are replaced and
any occurrence of a secret value from the server environment is masked. A
redaction manifest records what was changed, so redacted bytes are never
presented as exact originals.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from typing import Any

REDACTION_VERSION = "redaction_v1"
REDACTED = "[REDACTED]"
SENSITIVE_KEY = re.compile(r"(authorization|api[-_]?key|x-api-key|access[-_]?token|secret|password|cookie)", re.I)
SECRET_ENV = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD)", re.I)


def secret_values(extra: Iterable[str] = ()) -> list[str]:
    values = {v for k, v in os.environ.items() if SECRET_ENV.search(k) and v and len(v) >= 8}
    values |= {v for v in extra if v and len(v) >= 8}
    return sorted(values, key=len, reverse=True)


def redact(value: Any, secrets: list[str] | None = None) -> tuple[Any, dict[str, Any]]:
    secrets = secret_values() if secrets is None else secrets
    report = {"version": REDACTION_VERSION, "redacted_keys": [], "redacted_values": 0}

    def walk(item: Any, path: str) -> Any:
        if isinstance(item, dict):
            out = {}
            for key, sub in item.items():
                if isinstance(key, str) and SENSITIVE_KEY.search(key) and sub not in (None, "", [], {}):
                    out[key] = REDACTED
                    report["redacted_keys"].append(f"{path}.{key}")
                else:
                    out[key] = walk(sub, f"{path}.{key}")
            return out
        if isinstance(item, list):
            return [walk(sub, f"{path}[{i}]") for i, sub in enumerate(item)]
        if isinstance(item, str):
            for secret in secrets:
                if secret in item:
                    item = item.replace(secret, REDACTED)
                    report["redacted_values"] += 1
            return item
        return item

    return walk(value, "$"), report


def contains_secret(text: str, secrets: list[str] | None = None) -> bool:
    return any(s in text for s in (secret_values() if secrets is None else secrets))
