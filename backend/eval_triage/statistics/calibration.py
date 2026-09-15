"""Probability calibration fitted on a declared calibration split only.

* ``logistic``: unpenalised maximum-likelihood Platt-style fit on an explicit
  scalar feature. With ``feature_transform='logit'`` probabilities are clipped
  with a recorded epsilon before the logit.
* ``isotonic``: monotone, bounded to [0, 1], out-of-range inputs clipped.

Fitted parameters are plain JSON (arrays of floats); models are never pickled,
and imported parameters are validated before use.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression

from eval_triage.statistics.core import StatisticsError, binary_log_loss, brier_score, calibration_bins

MIN_CLUSTERS = 30
FORBIDDEN_FIT_SPLITS = frozenset({"test"})


class CalibrationError(StatisticsError):
    pass


def check_fit_data(labels: Sequence[int], clusters: Sequence[str], splits: Sequence[str], *,
                   fit_split: str, min_clusters: int = MIN_CLUSTERS) -> dict:
    if fit_split in FORBIDDEN_FIT_SPLITS:
        raise CalibrationError("calibration cannot be fitted on the held-out test split")
    if len(set(splits)) != 1 or splits[0] != fit_split:
        raise CalibrationError(f"every fitting record must belong to the declared split {fit_split!r}")
    positives = sum(1 for y in labels if y == 1)
    negatives = sum(1 for y in labels if y == 0)
    if positives + negatives != len(labels):
        raise CalibrationError("labels must be 0 or 1")
    if positives == 0 or negatives == 0:
        raise CalibrationError("fitting requires both outcome classes in the calibration split")
    n_clusters = len(set(clusters))
    if n_clusters < min_clusters:
        raise CalibrationError(f"only {n_clusters} independent labelled clusters; the workflow floor is "
                               f"{min_clusters}")
    return {"records": len(labels), "clusters": n_clusters, "positives": positives, "negatives": negatives,
            "warnings": [f"small calibration set ({n_clusters} clusters): the fitted mapping may be unstable"]
            if n_clusters < 100 else []}


def _feature(values: Sequence[float], transform: str, epsilon: float) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(x)):
        raise CalibrationError("features must be finite")
    if transform == "identity":
        return x
    if transform == "logit":
        if np.any((x < 0) | (x > 1)):
            raise CalibrationError("logit transform needs probabilities in [0, 1]")
        clipped = np.clip(x, epsilon, 1 - epsilon)
        return np.log(clipped / (1 - clipped))
    raise CalibrationError(f"unknown feature transform {transform!r}")


def fit_logistic(features: Sequence[float], labels: Sequence[int], *, feature_transform: str = "identity",
                 epsilon: float = 1e-6) -> dict:
    x = _feature(features, feature_transform, epsilon)
    y = np.asarray(labels, dtype=float)
    negatives, positives = x[y == 0], x[y == 1]
    if negatives.size == 0 or positives.size == 0:
        raise CalibrationError("fitting requires both outcome classes")
    if negatives.max() <= positives.min() or positives.max() <= negatives.min():
        # Under (quasi-)complete separation the maximum-likelihood slope is infinite.
        raise CalibrationError("the classes are perfectly separated by the feature, so an unpenalised "
                               "logistic fit is undefined; use isotonic calibration or more data")

    def nll(theta):
        z = theta[0] * x + theta[1]
        return float(np.sum(np.logaddexp(0, z) - y * z))

    def grad(theta):
        p = 1 / (1 + np.exp(-(theta[0] * x + theta[1])))
        return np.array([np.sum((p - y) * x), np.sum(p - y)])

    fit = minimize(nll, x0=np.array([1.0, 0.0]), jac=grad, method="BFGS", options={"maxiter": 500})
    coef, intercept = (float(v) for v in fit.x)
    if not fit.success or not np.isfinite(fit.x).all() or abs(coef) > 1e3:
        raise CalibrationError("logistic fit did not converge (the classes may be perfectly separated); "
                               "use isotonic calibration or more data")
    return {"method": "logistic", "coef": coef, "intercept": intercept, "feature_transform": feature_transform,
            "epsilon": epsilon, "fit": "unpenalised maximum likelihood", "negative_log_likelihood": fit.fun}


def fit_isotonic(features: Sequence[float], labels: Sequence[int]) -> dict:
    x = np.asarray(features, dtype=float)
    if not np.all(np.isfinite(x)):
        raise CalibrationError("features must be finite")
    model = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
    model.fit(x, np.asarray(labels, dtype=float))
    return {"method": "isotonic", "x_thresholds": [float(v) for v in model.X_thresholds_],
            "y_thresholds": [float(v) for v in model.y_thresholds_], "out_of_bounds": "clip",
            "interpolation": "linear"}


def validate_parameters(params: dict[str, Any]) -> dict[str, Any]:
    method = params.get("method")
    if method == "logistic":
        for key in ("coef", "intercept", "epsilon"):
            if not isinstance(params.get(key), (int, float)) or not np.isfinite(params[key]):
                raise CalibrationError(f"logistic parameter {key!r} must be a finite number")
        if params.get("feature_transform") not in ("identity", "logit"):
            raise CalibrationError("unknown feature_transform")
    elif method == "isotonic":
        xs, ys = params.get("x_thresholds"), params.get("y_thresholds")
        if not isinstance(xs, list) or not isinstance(ys, list) or len(xs) != len(ys) or not xs:
            raise CalibrationError("isotonic thresholds must be equal-length non-empty lists")
        if any(not isinstance(v, (int, float)) for v in xs + ys):
            raise CalibrationError("isotonic thresholds must be numbers")
        if any(b < a for a, b in zip(xs, xs[1:], strict=False)) or any(b < a for a, b in zip(ys, ys[1:], strict=False)):
            raise CalibrationError("isotonic thresholds must be non-decreasing")
        if min(ys) < 0 or max(ys) > 1:
            raise CalibrationError("isotonic outputs must lie in [0, 1]")
    else:
        raise CalibrationError(f"unknown calibration method {method!r}")
    return params


def apply_calibration(params: dict[str, Any], features: Sequence[float]) -> list[float]:
    validate_parameters(params)
    if params["method"] == "logistic":
        x = _feature(features, params["feature_transform"], params["epsilon"])
        z = params["coef"] * x + params["intercept"]
        return [float(v) for v in 1 / (1 + np.exp(-z))]
    x = np.asarray(features, dtype=float)
    return [float(v) for v in np.interp(x, params["x_thresholds"], params["y_thresholds"])]


def probability_quality(probabilities: Sequence[float], labels: Sequence[int], bins: int = 10) -> dict:
    return {"n": len(labels), "brier": brier_score(probabilities, labels),
            "log_loss_clipped": binary_log_loss(probabilities, labels, 1e-15),
            "calibration": calibration_bins(probabilities, labels, bins)}
