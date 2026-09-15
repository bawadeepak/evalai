"""Property-based and exhaustive checks of the statistics module."""

import itertools

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eval_triage.statistics import core as m
from eval_triage.statistics.bootstrap import paired_cluster_bootstrap
from eval_triage.statistics.retrieval import retrieval_metrics

counts = st.integers(min_value=1, max_value=400).flatmap(
    lambda n: st.tuples(st.integers(min_value=0, max_value=n), st.just(n)))
probs = st.floats(min_value=0, max_value=1, allow_nan=False)


@given(counts, st.sampled_from([0.8, 0.9, 0.95, 0.99]))
def test_wilson_is_a_valid_interval_containing_the_point_estimate(cn, confidence):
    c, n = cn
    low, high = m.wilson_interval(c, n, confidence)
    assert 0 <= low <= c / n <= high <= 1
    other_low, other_high = m.wilson_interval(n - c, n, confidence)
    assert low == pytest.approx(1 - other_high) and high == pytest.approx(1 - other_low)


@given(counts)
def test_beta_interval_contains_posterior_mean(cn):
    c, n = cn
    low, high = m.beta_credible_interval(c, n)
    assert low <= m.beta_posterior_mean(c, n) <= high


def test_pass_estimators_against_all_subsets():
    for n in range(1, 9):
        for c in range(n + 1):
            pool = [True] * c + [False] * (n - c)
            for k in range(1, n + 1):
                subsets = list(itertools.combinations(pool, k))
                assert m.pass_at_k(c, n, k) == pytest.approx(sum(any(s) for s in subsets) / len(subsets))
                assert m.pass_all_k(c, n, k) == pytest.approx(sum(all(s) for s in subsets) / len(subsets))


@given(st.lists(st.sampled_from("ABCD"), min_size=2, max_size=60))
def test_repeatability_bounds(outcomes):
    r = m.repeatability(outcomes)
    assert 0 <= r["pairwise_agreement"] <= r["modal_agreement"] <= 1
    assert r["entropy_nats"] >= 0
    assert sum(r["category_counts"].values()) == len(outcomes)


@given(st.lists(st.tuples(probs, st.integers(0, 1)), min_size=1, max_size=80), st.integers(1, 20))
def test_probability_scores_ranges(pairs, bins):
    p, y = zip(*pairs, strict=True)
    assert 0 <= m.brier_score(p, y) <= 1
    result = m.calibration_bins(p, y, bins)
    assert sum(b["count"] for b in result["bins"]) == len(p)
    assert 0 <= result["ece"] <= 1


@given(st.lists(st.tuples(probs, st.integers(0, 1)), min_size=1, max_size=50), probs)
def test_selective_risk_ranges(pairs, threshold):
    p, y = zip(*pairs, strict=True)
    r = m.selective_risk(p, y, threshold)
    assert r["accepted"] + r["review"] == len(p)
    assert r["risk"] is None or 0 <= r["risk"] <= 1


@given(st.lists(st.sampled_from("abcdefg"), max_size=10), st.lists(st.sampled_from("abcdefg"), max_size=10),
       st.integers(1, 8))
def test_retrieval_metrics_are_fractions_or_unavailable_with_reason(relevant, retrieved, k):
    result = retrieval_metrics(sorted(set(relevant)), retrieved, k)
    for name, metric in result.items():
        if name == "_meta":
            continue
        if metric["value"] is None:
            assert metric["reason"]
        else:
            assert 0 <= metric["value"] <= 1 + 1e-12


@settings(max_examples=40, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 1), st.integers(0, 1)), min_size=3, max_size=30))
def test_bootstrap_interval_brackets_delta_and_is_reproducible(pairs):
    units = [{"cluster": f"c{i}", "baseline": b, "candidate": c} for i, (b, c) in enumerate(pairs)]
    first = paired_cluster_bootstrap(units, resamples=300, seed=7)
    second = paired_cluster_bootstrap(units, resamples=300, seed=7)
    assert first == second
    assert first["lower"] - 1e-12 <= first["delta"] <= first["upper"] + 1e-12
