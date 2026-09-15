"""Local sandboxed tool environment for agent and security scenarios.

Tools are the scenario's declared contracts. Calls are validated against their
JSON argument schemas, return fixture-defined values and record declared
effects. Tools that require confirmation do nothing unless called with
``confirmed: true``. No real system is ever contacted.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import jsonschema

_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]{0,63})\}")


def _format_effect(template: str, arguments: dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(arguments.get(m.group(1), "")), template)


def _matches(when: dict[str, Any], arguments: dict[str, Any]) -> bool:
    return all(arguments.get(k) == v for k, v in when.items())


class ToolSandbox:
    def __init__(self, contracts: list[dict[str, Any]]) -> None:
        self.contracts = {c["name"]: c for c in contracts}
        self.calls: list[dict[str, Any]] = []
        self.effects: list[str] = []

    def definitions(self) -> list[dict[str, Any]]:
        out = []
        for c in self.contracts.values():
            schema = copy.deepcopy(c.get("arguments_schema") or {"type": "object"})
            if c.get("requires_confirmation"):
                schema.setdefault("properties", {})["confirmed"] = {
                    "type": "boolean", "description": "Set true only after the user explicitly confirmed."}
                if schema.get("additionalProperties") is False:
                    schema["additionalProperties"] = False
            out.append({"name": c["name"], "description": c.get("description", ""), "input_schema": schema})
        return out

    def call(self, tool: str, arguments: Any, call_id: str | None = None) -> dict[str, Any]:
        record: dict[str, Any] = {"id": call_id or f"call_{len(self.calls) + 1}", "tool": tool,
                                  "arguments": arguments, "effects": [], "valid_arguments": True,
                                  "confirmed": None, "error": None, "result": None}
        contract = self.contracts.get(tool)
        if contract is None:
            record.update(error="unknown_tool", valid_arguments=False, result={"error": f"unknown tool {tool!r}"})
            self.calls.append(record)
            return record
        if not isinstance(arguments, dict):
            record.update(error="invalid_arguments", valid_arguments=False,
                          result={"error": "arguments must be a JSON object"})
            self.calls.append(record)
            return record
        confirmed = arguments.get("confirmed") is True
        plain = {k: v for k, v in arguments.items() if k != "confirmed"}
        errors = list(jsonschema.Draft202012Validator(contract.get("arguments_schema") or {}).iter_errors(plain))
        if errors:
            record.update(error="invalid_arguments", valid_arguments=False,
                          result={"error": "invalid arguments", "details": [e.message for e in errors[:5]]})
            self.calls.append(record)
            return record
        if contract.get("requires_confirmation"):
            record["confirmed"] = confirmed
            if not confirmed:
                record.update(error="confirmation_required",
                              result={"error": "This action requires explicit user confirmation."})
                self.calls.append(record)
                return record
        result = next((f.get("returns") for f in contract.get("fixtures", []) if _matches(f.get("when", {}), plain)),
                      contract.get("default_return"))
        effects = [_format_effect(t, plain) for t in contract.get("effects", [])]
        self.effects.extend(effects)
        record.update(result=copy.deepcopy(result), effects=effects)
        self.calls.append(record)
        return record
