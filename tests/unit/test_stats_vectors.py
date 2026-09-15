"""Numerical acceptance vectors from docs/plan.md §12."""

import math

import pytest
from scipy import stats

from eval_triage.statistics import core as m
from eval_triage.statistics.bootstrap import paired_cluster_bootstrap
from eval_triage.statistics.facts import match_exact
from eval_triage.statistics.retrieval import retrieval_metrics


def test_wilson_18_of_20():
    low, high = m.wilson_interval(18, 20)
    assert abs(low - 0.6989663547715129) < 1e-9
    assert abs(high - 0.9721335187862318) < 1e-9
    with pytest.raises(m.StatisticsError):
        m.wilson_interval(0, 0)
    assert m.wilson_interval(20, 20)[0] < 1


def test_zero_failure_bounds():
    assert abs(m.zero_failure_upper_bound(100) - 0.029513049607039925) < 1e-12
    assert m.zero_failure_upper_bound(298) > 0.01
    assert m.zero_failure_upper_bound(299) < 0.01


def test_beta_posterior_is_not_wilson():
    assert m.beta_posterior(18, 20) == (19, 3)
    assert m.beta_posterior_mean(18, 20) == pytest.approx(19 / 22)
    low, high = m.beta_credible_interval(18, 20)
    assert low == pytest.approx(stats.beta.ppf(0.025, 19, 3))
    assert high == pytest.approx(stats.beta.ppf(0.975, 19, 3))
    assert (low, high) != pytest.approx(m.wilson_interval(18, 20))


def test_repeatability_six_a_four_b_and_identical():
    result = m.repeatability(["A"] * 6 + ["B"] * 4)
    assert result["modal_agreement"] == 0.6
    assert result["pairwise_agreement"] == pytest.approx(42 / 90)
    assert result["entropy_nats"] == pytest.approx(0.673011667, abs=1e-9)
    identical = m.repeatability(["wrong"] * 20)  # every quality grade may fail; repeatability is still 1
    assert identical["modal_agreement"] == identical["pairwise_agreement"] == 1
    assert identical["entropy_nats"] == 0


def test_repeated_success():
    assert m.at_least_one_success(0.8, 5) == pytest.approx(0.99968)
    assert m.all_k_succeed(0.8, 5) == pytest.approx(0.32768)
    assert m.pass_at_k(8, 10, 5) == 1
    assert m.pass_all_k(8, 10, 5) == pytest.approx(56 / 252)


def test_probability_scores():
    assert m.brier_score([0.9, 0.2], [1, 0]) == pytest.approx(0.025)
    assert m.exact_log_loss([0.9, 0.2], [1, 0]) == pytest.approx(-(math.log(0.9) + math.log(0.8)) / 2)
    assert m.binary_log_loss([0.9, 0.2], [1, 0]) == pytest.approx(-(math.log(0.9) + math.log(0.8)) / 2)
    assert m.exact_log_loss([1.0, 0.0], [0, 1]) == math.inf
    clipped = m.binary_log_loss([1.0, 0.0], [0, 1])
    assert math.isfinite(clipped) and clipped > 30


def test_calibration_bins_boundaries():
    result = m.calibration_bins([0.0, 1.0, 0.55], [0, 1, 1], bins=10)
    counts = [b["count"] for b in result["bins"]]
    assert counts[0] == 1 and counts[-1] == 1 and counts[5] == 1
    assert result["bins"][3]["prediction"] is None and result["bins"][3]["outcome"] is None
    for bad in (float("nan"), -0.1, 1.2):
        with pytest.raises(m.StatisticsError):
            m.calibration_bins([bad], [1])


def test_selective_prediction_edges():
    none_accepted = m.selective_risk([0.2, 0.3], [1, 0], 0.9)
    assert none_accepted["coverage"] == 0 and none_accepted["risk"] is None
    everything = m.selective_risk([0.0, 0.3], [1, 0], 0.0)
    assert everything["accepted"] == 2 and everything["coverage"] == 1


def test_retrieval_vector_and_duplicates():
    r = retrieval_metrics(["a", "c"], ["a", "b", "c"], k=2)
    assert r["precision_at_k"]["value"] == 0.5
    assert r["recall_at_k"]["value"] == 0.5
    assert r["reciprocal_rank"]["value"] == 1
    assert r["ndcg_at_k"]["value"] == pytest.approx(1 / (1 + 1 / math.log2(3)))
    dup = retrieval_metrics(["a"], ["a", "a", "b"], k=2)
    assert dup["precision_at_k"]["value"] == 0.5  # a counted once among unique [a, b]


def test_duplicated_fact_gets_one_true_positive():
    fact = {"subject": "maria", "relation": "lives_in", "object": "Lisbon"}
    result = match_exact([fact, dict(fact, object=" lisbon ")], [fact])
    assert (result["tp"], result["fp"], result["fn"]) == (1, 1, 0)
    assert result["precision"] == 0.5 and result["recall"] == 1
    assert result["f1"] == pytest.approx(2 / 3)


def test_paired_identical_scores_are_degenerate_and_clusters_count_once():
    units = [{"cluster": f"c{i}", "baseline": v, "candidate": v} for i, v in enumerate([0, 1, 0, 1])]
    result = paired_cluster_bootstrap(units, resamples=500)
    assert (result["lower"], result["delta"], result["upper"]) == (0, 0, 0)
    assert result["degenerate"] is True
    correlated = [{"cluster": "same-person", "baseline": 0, "candidate": 1} for _ in range(5)]
    correlated += [{"cluster": "other", "baseline": 1, "candidate": 1}]
    assert paired_cluster_bootstrap(correlated, resamples=500)["clusters"] == 2


def test_video_reconstructions():
    for value in m.accuracy_gaps(0.90, 0.89, 0.88, 0.87).values():
        assert value == pytest.approx(0.01)
    assert m.weighted_mean([0.95, 0.9, 0.85, 0.17], [1, 1, 1, 1]) == pytest.approx(0.7175)
