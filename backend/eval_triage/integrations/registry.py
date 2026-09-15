"""Availability and descriptions of optional integrations.

The core app never imports an optional dependency eagerly: importers parse
files directly, and runners/graders import their package only when used.
"""

from __future__ import annotations

from typing import Any

from eval_triage.integrations import inspect_logs, promptfoo, ragas_grader


def _settings(settings):
    if settings is not None:
        return settings
    from eval_triage.config import get_settings

    return get_settings()


def plugins(settings=None) -> list[dict[str, Any]]:
    """Full plugin descriptions: id/version, packs, input and result schemas, capabilities."""
    settings = _settings(settings)
    return [promptfoo.INFO.describe(promptfoo.capabilities(settings)),
            inspect_logs.INFO.describe(inspect_logs.capabilities(settings)),
            ragas_grader.INFO.describe(ragas_grader.capabilities(settings))]


def plugin_status(settings=None) -> dict[str, dict]:
    """Compact availability used by health and settings."""
    settings = _settings(settings)
    pf = promptfoo.capabilities(settings)
    ins = inspect_logs.capabilities(settings)
    rg = ragas_grader.capabilities(settings)
    return {
        "inspect": {
            "available": ins["run"]["available"],
            "import_available": True,
            "install": inspect_logs.INSTALL,
            "purpose": "Inspect AI log import (built in) and task runner (needs inspect_ai)",
            "reason": ins["run"]["reason"],
        },
        "ragas": {
            "available": rg["grade"]["available"],
            "install": ragas_grader.INSTALL,
            "purpose": "Ragas retrieval and grounding metrics as an external grader",
            "reason": rg["grade"]["reason"],
        },
        "promptfoo": {
            "available": True,
            "import_available": True,
            "run_available": pf["run"]["available"],
            "subprocess_available": pf["run"]["available"],
            "install": promptfoo.INFO.install,
            "purpose": "Promptfoo result import (built in) and explicitly configured suite runner",
            "reason": pf["run"]["reason"],
        },
    }
