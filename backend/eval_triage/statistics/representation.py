"""Canonical output representations for repeatability.

Agreement must be computed over a declared representation:

* ``raw`` — byte-for-byte UTF-8 text equality;
* ``json`` — canonical JSON (sorted keys, array order kept, no numeric coercion);
  outputs that do not parse are ineligible, not "different";
* ``semantic`` — classes assigned by a versioned procedure (grader verdict class,
  human label or clustering). Without such an assignment it is unavailable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from eval_triage.domain.canonical import CanonicalJSONError, canonical_json

REPRESENTATIONS = ("raw", "json", "semantic")


def category(output: Mapping[str, Any] | None, representation: str,
             semantic_class: str | None = None) -> tuple[str | None, str | None]:
    """Return ``(category, ineligible_reason)``."""
    if representation not in REPRESENTATIONS:
        raise ValueError(f"unknown representation {representation!r}")
    if output is None:
        return None, "no output"
    if representation == "semantic":
        return (f"semantic:{semantic_class}", None) if semantic_class else (None, "no semantic class assigned")
    text = output.get("text")
    if representation == "raw":
        if text is None:
            return None, "no text output"
        return "raw:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:24], None
    parsed = output.get("parsed")
    if parsed is None and text is not None:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None, "output is not valid JSON"
    if parsed is None:
        return None, "output is not valid JSON"
    try:
        return "json:" + hashlib.sha256(canonical_json(parsed).encode()).hexdigest()[:24], None
    except CanonicalJSONError as exc:
        return None, f"output is not canonical JSON ({exc})"
