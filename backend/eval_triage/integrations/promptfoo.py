"""Promptfoo results importer (built in) and the explicitly configured suite runner.

Import reads the JSON written by ``promptfoo eval -o results.json``. Each result
keeps its assertion types, pass/fail status and reasons, and error provenance.
Promptfoo's ``score`` is a weighted assertion score — it is recorded as an
external score and never treated as a probability.

Running suites needs an explicit command (``EVAL_TRIAGE_PROMPTFOO_COMMAND``) and
working directory; nothing is installed or downloaded by Eval Triage.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from eval_triage.integrations.base import (
    Assertion,
    ExternalScore,
    NormalizedImport,
    NormalizedResult,
    PluginInfo,
    PluginInputError,
    PluginUnavailable,
    summarize,
)

PLUGIN_ID = "promptfoo"
PLUGIN_VERSION = "promptfoo_import_v1"
SCORE_DEFINITION = ("Promptfoo aggregate score: weighted combination of assertion scores for this test. "
                    "It is not a probability of any event.")

INFO = PluginInfo(
    id=PLUGIN_ID, version=PLUGIN_VERSION, title="Promptfoo",
    purpose="Import Promptfoo result files and run explicitly configured security suites",
    supported_packs=("robustness_security", "reference_answer", "exact_classification"),
    input_description="JSON from `promptfoo eval -o results.json` (results format v2–v4)",
    input_schema={"type": "object", "required": ["results"],
                  "properties": {"evalId": {"type": "string"}, "results": {"type": ["object", "array"]}}},
    operations=("import", "run"),
    install="Import is built in. Running suites needs EVAL_TRIAGE_PROMPTFOO_COMMAND (e.g. a locally installed promptfoo) "
            "and EVAL_TRIAGE_PROMPTFOO_WORKDIR.",
)


def _results_list(data: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    block = data.get("results")
    if isinstance(block, list):
        return block, {}
    if isinstance(block, dict) and isinstance(block.get("results"), list):
        return block["results"], block
    raise PluginInputError("expected `results` to be a list or an object with a `results` list", "results")


def _status(item: dict[str, Any]) -> str:
    if item.get("error") and not item.get("gradingResult"):
        return "error"
    if item.get("failureReason") == 2:  # promptfoo ResultFailureReason.ERROR
        return "error"
    if item.get("success") is True:
        return "pass"
    if item.get("success") is False:
        return "fail"
    return "unscored"


def _assertions(item: dict[str, Any], index: int) -> list[Assertion]:
    grading = item.get("gradingResult") or {}
    out: list[Assertion] = []
    for n, component in enumerate(grading.get("componentResults") or []):
        assertion = component.get("assertion") or {}
        passed = component.get("pass")
        out.append(Assertion(
            type=str(assertion.get("type", "unknown")),
            status="pass" if passed is True else "fail" if passed is False else "skipped",
            reason=str(component.get("reason") or ""),
            value=assertion.get("value"),
            score=float(component["score"]) if isinstance(component.get("score"), int | float) else None,
            provenance={"source": "promptfoo gradingResult.componentResults", "result_index": index,
                        "component_index": n, "metric": assertion.get("metric"),
                        "weight": assertion.get("weight")},
        ))
    if not out and grading:
        out.append(Assertion(type="aggregate", status="pass" if grading.get("pass") else "fail",
                             reason=str(grading.get("reason") or ""),
                             provenance={"source": "promptfoo gradingResult", "result_index": index}))
    return out


def _scores(item: dict[str, Any]) -> list[ExternalScore]:
    scores: list[ExternalScore] = []
    if isinstance(item.get("score"), int | float):
        scores.append(ExternalScore(name="promptfoo_score", value=float(item["score"]), kind="numeric",
                                    definition=SCORE_DEFINITION, implementation_version=PLUGIN_VERSION))
    for name, value in (item.get("namedScores") or {}).items():
        if isinstance(value, int | float):
            scores.append(ExternalScore(name=f"named:{name}", value=float(value), kind="numeric",
                                        definition=f"Promptfoo named metric '{name}' as reported upstream.",
                                        implementation_version=PLUGIN_VERSION))
    return scores


def parse(raw: bytes | str) -> NormalizedImport:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PluginInputError(f"not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PluginInputError("expected a JSON object")
    items, block = _results_list(data)
    results: list[NormalizedResult] = []
    warnings: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PluginInputError(f"result {index} is not an object", f"results[{index}]")
        test = item.get("testCase") or {}
        provider = item.get("provider") or {}
        provider_id = provider.get("id") if isinstance(provider, dict) else str(provider)
        upstream = str(item.get("id") or f"{item.get('promptIdx', 0)}:{item.get('testIdx', index)}:{provider_id}")
        meta = test.get("metadata") or {}
        variables = test.get("vars") or item.get("vars") or {}
        response = item.get("response") or {}
        error = item.get("error")
        results.append(NormalizedResult(
            upstream_id=upstream[:200],
            case_external_id=(meta.get("external_id") or variables.get("external_id")),
            provider=provider_id,
            input={"vars": variables, "prompt": (item.get("prompt") or {}).get("raw"),
                   "description": test.get("description")},
            expected={"assert": test.get("assert")} if test.get("assert") else None,
            output={"text": response.get("output") if isinstance(response.get("output"), str)
                    else json.dumps(response.get("output")) if response.get("output") is not None else None},
            status=_status(item),
            assertions=_assertions(item, index),
            scores=_scores(item),
            error={"message": str(error), "source": "promptfoo result.error",
                   "failure_reason": item.get("failureReason")} if error else None,
            extra={"prompt_idx": item.get("promptIdx"), "test_idx": item.get("testIdx"),
                   "latency_ms": item.get("latencyMs"), "token_usage": response.get("tokenUsage"),
                   "prompt_label": (item.get("prompt") or {}).get("label")},
        ))
    if not results:
        warnings.append("the file contains no results")
    stats = block.get("stats") if isinstance(block, dict) else None
    identity = {"eval_id": data.get("evalId"), "timestamp": block.get("timestamp") if block else None,
                "results_version": block.get("version") if block else None,
                "providers": sorted({r.provider for r in results if r.provider}),
                "upstream_stats": stats}
    if data.get("shareableUrl"):
        warnings.append("the file references a share URL; it is stored as text and never opened")
    return NormalizedImport(plugin=PLUGIN_ID, plugin_version=PLUGIN_VERSION,
                            source_version=str(block.get("version")) if block and block.get("version") else None,
                            source_identity=identity, results=results, summary=summarize(results), warnings=warnings)


def capabilities(settings) -> dict[str, Any]:
    command = getattr(settings, "promptfoo_command", None)
    workdir = getattr(settings, "promptfoo_workdir", None)
    run_ok = bool(command) and workdir is not None and Path(workdir).is_dir()
    return {"import": {"available": True},
            "run": {"available": run_ok,
                    "reason": None if run_ok else "set EVAL_TRIAGE_PROMPTFOO_COMMAND and an existing "
                                                  "EVAL_TRIAGE_PROMPTFOO_WORKDIR to run suites"}}


def resolve_config(settings, config: str) -> Path:
    """A suite config must be a file inside the configured working directory."""
    workdir = getattr(settings, "promptfoo_workdir", None)
    if not getattr(settings, "promptfoo_command", None) or workdir is None:
        raise PluginUnavailable(capabilities(settings)["run"]["reason"])
    root = Path(workdir).expanduser().resolve()
    path = (root / config).resolve()
    if root not in path.parents or not path.is_file():
        raise PluginInputError("config must be an existing file inside the Promptfoo working directory", "config")
    return path


def run_suite(settings, config: str, timeout: float | None = None) -> tuple[bytes, dict[str, Any]]:
    """Run the configured command with ``-c <config> -o <json>`` and return the results file."""
    path = resolve_config(settings, config)
    command = shlex.split(settings.promptfoo_command)
    with tempfile.TemporaryDirectory(prefix="evalai-promptfoo-") as tmp:
        output = Path(tmp) / "results.json"
        argv = [*command, "-c", str(path), "-o", str(output)]
        completed = subprocess.run(argv, cwd=str(Path(settings.promptfoo_workdir).expanduser()),  # noqa: S603
                                   capture_output=True, text=True,
                                   timeout=timeout or settings.promptfoo_timeout_seconds, check=False)
        info = {"returncode": completed.returncode, "config": str(path.relative_to(Path(settings.promptfoo_workdir)
                                                                                      .expanduser().resolve())),
                "stderr_tail": completed.stderr[-2000:], "command": command[0]}
        if not output.is_file():
            raise PluginInputError(f"promptfoo wrote no results file (exit {completed.returncode})")
        return output.read_bytes(), info
