import json
import random

import pytest

from eval_triage.domain.fixtures import FIXTURES_DIR
from eval_triage.statistics import calibration as cal
from eval_triage.statistics.core import brier_score


def _synthetic(n=3000, seed=3):
    rng = random.Random(seed)
    xs, ys = [], []
    for _ in range(n):
        x = rng.uniform(0.02, 0.98)
        xs.append(x)
        ys.append(1 if rng.random() < x ** 2 else 0)  # overconfident raw scores
    return xs, ys


def test_fit_guards():
    labels = [0, 1] * 20
    clusters = [f"c{i}" for i in range(40)]
    with pytest.raises(cal.CalibrationError, match="held-out test"):
        cal.check_fit_data(labels, clusters, ["test"] * 40, fit_split="test")
    with pytest.raises(cal.CalibrationError, match="both outcome classes"):
        cal.check_fit_data([1] * 40, clusters, ["calibration"] * 40, fit_split="calibration")
    with pytest.raises(cal.CalibrationError, match="workflow floor"):
        cal.check_fit_data(labels, ["one"] * 40, ["calibration"] * 40, fit_split="calibration")
    with pytest.raises(cal.CalibrationError, match="declared split"):
        cal.check_fit_data(labels, clusters, ["calibration"] * 39 + ["test"], fit_split="calibration")
    info = cal.check_fit_data(labels, clusters, ["calibration"] * 40, fit_split="calibration")
    assert info["clusters"] == 40 and info["warnings"]


@pytest.mark.parametrize("method", ["logistic", "isotonic"])
def test_calibration_improves_overconfident_scores_and_round_trips_as_json(method):
    xs, ys = _synthetic()
    fit_x, fit_y, test_x, test_y = xs[:1500], ys[:1500], xs[1500:], ys[1500:]
    params = cal.fit_logistic(fit_x, fit_y, feature_transform="logit") if method == "logistic" \
        else cal.fit_isotonic(fit_x, fit_y)
    restored = json.loads(json.dumps(params))
    calibrated = cal.apply_calibration(restored, test_x)
    assert calibrated == cal.apply_calibration(params, test_x)
    assert all(0 <= p <= 1 for p in calibrated)
    assert brier_score(calibrated, test_y) < brier_score(test_x, test_y)


def test_isotonic_is_monotone_and_clips_out_of_range():
    params = cal.fit_isotonic([0.1, 0.4, 0.6, 0.9], [0, 0, 1, 1])
    out = cal.apply_calibration(params, [-5, 0.1, 0.5, 0.9, 5])
    assert out == sorted(out) and out[0] == out[1] and out[-1] == out[-2]


def test_separable_logistic_refused():
    with pytest.raises(cal.CalibrationError, match="separated"):
        cal.fit_logistic([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1])


def test_imported_parameters_validated():
    for bad in ({"method": "pickle"}, {"method": "isotonic", "x_thresholds": [0, 1], "y_thresholds": [0.9, 0.1]},
                {"method": "logistic", "coef": float("nan"), "intercept": 0, "epsilon": 1e-6,
                 "feature_transform": "identity"}):
        with pytest.raises(cal.CalibrationError):
            cal.validate_parameters(bad)


def test_demo_records_fit_on_calibration_split_only():
    records = json.loads((FIXTURES_DIR / "demo" / "probability_records.json").read_text())["records"]
    fit = [r for r in records if r["split"] == "calibration"]
    info = cal.check_fit_data([r["label"] for r in fit], [r["cluster_id"] for r in fit],
                              [r["split"] for r in fit], fit_split="calibration", min_clusters=20)
    assert info["positives"] and info["negatives"]
    params = cal.fit_isotonic([r["raw_feature"] for r in fit], [r["label"] for r in fit])
    test = [r for r in records if r["split"] == "test"]
    quality = cal.probability_quality(cal.apply_calibration(params, [r["raw_feature"] for r in test]),
                                      [r["label"] for r in test])
    assert quality["n"] == len(test)
