"""Dated, configurable pricing table.

Prices are never hardcoded claims about today's provider prices. The shipped
default only prices the demo adapter (free). Users add real prices in
``$EVAL_TRIAGE_DATA_DIR/pricing.json`` (same shape). A model without an entry
has ``unknown`` cost — never zero.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from eval_triage.config import REPO_ROOT, Settings

DEFAULT_PRICING = REPO_ROOT / "config" / "pricing.default.json"


def load_pricing(settings: Settings | None = None) -> dict[str, Any]:
    tables = [json.loads(DEFAULT_PRICING.read_text())] if DEFAULT_PRICING.is_file() else []
    if settings is not None:
        user = settings.data_dir / "pricing.json"
        if user.is_file():
            tables.append(json.loads(user.read_text()))
    merged: dict[str, Any] = {"entries": [], "sources": []}
    for table in tables:
        for entry in table.get("entries", []):
            merged["entries"].append({**entry, "as_of": entry.get("as_of", table.get("as_of"))})
        merged["sources"].append({"as_of": table.get("as_of"), "description": table.get("description", "")})
    return merged


def find_price(table: dict[str, Any], adapter: str, model: str) -> dict[str, Any] | None:
    match = None
    for entry in table.get("entries", []):
        if entry.get("adapter") in (adapter, "*") and fnmatch.fnmatchcase(model or "", entry.get("model", "")):
            match = entry  # later (user) entries override earlier ones
    return match


def estimate_cost(table: dict[str, Any], adapter: str, model: str, usage: dict[str, Any]) -> dict[str, Any]:
    price = find_price(table, adapter, model)
    if price is None:
        return {"amount": None, "currency": None, "reason": f"no pricing entry for {adapter}:{model}"}
    input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
    if input_tokens is None or output_tokens is None:
        return {"amount": None, "currency": price["currency"], "reason": "provider did not report token usage"}
    amount = (input_tokens * price.get("input_per_million", 0) + output_tokens * price.get("output_per_million", 0)
              ) / 1_000_000
    return {"amount": amount, "currency": price["currency"], "source": f"pricing table as of {price.get('as_of')}",
            "reason": None}


def estimate_run_cost(table: dict[str, Any], adapter: str, model: str, calls: int,
                      tokens_per_call: tuple[int, int] = (800, 300)) -> dict[str, Any]:
    price = find_price(table, adapter, model)
    if price is None:
        return {"amount": None, "currency": None, "display": "unknown",
                "reason": f"no pricing entry for {adapter}:{model}"}
    per_call = (tokens_per_call[0] * price.get("input_per_million", 0)
                + tokens_per_call[1] * price.get("output_per_million", 0)) / 1_000_000
    return {"amount": per_call * calls, "currency": price["currency"], "display": None, "estimated": True,
            "assumption": f"~{tokens_per_call[0]} input and {tokens_per_call[1]} output tokens per call",
            "source": f"pricing table as of {price.get('as_of')}"}


def write_user_pricing(settings: Settings, table: dict[str, Any]) -> Path:
    path = settings.data_dir / "pricing.json"
    path.write_text(json.dumps(table, indent=2))
    return path
