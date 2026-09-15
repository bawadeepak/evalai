"""Inspect AI eval-log importer and optional runner.

Import reads Inspect's JSON log format (``--log-format json`` or
``inspect log convert --to json``) without needing ``inspect_ai`` installed.
Upstream identifiers (run id, task id, sample id, epoch) are kept, and the
original log file is stored as an artifact by the caller.

Running tasks needs the optional ``inspect_ai`` package; when it is absent the
runner reports itself unavailable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval_triage.integrations.base import (
    ExternalScore,
    NormalizedImport,
    NormalizedResult,
    PluginInfo,
    PluginInputError,
    module_available,
    module_version,
    require,
    summarize,
)

PLUGIN_ID = "inspect"
PLUGIN_VERSION = "inspect_log_import_v1"
INSTALL = "optional extra: install inspect-ai into this environment"

INFO = PluginInfo(
    id=PLUGIN_ID, version=PLUGIN_VERSION, title="Inspect AI",
    purpose="Import Inspect eval logs; run Inspect tasks when inspect_ai is installed",
    supported_packs=("reference_answer", "exact_classification", "structured_extraction", "tool_agent"),
    input_description="Inspect EvalLog JSON (log format version 1 or 2)",
    input_schema={"type": "object", "required": ["eval"],
                  "properties": {"version": {"type": "integer"}, "eval": {"type": "object"},
                                 "samples": {"type": "array"}}},
    operations=("import", "run"),
    install=INSTALL,
)

#: Inspect's conventional letter values (inspect_ai.scorer CORRECT/INCORRECT/PARTIAL/NOANSWER).
LETTERS = {"C": "pass", "I": "fail", "P": "partial", "N": "no_answer"}


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                content = item.get("content")
                parts.append(content if isinstance(content, str) else json.dumps(content))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return json.dumps(value)


def _score(name: str, score: dict[str, Any], scorer_meta: dict[str, Any]) -> tuple[ExternalScore, str | None]:
    value = score.get("value")
    definition = (f"Inspect scorer '{name}' value as reported in the log"
                  + (f" (scorer {scorer_meta.get('scorer')})" if scorer_meta.get("scorer") else ""))
    if isinstance(value, str) and value in LETTERS:
        verdict = LETTERS[value]
        return ExternalScore(name=name, value=value, kind="label", definition=definition + "; C/I/P/N letters",
                             implementation_version=PLUGIN_VERSION, note=verdict), verdict
    if isinstance(value, bool):
        return ExternalScore(name=name, value=value, kind="binary", definition=definition,
                             implementation_version=PLUGIN_VERSION), "pass" if value else "fail"
    if isinstance(value, int | float):
        return ExternalScore(name=name, value=float(value), kind="numeric", definition=definition,
                             implementation_version=PLUGIN_VERSION,
                             note="numeric scorer output; not a probability and not a pass/fail verdict"), None
    return ExternalScore(name=name, value=json.dumps(value) if value is not None else None, kind="text",
                         definition=definition, implementation_version=PLUGIN_VERSION), None


def _status(verdicts: list[str | None], error: Any) -> str:
    if error:
        return "error"
    binary = [v for v in verdicts if v in ("pass", "fail")]
    if not binary:
        return "unscored"
    return "fail" if "fail" in binary else "pass"


def parse(raw: bytes | str) -> NormalizedImport:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PluginInputError(f"not valid JSON (use `inspect log convert --to json` for .eval files): {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("eval"), dict):
        raise PluginInputError("expected an Inspect EvalLog object with an `eval` section", "eval")
    spec = data["eval"]
    scorers = {s.get("name"): s for s in ((data.get("results") or {}).get("scores") or []) if isinstance(s, dict)}
    samples = data.get("samples")
    warnings: list[str] = []
    if samples is None:
        samples = []
        warnings.append("the log has no samples (header-only log); only the run identity was imported")
    results: list[NormalizedResult] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise PluginInputError(f"sample {index} is not an object", f"samples[{index}]")
        scores, verdicts = [], []
        for name, score in (sample.get("scores") or {}).items():
            normalized, verdict = _score(name, score if isinstance(score, dict) else {"value": score},
                                         scorers.get(name) or {})
            scores.append(normalized)
            verdicts.append(verdict)
        output = sample.get("output") or {}
        completion = output.get("completion")
        if completion is None and output.get("choices"):
            completion = _text((output["choices"][0].get("message") or {}).get("content"))
        target = sample.get("target")
        error = sample.get("error")
        metadata = sample.get("metadata") or {}
        sample_id = sample.get("id", index)
        results.append(NormalizedResult(
            upstream_id=f"{sample_id}#{sample.get('epoch', 1)}"[:200],
            case_external_id=str(metadata.get("external_id") or sample_id),
            epoch=sample.get("epoch"),
            provider=output.get("model") or spec.get("model"),
            input={"text": _text(sample.get("input"))} if not isinstance(sample.get("input"), list)
            else {"messages": sample.get("input")},
            expected={"target": target} if target not in (None, "", []) else None,
            output={"text": completion, "stop_reason": ((output.get("choices") or [{}])[0] or {}).get("stop_reason")},
            status=_status(verdicts, error),
            scores=scores,
            error={"message": error.get("message") if isinstance(error, dict) else str(error),
                   "source": "inspect sample.error"} if error else None,
            extra={"sample_id": sample_id, "explanations": {n: (s or {}).get("explanation")
                                                            for n, s in (sample.get("scores") or {}).items()
                                                            if isinstance(s, dict)},
                   "metadata": metadata},
        ))
    identity = {"run_id": spec.get("run_id"), "eval_id": spec.get("eval_id"), "task": spec.get("task"),
                "task_id": spec.get("task_id"), "task_version": spec.get("task_version"),
                "model": spec.get("model"), "created": spec.get("created"),
                "dataset": (spec.get("dataset") or {}).get("name"), "status": data.get("status"),
                "log_version": data.get("version"),
                "aggregate_scores": {name: {m: (v or {}).get("value") for m, v in (s.get("metrics") or {}).items()}
                                     for name, s in scorers.items()}}
    inspect_version = (spec.get("packages") or {}).get("inspect_ai")
    if data.get("status") not in (None, "success"):
        warnings.append(f"the upstream eval status is {data.get('status')!r}")
    return NormalizedImport(plugin=PLUGIN_ID, plugin_version=PLUGIN_VERSION, source_version=inspect_version,
                            source_identity=identity, results=results, summary=summarize(results), warnings=warnings)


def capabilities(settings=None) -> dict[str, Any]:
    installed = module_available("inspect_ai")
    return {"import": {"available": True},
            "run": {"available": installed, "version": module_version("inspect-ai") if installed else None,
                    "reason": None if installed else f"inspect_ai is not installed ({INSTALL})"}}


def run_task(task: str, model: str, log_dir: Path, limit: int | None = None) -> bytes:
    """Run an Inspect task and return its JSON log. Needs inspect_ai; makes model calls."""
    inspect_ai = require("inspect_ai", INSTALL)
    log_dir.mkdir(parents=True, exist_ok=True)
    logs = inspect_ai.eval(task, model=model, log_dir=str(log_dir), log_format="json", limit=limit)
    if not logs:
        raise PluginInputError("Inspect returned no log")
    location = getattr(logs[0], "location", None)
    if not location:
        raise PluginInputError("Inspect log has no location")
    return Path(str(location).removeprefix("file://")).read_bytes()
