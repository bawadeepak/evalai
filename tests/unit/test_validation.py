"""Validators return every problem at once, with row numbers and paths."""

from eval_triage.domain.scenario import validate_document


def _doc(**overrides):
    base = {
        "schema_version": 1,
        "name": "routing",
        "pack": "exact_classification",
        "contract": "Route messages.",
        "allowed_labels": ["billing", "technical"],
        "slice_keys": ["difficulty"],
        "graders": [{"name": "label", "kind": "deterministic", "checks": ["label_match"]}],
        "dataset": {"name": "d", "cases": []},
    }
    base.update(overrides)
    return base


def test_all_row_errors_reported_with_rows():
    cases = [
        {"external_id": "A", "input": {"text": "x"}, "expected": {"label": "billing"}, "tags": {"difficulty": "e"}},
        {"external_id": "B", "input": {}, "expected": {"label": "nope"}},
        {"external_id": "bad id!", "input": {"text": "y"}, "expected": {"label": "billing"}},
        {"external_id": "A", "input": {"text": "z"}, "expected": {"label": "technical"}, "weight": -1},
        {"external_id": "D", "input": {"text": "x"}, "expected": {"label": "billing"}, "tags": {"difficulty": "e"}},
    ]
    report = validate_document(_doc(dataset={"name": "d", "cases": cases}))
    assert not report.ok
    rows = {e.row for e in report.errors}
    assert {1, 2, 3} <= rows
    paths = [e.path for e in report.errors]
    assert "dataset.cases[1].input.text" in paths
    assert "dataset.cases[1].expected.label" in paths
    assert any(e.code == "duplicate_content" and e.row == 4 for e in report.warnings)
    assert any(e.code == "slice_tag" for e in report.warnings)
    assert len(report.cases) == 2  # only fully valid rows are kept


def test_header_errors_and_grader_checks():
    report = validate_document(_doc(
        pack="nonsense", graders=[{"name": "g", "kind": "deterministic", "checks": ["mystery"]}],
        critical_invariants=["made_up"],
    ))
    messages = " ".join(e.message for e in report.errors)
    assert "pack" in {e.path for e in report.errors}
    assert "unknown checks" in messages


def test_duplicate_external_id_and_cluster_leak():
    cases = [
        {"external_id": "A", "cluster_id": "k", "split": "calibration", "input": {"text": "1"},
         "expected": {"label": "billing"}},
        {"external_id": "A", "cluster_id": "k", "split": "test", "input": {"text": "2"},
         "expected": {"label": "billing"}},
    ]
    report = validate_document(_doc(dataset={"name": "d", "cases": cases}))
    codes = {e.code for e in report.errors}
    assert {"duplicate_id", "cluster_split_leak"} <= codes


def test_pass_rule_and_pack_cross_checks():
    doc = {
        "schema_version": 1, "name": "agent", "pack": "tool_agent", "contract": "c",
        "tools": [{"name": "lookup", "arguments_schema": {"type": "object"}}],
        "graders": [{"name": "judge", "kind": "model", "rubric": "r"}],
        "dataset": {"name": "d", "pass_rule": {"mandatory_graders": ["missing"]}, "cases": [
            {"external_id": "T1", "input": {"task": "t"},
             "expected": {"required_tools": ["lookup", "refund"], "must_precede": [["a", "b"], ["b", "a"]]}},
            {"external_id": "T2", "input": {"task": "t"}, "expected": {"required_tools": ["refund"]}},
        ]},
    }
    report = validate_document(doc)
    messages = " | ".join(e.message for e in report.errors)
    assert "cycle" in messages
    assert "not declared in the scenario" in messages
    assert "unknown graders" in messages


def test_rag_documents_must_exist_and_memory_steps_must_exist():
    rag = {
        "schema_version": 1, "name": "r", "pack": "rag", "contract": "c",
        "corpus": [{"id": "d1", "text": "t"}],
        "graders": [{"name": "a", "kind": "deterministic", "checks": ["answer_contains"]}],
        "dataset": {"name": "d", "cases": [
            {"external_id": "Q", "input": {"question": "q"}, "expected": {"relevant_ids": ["d9"]}},
            {"external_id": "Q2", "input": {"question": "q"}, "expected": {"relevance": {"d1": 7},
                                                                           "relevant_ids": ["d1"]}},
        ]},
    }
    report = validate_document(rag)
    messages = " | ".join(e.message for e in report.errors)
    assert "not in the scenario corpus" in messages
    assert "unsupported scale" in messages

    memory = {
        "schema_version": 1, "name": "m", "pack": "memory_lifecycle", "contract": "c",
        "graders": [{"name": "m", "kind": "deterministic", "checks": ["recall_budget"]}],
        "dataset": {"name": "d", "cases": [
            {"external_id": "M", "episode": [{"id": "e1", "action": "remember", "args": {"text": "x"}}],
             "expected": {"recall_budget": {"step": "r9"}}},
            {"external_id": "N", "input": {}, "expected": {"no_durable_fact": True}},
        ]},
    }
    report = validate_document(memory)
    messages = " | ".join(e.message for e in report.errors)
    assert "unknown steps ['r9']" in messages
    assert "need an episode" in messages


def test_valid_document_ok_and_pass_rule_defaults():
    cases = [{"external_id": "A", "input": {"text": "x"}, "expected": {"label": "billing"},
              "tags": {"difficulty": "easy"}}]
    report = validate_document(_doc(dataset={"name": "d", "cases": cases}))
    assert report.ok, report.errors
    assert report.scenario.pass_rule() == {"policy": "all_mandatory_pass", "mandatory_graders": ["label"]}
    assert len(report.scenario.scenario_hash()) == 64
