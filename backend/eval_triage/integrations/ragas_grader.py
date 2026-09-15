"""Ragas grader plugin (optional; ``ragas`` is not a core dependency).

Grader spec: ``{kind: external, config: {plugin: ragas, metric: <MetricClass>,
threshold?: float, direction?: higher_is_better|lower_is_better}}``.

Only metrics that need no evaluator LLM are run (e.g. ``NonLLMContextRecall``,
``NonLLMContextPrecisionWithReference``, ``NonLLMStringSimilarity``,
``ExactMatch``, ``StringPresence``). LLM-based metrics such as faithfulness are
reported unavailable rather than run with an unconfigured judge. Every result
records the exact Ragas version, the metric definition and the judge
configuration (none for non-LLM metrics). A numeric score without a declared
threshold is not a pass/fail verdict.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
from typing import Any

from eval_triage.domain.enums import Verdict
from eval_triage.graders.base import NOT_A_BINARY_VERDICT, NOT_APPLICABLE, GradeResult, GradingContext
from eval_triage.integrations.base import (
    PluginInfo,
    PluginUnavailable,
    module_available,
    module_version,
    require,
)

PLUGIN_ID = "ragas"
PLUGIN_VERSION = "ragas_grader_v1"
INSTALL = "optional: install ragas into this environment"

INFO = PluginInfo(
    id=PLUGIN_ID, version=PLUGIN_VERSION, title="Ragas",
    purpose="Retrieval and grounding metrics as an external grader",
    supported_packs=("rag", "reference_answer"),
    input_description="Grader config {plugin: 'ragas', metric, threshold?, direction?}",
    input_schema={"type": "object", "required": ["plugin", "metric"],
                  "properties": {"plugin": {"const": "ragas"}, "metric": {"type": "string"},
                                 "threshold": {"type": "number"},
                                 "direction": {"enum": ["higher_is_better", "lower_is_better"]}}},
    operations=("grade",),
    install=INSTALL,
)


def capabilities(settings=None) -> dict[str, Any]:
    installed = module_available("ragas")
    return {"grade": {"available": installed, "version": _version() if installed else None,
                      "reason": None if installed else f"ragas is not installed ({INSTALL})",
                      "llm_metrics": "unavailable: no evaluator LLM wiring; use non-LLM metrics"}}


def _version() -> str | None:
    return module_version("ragas")


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "question", "query", "prompt"):
            if isinstance(value.get(key), str):
                return value[key]
    return None


def _contexts(ctx: GradingContext) -> tuple[list[str] | None, list[str] | None]:
    definition = ctx.scenario.get("definition") or ctx.scenario
    corpus = {d.get("id"): d.get("text") for d in definition.get("corpus") or [] if isinstance(d, dict)}
    output = ctx.output or {}
    retrieved = output.get("retrieved_contexts")
    if retrieved is None and output.get("retrieved_ids") is not None:
        retrieved = [corpus.get(i) for i in output["retrieved_ids"] if corpus.get(i)]
    expected = ctx.expected
    reference_ids = expected.get("relevant_ids") or expected.get("relevant_documents")
    reference = [corpus.get(i) for i in reference_ids if corpus.get(i)] if isinstance(reference_ids, list) else None
    return retrieved, reference


def _score(metric, sample) -> float:
    if hasattr(metric, "single_turn_score"):
        return float(metric.single_turn_score(sample))
    coroutine = metric.single_turn_ascore(sample)
    if not inspect.isawaitable(coroutine):
        return float(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:  # safe inside a running event loop
        return float(pool.submit(asyncio.run, coroutine).result(timeout=120))


def grade(ctx: GradingContext) -> GradeResult:
    config = ctx.grader.get("config") or {}
    try:
        ragas = require("ragas", INSTALL)
    except PluginUnavailable as exc:
        return GradeResult(Verdict.UNAVAILABLE, reason=str(exc))
    metric_name = str(config.get("metric") or "")
    metrics_module = require("ragas.metrics", INSTALL)
    metric_class = getattr(metrics_module, metric_name, None)
    if metric_class is None:
        return GradeResult(Verdict.ERROR, reason="unknown_ragas_metric",
                           error={"code": "unknown_ragas_metric", "message": f"ragas.metrics has no {metric_name!r}"})
    metric = metric_class()
    if getattr(metric, "llm", None) is not None or "llm" in getattr(metric_class, "__dataclass_fields__", {}):
        return GradeResult(Verdict.UNAVAILABLE,
                           reason=f"{metric_name} needs an evaluator LLM; Eval Triage does not wire one into Ragas. "
                                  "Use a non-LLM metric or a model-judge grader.")
    schema = require("ragas.dataset_schema", INSTALL)
    retrieved, reference_contexts = _contexts(ctx)
    expected = ctx.expected
    reference = next((expected[k] for k in ("reference", "answer", "target") if isinstance(expected.get(k), str)), None)
    fields = {"user_input": _text(ctx.case.get("input")), "response": (ctx.output or {}).get("text"),
              "retrieved_contexts": retrieved, "reference": reference, "reference_contexts": reference_contexts}
    sample = schema.SingleTurnSample(**{k: v for k, v in fields.items() if v is not None})
    required = getattr(metric, "_required_columns", None)
    if isinstance(required, dict):
        needed = {c.split(":")[0] for cols in required.values() for c in cols}
        missing = sorted(c for c in needed if fields.get(c) is None)
        if missing:
            return GradeResult(Verdict.UNAVAILABLE, reason=NOT_APPLICABLE,
                               explanation=f"{metric_name} needs {', '.join(missing)} for this case")
    value = _score(metric, sample)
    version = getattr(ragas, "__version__", None) or _version()
    doc = (metric_class.__doc__ or "").strip().splitlines()
    record = {"ragas": {"metric": metric_name, "value": value, "implementation_version": f"ragas {version}",
                        "plugin_version": PLUGIN_VERSION, "definition": doc[0] if doc else metric_name,
                        "judge": None, "is_probability": False}}
    threshold = config.get("threshold")
    if threshold is None:
        return GradeResult(Verdict.UNAVAILABLE, reason=NOT_A_BINARY_VERDICT, metric=record,
                           explanation=f"{metric_name} = {value:.4f} (no threshold declared, so no verdict)")
    higher = config.get("direction", "higher_is_better") == "higher_is_better"
    passed = value >= float(threshold) if higher else value <= float(threshold)
    return GradeResult(Verdict.PASS if passed else Verdict.FAIL, metric=record,
                       explanation=f"{metric_name} = {value:.4f} {'≥' if higher else '≤'} {threshold} required")
