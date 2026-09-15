"""Availability of optional integrations. The core app never imports them eagerly."""

from __future__ import annotations

import importlib.util
import shutil


def _module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def plugin_status() -> dict[str, dict]:
    return {
        "inspect": {
            "available": _module("inspect_ai"),
            "install": "uv sync --extra inspect",
            "purpose": "Inspect AI runner and log import",
        },
        "ragas": {
            "available": _module("ragas"),
            "install": "uv sync --extra ragas",
            "purpose": "Ragas retrieval and grounding metrics",
        },
        "promptfoo": {
            "available": True,
            "subprocess_available": shutil.which("npx") is not None,
            "install": "JSON import is built in; running suites needs `npx promptfoo` configured in Settings",
            "purpose": "Promptfoo result import and configured security-suite worker",
        },
    }
