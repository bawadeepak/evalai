import pytest

from eval_triage.statistics.bootstrap import ReleasePolicyConfig, evaluate_gate, paired_cluster_bootstrap
from eval_triage.statistics.core import StatisticsError


def _units(deltas, clusters=None):
    clusters = clusters or [f"c{i}" for i in range(len(deltas))]
    return [{"cluster": c, "baseline": 0.5, "candidate": 0.5 + d} for c, d in zip(clusters, deltas, strict=True)]


def test_bootstrap_defaults_and_warnings():
    result = paired_cluster_bootstrap(_units([0.1, -0.1, 0.2]))
    assert result["resamples"] == 10_000 and result["seed"] == 42
    assert result["method"] == "paired_cluster_percentile_bootstrap"
    assert any("fewer than 20" in w for w in result["warnings"])
    single = paired_cluster_bootstrap(_units([0.3]))
    assert single["lower"] is None and single["reason"]
    with pytest.raises(StatisticsError):
        paired_cluster_bootstrap(_units([0.1, 0.2]), resamples=10)


def test_case_weighted_estimand_differs_from_equal_weight_clusters():
    units = [{"cluster": "big", "baseline": 0, "candidate": 1, "weight": 1} for _ in range(4)]
    units.append({"cluster": "small", "baseline": 1, "candidate": 0, "weight": 1})
    equal = paired_cluster_bootstrap(units, resamples=200)
    weighted = paired_cluster_bootstrap(units, resamples=200, estimand="case_weighted")
    assert equal["delta"] == pytest.approx(0.0)
    assert weighted["delta"] == pytest.approx(3 / 5)


POLICY = ReleasePolicyConfig.from_dict({
    "metrics": [{"name": "case_pass_rate", "direction": "higher_is_better", "margin": 0.05}],
    "critical_invariants": ["no_cross_user_leak"], "min_independent_clusters": 20,
})


def _result(lower, upper, clusters=24, delta=None):
    return {"case_pass_rate": {"lower": lower, "upper": upper, "clusters": clusters,
                               "delta": delta if delta is not None else (lower + upper) / 2}}


def test_gate_ready_blocked_inconclusive():
    assert evaluate_gate(POLICY, _result(-0.02, 0.1))["verdict"] == "ready"
    regression = evaluate_gate(POLICY, _result(-0.3, -0.1))
    assert regression["verdict"] == "blocked" and "demonstrated regression" in regression["reasons"][0]
    crossing = evaluate_gate(POLICY, _result(-0.2, 0.1))
    assert crossing["verdict"] == "inconclusive" and "crosses" in crossing["reasons"][0]
    few = evaluate_gate(POLICY, _result(0.0, 0.1, clusters=5))
    assert few["verdict"] == "inconclusive" and "independent clusters" in few["reasons"][0]


def test_critical_invariant_blocks_regardless_of_improvement():
    gate = evaluate_gate(POLICY, _result(0.2, 0.4), {"no_cross_user_leak": 1})
    assert gate["verdict"] == "blocked"


def test_partial_or_cancelled_experiments_never_ready():
    gate = evaluate_gate(POLICY, _result(0.1, 0.3), run_problems=["candidate run was cancelled"])
    assert gate["verdict"] == "inconclusive"
    coverage = evaluate_gate(POLICY, _result(0.1, 0.3), paired_coverage=0.9)
    assert coverage["verdict"] == "inconclusive"


def test_lower_is_better_sign_flip_and_multiplicity_note():
    policy = ReleasePolicyConfig.from_dict({"metrics": [
        {"name": "latency_p95", "direction": "lower_is_better", "margin": 50},
        {"name": "case_pass_rate", "direction": "higher_is_better", "margin": 0.05}]})
    results = {"latency_p95": {"lower": -20, "upper": 30, "clusters": 25},
               "case_pass_rate": {"lower": 0.0, "upper": 0.1, "clusters": 25}}
    gate = evaluate_gate(policy, results)
    assert gate["verdict"] == "ready"
    assert gate["multiplicity_note"]
    worse = evaluate_gate(policy, {**results, "latency_p95": {"lower": 60, "upper": 90, "clusters": 25}})
    assert worse["verdict"] == "blocked"


def test_policy_validation():
    with pytest.raises(StatisticsError):
        ReleasePolicyConfig.from_dict({"metrics": [{"name": "x", "direction": "sideways"}]})
    assert evaluate_gate(ReleasePolicyConfig(), {})["verdict"] == "inconclusive"
