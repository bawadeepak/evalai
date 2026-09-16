"""The optional integrations against their real packages.

These run when the extras are installed (``uv sync --extra inspect --extra ragas``)
and skip otherwise, so the suite stays green in a core-only environment. Both
tests are offline: Inspect runs against its built-in ``mockllm/model`` and the
Ragas metrics used here need no evaluator LLM.
"""

from pathlib import Path

import pytest

from eval_triage.domain.enums import Verdict
from eval_triage.graders.base import NOT_A_BINARY_VERDICT, GradingContext
from eval_triage.graders.runner import grade
from eval_triage.integrations import inspect_logs, ragas_grader
from eval_triage.integrations.base import module_available

TASK = Path(__file__).resolve().parents[2] / "fixtures" / "integrations" / "inspect" / "capitals_task.py"

needs_inspect = pytest.mark.skipif(not module_available("inspect_ai"), reason="the [inspect] extra is not installed")
needs_ragas = pytest.mark.skipif(not module_available("ragas"), reason="the [ragas] extra is not installed")


def _context(config: dict, *, response: str = "Paris", reference: str = "Paris") -> GradingContext:
    return GradingContext(
        scenario={"pack": "reference_answer"},
        case={"input": {"question": "What is the capital of France?"}, "expected": {"reference": reference}},
        grader={"name": "ragas", "kind": "external", "config": config},
        trial_status="success", output={"text": response})


@needs_inspect
def test_inspect_task_runs_and_its_log_imports(tmp_path):
    """The runner drives real Inspect; the importer reads the log it wrote."""
    raw = inspect_logs.run_task(str(TASK), "mockllm/model", tmp_path / "logs")
    parsed = inspect_logs.parse(raw)

    assert parsed.plugin == "inspect" and parsed.source_version  # the installed inspect_ai version
    assert len(parsed.results) == 2
    assert {r.case_external_id for r in parsed.results} == {"cap-fr", "cap-au"}
    assert parsed.source_identity["task"] == "capitals"
    assert parsed.source_identity["run_id"] and parsed.source_identity["model"] == "mockllm/model"
    for result in parsed.results:
        assert result.upstream_id.endswith("#1")  # sample id + epoch
        assert result.output and result.output["text"]
        assert result.expected and result.expected["target"] in ("Paris", "Canberra")
        assert result.scores and all(s.is_probability is False for s in result.scores)
        assert result.status in ("pass", "fail", "unscored")
    assert inspect_logs.capabilities()["run"]["available"] is True


@needs_ragas
def test_ragas_grader_scores_with_the_real_package():
    """A non-LLM metric produces a verdict only with a declared threshold."""
    passed = grade(_context({"plugin": "ragas", "metric": "ExactMatch", "threshold": 1.0}))
    assert passed.verdict == Verdict.PASS, passed.reason
    record = passed.metric["ragas"]
    assert record["value"] == 1.0 and record["metric"] == "ExactMatch"
    assert record["implementation_version"].startswith("ragas ")
    assert record["judge"] is None and record["is_probability"] is False

    failed = grade(_context({"plugin": "ragas", "metric": "ExactMatch", "threshold": 1.0}, response="Lyon"))
    assert failed.verdict == Verdict.FAIL and failed.metric["ragas"]["value"] == 0.0

    measured = grade(_context({"plugin": "ragas", "metric": "ExactMatch"}))
    assert measured.verdict == Verdict.UNAVAILABLE and measured.reason == NOT_A_BINARY_VERDICT

    llm_metric = grade(_context({"plugin": "ragas", "metric": "Faithfulness", "threshold": 0.5}))
    assert llm_metric.verdict == Verdict.UNAVAILABLE and "evaluator LLM" in llm_metric.reason

    unknown = grade(_context({"plugin": "ragas", "metric": "NoSuchMetric"}))
    assert unknown.verdict == Verdict.ERROR
    assert ragas_grader.capabilities()["grade"]["available"] is True
