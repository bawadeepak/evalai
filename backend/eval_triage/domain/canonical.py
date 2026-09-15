"""Canonical JSON and content hashing.

Immutable records are hashed over canonical UTF-8 JSON: object keys sorted
recursively, arrays in their original order, the shortest round-trip float
representation, and no lossy coercion. Non-finite numbers, non-string keys and
non-JSON types are rejected rather than silently converted.

Callers decide *what* goes into a hash. Use :func:`hash_payload` with the
top-level keys that are operational (ids, timestamps, project ownership) so the
same definition hashes identically after import into another project.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

#: Top-level keys that never contribute to a definition hash.
OPERATIONAL_KEYS = frozenset(
    {"id", "hash", "content_hash", "created_at", "updated_at", "project_id", "logical_id", "version",
     "parent_id", "reason"}
)


class CanonicalJSONError(ValueError):
    pass


def _check(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJSONError(f"{path}: non-finite number is not valid JSON")
        return value
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONError(f"{path}: object keys must be strings, got {type(key).__name__}")
            out[key] = _check(item, f"{path}.{key}")
        return out
    if isinstance(value, (list, tuple)):
        return [_check(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise CanonicalJSONError(f"{path}: {type(value).__name__} is not a JSON type")


def canonical_json(value: Any) -> str:
    return json.dumps(_check(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def strip_keys(value: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    drop = set(keys)
    return {k: v for k, v in value.items() if k not in drop}


def hash_payload(value: Mapping[str, Any], extra_exclude: Iterable[str] = ()) -> str:
    """Hash a definition, excluding operational top-level keys."""
    return content_hash(strip_keys(value, OPERATIONAL_KEYS | set(extra_exclude)))


def dumps_strict(value: Any) -> str:
    """JSON serializer for database columns: rejects NaN/Infinity."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False)
