import pytest

from eval_triage.statistics.classification import class_metrics, pairwise_win_rate, position_consistency
from eval_triage.statistics.facts import match_exact, match_weighted
from eval_triage.statistics.operational import (
    cost_per_confirmed_success,
    cost_summary,
    latency_summary,
    slot_rates,
)
from eval_triage.statistics.representation import category
from eval_triage.statistics.retrieval import retrieval_metrics


def test_retrieval_empty_set_rules():
    none_relevant = retrieval_metrics([], ["a"], k=3, intentional_no_answer=True)
    assert none_relevant["recall_at_k"]["value"] is None
    assert "intentionally" in none_relevant["recall_at_k"]["reason"]
    assert none_relevant["ndcg_at_k"]["value"] is None
    assert none_relevant["precision_at_k"]["value"] == 0
    nothing_retrieved = retrieval_metrics(["a"], [], k=3)
    assert nothing_retrieved["recall_at_k"]["value"] == 0
    assert nothing_retrieved["reciprocal_rank"]["value"] == 0
    assert nothing_retrieved["precision_at_k"]["value"] is None
    graded = retrieval_metrics(["d4", "d2"], ["d4", "d2", "d1"], k=3, relevance={"d4": 3, "d2": 2})
    assert graded["ndcg_at_k"]["value"] == pytest.approx(1.0)
    swapped = retrieval_metrics(["d4", "d2"], ["d2", "d4"], k=3, relevance={"d4": 3, "d2": 2})
    assert swapped["ndcg_at_k"]["value"] < 1
    with pytest.raises(ValueError):
        retrieval_metrics(["a"], ["a"], k=1, relevance={"a": 9})


def test_fact_empty_set_rules():
    reference = [{"subject": "ana", "relation": "lives_in", "object": "Oslo"}]
    no_predictions = match_exact([], reference)
    assert no_predictions["precision"] is None and no_predictions["recall"] == 0 and no_predictions["f1"] == 0
    both_empty = match_exact([], [])
    assert both_empty["f1"] is None and "no-facts-required" in both_empty["f1_reason"]
    normalised = match_exact([{"subject": "ANA", "relation": "lives_in", "object": "  oslo"}], reference)
    assert normalised["tp"] == 1


def test_weighted_matching_discards_pairs_below_threshold():
    similarity = [[0.95, 0.2], [0.3, 0.55], [0.9, 0.1]]
    result = match_weighted(similarity, threshold=0.6)
    assert [(p, r) for p, r, _ in result["matches"]] == [(0, 0)]
    assert result["unmatched_reference"] == [1]
    assert result["tp"] == 1 and result["fp"] == 2 and result["fn"] == 1
    review = match_weighted([[0.65]], threshold=0.6)
    assert review["needs_review"]


def test_class_metrics_micro_macro_and_omitted():
    pairs = [("billing", "billing"), ("billing", "technical"), ("technical", "technical"), ("account", "other")]
    result = class_metrics(pairs, ["billing", "technical", "account", "other"])
    assert result["accuracy"] == 0.5
    assert result["per_class"]["billing"]["recall"] == 0.5
    assert result["per_class"]["technical"]["precision"] == 0.5
    assert "other" in result["macro_f1"]["omitted_classes"]
    assert result["micro"]["f1"] == pytest.approx(0.5)


def test_win_rate_and_position_consistency():
    result = pairwise_win_rate(["win", "win", "tie", "loss", "abstain"])
    assert result["win_rate"] == pytest.approx(2.5 / 4)
    assert result["abstentions"] == 1
    assert pairwise_win_rate(["abstain"])["win_rate"] is None
    assert position_consistency([("win", "win"), ("win", "loss")])["inconsistent"] == 1


def test_operational_definitions():
    rates = slot_rates(scheduled=10, generated=8, graded=7, eligible=8, passed=5, failed=2)
    assert rates["target_completion"]["value"] == 0.8
    assert rates["grade_coverage"]["value"] == pytest.approx(7 / 8)
    assert rates["conditional_pass"]["value"] == pytest.approx(5 / 7)
    assert rates["observed_success_yield"]["value"] == 0.5
    assert rates["unresolved"] == 3
    assert slot_rates(0, 0, 0, 0, 0, 0)["target_completion"]["value"] is None
    latency = latency_summary([100, 200, 300, 400], timeouts=2)
    assert latency["p50_ms"] == 250 and latency["timeouts"] == 2
    partial = cost_summary([{"amount": 0.5, "currency": "USD"}, {"amount": None, "currency": None}])
    assert partial["complete"] is False and partial["coverage"] == 0.5
    assert cost_per_confirmed_success(partial, 3)["value"] is None
    full = cost_summary([{"amount": 0.5, "currency": "USD"}, {"amount": 0.1, "currency": "USD", "kind": "judge"}])
    assert cost_per_confirmed_success(full, 3)["value"] == pytest.approx(0.2)
    assert full["by_kind"]["judge"]["USD"] == pytest.approx(0.1)


def test_representations():
    assert category({"text": "a"}, "raw") == category({"text": "a"}, "raw")
    assert category({"text": '{"b":1,"a":2}'}, "json")[0] == category({"text": '{"a": 2, "b": 1}'}, "json")[0]
    assert category({"text": "not json"}, "json") == (None, "output is not valid JSON")
    assert category({"text": "x"}, "semantic") == (None, "no semantic class assigned")
    assert category({"text": "x"}, "semantic", "correct")[0] == "semantic:correct"
