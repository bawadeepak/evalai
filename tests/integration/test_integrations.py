"""Optional integrations (M9).

* Promptfoo and Inspect importers keep upstream identifiers, assertion types,
  statuses, reasons and error provenance, and never treat scores as probabilities.
* Imports are immutable, keep the original file, and redact secret-like values.
* The Promptfoo runner needs explicit configuration; the Inspect runner and the
  Ragas grader need their optional packages. Contract tests use stand-in modules,
  because neither package is installed in this environment.
* The core app starts without any optional package, and project export/import
  carries imported results.
"""

import importlib.machinery
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval_triage.db.migrate import ImmutableRecordError
from eval_triage.db.models import ExternalResult
from eval_triage.domain.enums import Verdict
from eval_triage.domain.fixtures import FIXTURES_DIR
from eval_triage.graders.base import NOT_A_BINARY_VERDICT, GradingContext
from eval_triage.graders.runner import grade
from eval_triage.integrations import inspect_logs, promptfoo, ragas_grader
from eval_triage.integrations.base import module_available
from tests.conftest import SENTINEL_SECRET
from tests.integration.helpers import make_project, run_all

PROMPTFOO = FIXTURES_DIR / "integrations" / "promptfoo" / "results.json"
INSPECT = FIXTURES_DIR / "integrations" / "inspect" / "eval_log.json"


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


# --- importers ---------------------------------------------------------------------------------


def test_promptfoo_import_preserves_assertions_and_error_provenance():
    parsed = promptfoo.parse(PROMPTFOO.read_bytes())
    assert [r.status for r in parsed.results] == ["pass", "fail", "error"]
    assert [r.case_external_id for r in parsed.results] == ["PF-01", "PF-02", "PF-03"]
    injection = parsed.results[1]
    assert [(a.type, a.status) for a in injection.assertions] == [("not-icontains", "fail"), ("llm-rubric", "pass")]
    assert "system prompt" in injection.assertions[0].reason
    assert injection.assertions[1].provenance["metric"] == "refusal"
    assert all(s.is_probability is False for r in parsed.results for s in r.scores)
    assert "not a probability" in injection.scores[0].definition
    error = parsed.results[2].error
    assert "connection reset" in error["message"] and error["failure_reason"] == 2
    assert parsed.source_identity["eval_id"] == "eval-synthetic-2026-09-16"
    assert parsed.summary["pass"] == 1 and parsed.summary["fail"] == 1 and parsed.summary["error"] == 1


def test_inspect_import_keeps_upstream_identity():
    parsed = inspect_logs.parse(INSPECT.read_bytes())
    by_id = {r.upstream_id: r for r in parsed.results}
    assert list(by_id) == ["cap-fr#1", "cap-au#1", "cap-ca#1", "cap-nz#1"]
    assert [r.status for r in parsed.results] == ["pass", "fail", "unscored", "error"]
    assert by_id["cap-fr#1"].case_external_id == "CAP-FR" and by_id["cap-fr#1"].epoch == 1
    assert by_id["cap-ca#1"].input == {"messages": [{"role": "user", "content": "Capital of Canada?"}]}
    assert by_id["cap-ca#1"].scores[0].note == "partial"  # a partial letter is not forced into pass/fail
    length = next(s for s in by_id["cap-fr#1"].scores if s.name == "length")
    assert length.kind == "numeric" and "not a probability" in length.note
    assert parsed.source_identity["run_id"] == "synthetic-run-7Qm2"
    assert parsed.source_identity["task_id"] == "synthetic-task-001"
    assert parsed.source_version == "0.3.0-synthetic"
    assert "Synthetic model error" in by_id["cap-nz#1"].error["message"]


def test_invalid_result_files_are_rejected_with_reasons(client, ctx):
    project = make_project(ctx)
    bad = client.post("/api/v1/integrations/promptfoo/imports",
                      json={"project_id": project, "filename": "x.json", "content": '{"results": 3}'})
    assert bad.status_code == 422 and "Promptfoo file is invalid" in bad.json()["error"]["message"]
    not_inspect = client.post("/api/v1/integrations/inspect/imports",
                              json={"project_id": project, "filename": "x.json", "content": "[]"})
    assert not_inspect.status_code == 422
    unknown = client.post("/api/v1/integrations/nope/imports",
                          json={"project_id": project, "filename": "x.json", "content": "{}"})
    assert unknown.status_code == 404


def test_imports_are_stored_immutably_with_the_original_file(client, ctx):
    project = make_project(ctx)
    raw = PROMPTFOO.read_text()
    created = client.post("/api/v1/integrations/promptfoo/imports",
                          json={"project_id": project, "filename": "results.json", "content": raw})
    assert created.status_code == 201
    body = created.json()["data"]
    assert body["result_count"] == 3 and body["summary"]["original_redacted"] is False
    listing = client.get("/api/v1/external-imports", params={"project_id": project}).json()["data"]
    assert [i["id"] for i in listing] == [body["id"]] and listing[0]["result_count"] == 3
    detail = client.get(f"/api/v1/external-imports/{body['id']}").json()
    assert detail["meta"]["total"] == 3 and detail["data"]["results"][1]["assertions"][0]["type"] == "not-icontains"
    failed = client.get(f"/api/v1/external-imports/{body['id']}", params={"status": "fail"}).json()
    assert [r["case_external_id"] for r in failed["data"]["results"]] == ["PF-02"]
    original = client.get(f"/api/v1/artifacts/{body['artifact_hash']}")
    assert original.status_code == 200 and original.content == raw.encode("utf-8")
    with pytest.raises(ImmutableRecordError), ctx.db.write() as session:
        row = session.query(ExternalResult).filter_by(import_id=body["id"], ordinal=1).one()
        row.status = "pass"
        session.flush()


def test_secret_like_values_in_imported_files_are_redacted(client, ctx):
    project = make_project(ctx)
    data = json.loads(PROMPTFOO.read_text())
    data["config"] = {"providers": [{"id": "openai:x", "config": {"apiKey": SENTINEL_SECRET}}]}
    data["results"]["results"][0]["response"]["output"] = f"leaked {SENTINEL_SECRET}"
    body = client.post("/api/v1/integrations/promptfoo/imports",
                       json={"project_id": project, "filename": "r.json", "content": json.dumps(data)}).json()["data"]
    assert body["summary"]["original_redacted"] is True
    stored = client.get(f"/api/v1/artifacts/{body['artifact_hash']}").text
    detail = client.get(f"/api/v1/external-imports/{body['id']}").text
    assert SENTINEL_SECRET not in stored and SENTINEL_SECRET not in detail


# --- optional packages and explicit configuration -------------------------------------------------


def test_plugins_are_optional_and_described(client):
    plugins = {p["id"]: p for p in client.get("/api/v1/integrations").json()["data"]}
    assert set(plugins) == {"promptfoo", "inspect", "ragas"}
    for plugin in plugins.values():
        assert plugin["version"] and plugin["supported_packs"] and plugin["input_schema"]
        assert "upstream_id" in plugin["result_schema"]["properties"]
    assert plugins["inspect"]["capabilities"]["import"]["available"] is True
    assert plugins["inspect"]["capabilities"]["run"]["available"] is module_available("inspect_ai")
    assert plugins["ragas"]["capabilities"]["grade"]["available"] is module_available("ragas")
    assert plugins["promptfoo"]["capabilities"]["run"]["available"] is False  # not configured
    health = client.get("/api/v1/health").json()["data"]["plugins"]
    assert set(health) == {"promptfoo", "inspect", "ragas"} and health["promptfoo"]["import_available"]
    # The core app never imports the optional packages.
    assert "inspect_ai" not in sys.modules and "ragas" not in sys.modules


def test_promptfoo_runner_requires_explicit_configuration(client, ctx):
    project = make_project(ctx)
    refused = client.post("/api/v1/integrations/promptfoo/runs", json={"project_id": project, "config": "suite.yaml"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "plugin_unavailable"


def test_configured_promptfoo_suite_runs_and_is_imported(client, ctx, tmp_path):
    workdir = tmp_path / "suites"
    workdir.mkdir()
    (workdir / "suite.yaml").write_text("description: synthetic\n")
    fake = tmp_path / "fake_promptfoo.py"
    fake.write_text("import shutil, sys\nargs = sys.argv[1:]\n"
                    f"shutil.copy({str(PROMPTFOO)!r}, args[args.index('-o') + 1])\n")
    ctx.settings.promptfoo_command = f"{sys.executable} {fake}"
    ctx.settings.promptfoo_workdir = workdir
    project = make_project(ctx)
    escape = client.post("/api/v1/integrations/promptfoo/runs", json={"project_id": project, "config": "../x.yaml"})
    assert escape.status_code == 422
    started = client.post("/api/v1/integrations/promptfoo/runs", json={"project_id": project, "config": "suite.yaml"})
    assert started.status_code == 202
    run_all(ctx, seconds=30)
    job = client.get(f"/api/v1/jobs/{started.json()['data']['job_id']}").json()["data"]
    assert job["result"]["ok"], job
    detail = client.get(f"/api/v1/external-imports/{job['result']['import_id']}").json()
    assert detail["data"]["summary"]["run"]["returncode"] == 0 and detail["meta"]["total"] == 3
    assert detail["data"]["filename"] == "suite.yaml"


def test_inspect_runner_uses_inspect_ai_only_when_present(client, ctx, monkeypatch):
    project = make_project(ctx)
    if not module_available("inspect_ai"):
        refused = client.post("/api/v1/integrations/inspect/runs",
                              json={"project_id": project, "task": "capitals.py", "model": "mockllm/model"})
        assert refused.status_code == 409
    calls = []

    def fake_eval(task, model, log_dir, log_format, limit):
        calls.append((task, model, log_format, limit))
        path = Path(log_dir) / "log.json"
        path.write_bytes(INSPECT.read_bytes())
        return [SimpleNamespace(location=str(path))]

    monkeypatch.setitem(sys.modules, "inspect_ai", _module("inspect_ai", eval=fake_eval))
    started = client.post("/api/v1/integrations/inspect/runs",
                          json={"project_id": project, "task": "capitals.py", "model": "mockllm/model", "limit": 4})
    assert started.status_code == 202
    run_all(ctx, seconds=30)
    job = client.get(f"/api/v1/jobs/{started.json()['data']['job_id']}").json()["data"]
    assert job["result"]["ok"], job
    assert calls == [("capitals.py", "mockllm/model", "json", 4)]
    detail = client.get(f"/api/v1/external-imports/{job['result']['import_id']}").json()["data"]
    assert detail["plugin"] == "inspect" and detail["source_identity"]["run_id"] == "synthetic-run-7Qm2"


# --- Ragas grader -------------------------------------------------------------------------------


def _rag_context(config) -> GradingContext:
    return GradingContext(
        scenario={"pack": "rag", "corpus": [{"id": "d1", "text": "Paris is in France."},
                                            {"id": "d2", "text": "Canberra is in Australia."}]},
        case={"input": {"question": "Where is Paris?"}, "expected": {"relevant_ids": ["d1", "d2"]}},
        grader={"name": "ragas-recall", "kind": "external", "config": config},
        trial_status="success", output={"text": "France", "retrieved_ids": ["d1"]})


def test_ragas_grader_is_unavailable_without_the_package():
    if module_available("ragas"):
        pytest.skip("ragas is installed here")
    result = grade(_rag_context({"plugin": "ragas", "metric": "NonLLMContextRecall"}))
    assert result.verdict == Verdict.UNAVAILABLE and "ragas is not installed" in result.reason


@pytest.fixture
def stub_ragas(monkeypatch):
    class SingleTurnSample:
        def __init__(self, **fields):
            self.user_input = self.response = self.retrieved_contexts = None
            self.reference = self.reference_contexts = None
            self.__dict__.update(fields)

    class NonLLMContextRecall:
        """Fraction of reference contexts found among the retrieved contexts (stub)."""

        _required_columns = {"SINGLE_TURN": {"retrieved_contexts", "reference_contexts"}}

        def single_turn_score(self, sample):
            found = set(sample.retrieved_contexts) & set(sample.reference_contexts)
            return len(found) / len(sample.reference_contexts)

    class Faithfulness:
        """Needs an evaluator LLM (stub)."""

        __dataclass_fields__ = {"llm": None}

    monkeypatch.setitem(sys.modules, "ragas", _module("ragas", __version__="0.0-stub"))
    monkeypatch.setitem(sys.modules, "ragas.metrics",
                        _module("ragas.metrics", NonLLMContextRecall=NonLLMContextRecall, Faithfulness=Faithfulness))
    monkeypatch.setitem(sys.modules, "ragas.dataset_schema",
                        _module("ragas.dataset_schema", SingleTurnSample=SingleTurnSample))


def test_ragas_grader_contract_with_stub_package(stub_ragas):
    measured = grade(_rag_context({"plugin": "ragas", "metric": "NonLLMContextRecall"}))
    assert measured.verdict == Verdict.UNAVAILABLE and measured.reason == NOT_A_BINARY_VERDICT
    record = measured.metric["ragas"]
    assert record["value"] == 0.5 and record["implementation_version"] == "ragas 0.0-stub"
    assert record["judge"] is None and record["is_probability"] is False
    assert record["definition"].startswith("Fraction of reference contexts")
    assert grade(_rag_context({"plugin": "ragas", "metric": "NonLLMContextRecall", "threshold": 0.4})).verdict \
        == Verdict.PASS
    assert grade(_rag_context({"plugin": "ragas", "metric": "NonLLMContextRecall", "threshold": 0.6})).verdict \
        == Verdict.FAIL
    llm = grade(_rag_context({"plugin": "ragas", "metric": "Faithfulness"}))
    assert llm.verdict == Verdict.UNAVAILABLE and "evaluator LLM" in llm.reason
    unknown = grade(_rag_context({"plugin": "ragas", "metric": "NoSuchMetric"}))
    assert unknown.verdict == Verdict.ERROR
    assert ragas_grader.capabilities()["grade"]["available"] is True


# --- exchange -----------------------------------------------------------------------------------


def test_export_import_carries_imported_results(client, ctx):
    project = make_project(ctx)
    client.post("/api/v1/integrations/inspect/imports",
                json={"project_id": project, "filename": "log.json", "content": INSPECT.read_text()})
    export = client.post("/api/v1/exports", json={"project_id": project}).json()["data"]
    redacted = client.post("/api/v1/exports", json={"project_id": project, "redact_text": True}).json()["data"]
    run_all(ctx, seconds=30)
    full = client.get(f"/api/v1/exports/{export['id']}").json()["data"]
    assert full["summary"]["counts"]["external_imports"] == 1 and full["summary"]["counts"]["external_results"] == 4
    assert client.get(f"/api/v1/exports/{redacted['id']}").json()["data"]["summary"]["counts"]["external_imports"] == 0
    archive = client.get(f"/api/v1/exports/{export['id']}/download").content
    started = client.post("/api/v1/imports", content=archive, headers={"Content-Type": "application/zip"})
    run_all(ctx, seconds=30)
    new_project = client.get(f"/api/v1/imports/{started.json()['data']['id']}").json()["data"]["project_id"]
    imported = client.get("/api/v1/external-imports", params={"project_id": new_project}).json()["data"]
    assert len(imported) == 1 and imported[0]["result_count"] == 4
    assert client.get(f"/api/v1/artifacts/{imported[0]['artifact_hash']}").status_code == 200
