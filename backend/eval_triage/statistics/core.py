"""Core statistics: intervals, Bayesian estimates, repeatability, repeated success,
probability quality and small helpers.

Ported from the reference ``docs/metrics.py`` (formula catalogue in
``docs/FORMULAS.md``) and extended. Inputs are validated; invalid input raises
:class:`StatisticsError` instead of producing a silent score. Functions return
``None`` where the catalogue declares a value undefined, and callers attach the
reason when wrapping values as ``MetricValue``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable, Mapping, Sequence
from math import comb, exp, expm1, inf, isfinite, log, log1p, sqrt
from statistics import NormalDist, fmean

from scipy import stats as _stats


class StatisticsError(ValueError):
    pass


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise StatisticsError(f"{name} must be a finite number")
    return float(value)


def _prob(value, name: str = "probability") -> float:
    value = _number(value, name)
    if not 0 <= value <= 1:
        raise StatisticsError(f"{name} must be in [0, 1]")
    return value


def _open_prob(value, name: str) -> float:
    value = _prob(value, name)
    if not 0 < value < 1:
        raise StatisticsError(f"{name} must be strictly between 0 and 1")
    return value


def _integer(value, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise StatisticsError(f"{name} must be an integer >= {minimum}")
    return value


def _counts(successes, trials) -> None:
    _integer(trials, "trials", 1)
    _integer(successes, "successes")
    if successes > trials:
        raise StatisticsError("successes cannot exceed trials")


def _pairs(probabilities, labels) -> tuple[list[float], list[int]]:
    p, y = list(probabilities), list(labels)
    if not p or len(p) != len(y):
        raise StatisticsError("probabilities and labels must have equal nonzero length")
    p = [_prob(value) for value in p]
    if any(type(value) not in (int, bool) or value not in (0, 1) for value in y):
        raise StatisticsError("labels must be binary integers or booleans")
    return p, [int(v) for v in y]


# --- video reconstructions [V + R] -------------------------------------------------------


def accuracy_gaps(train, evaluation, initial_production, later_production) -> dict[str, float]:
    a, b, c, d = (_prob(x, "accuracy") for x in (train, evaluation, initial_production, later_production))
    return {"generalization_gap": a - b, "domain_gap": b - c, "temporal_gap": c - d}


def weighted_mean(values: Sequence, weights: Sequence) -> float:
    values, weights = list(values), list(weights)
    if not values or len(values) != len(weights):
        raise StatisticsError("values and weights must have equal nonzero length")
    values = [_number(x, "value") for x in values]
    weights = [_number(x, "weight") for x in weights]
    if any(w < 0 for w in weights) or sum(weights) <= 0:
        raise StatisticsError("weights must be nonnegative with positive total")
    return sum(v * w for v, w in zip(values, weights, strict=True)) / sum(weights)


# --- observed success, intervals, Bayesian estimate [S] ---------------------------------


def wilson_interval(successes: int, trials: int, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided Wilson score interval for independent Bernoulli trials."""
    _counts(successes, trials)
    confidence = _open_prob(confidence, "confidence")
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    half = z * sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    # The analytic endpoints at c = 0 and c = n are exactly 0 and 1; avoid rounding residue.
    low = 0.0 if successes == 0 else max(0.0, center - half)
    high = 1.0 if successes == trials else min(1.0, center + half)
    return low, high


def zero_failure_upper_bound(trials: int, confidence: float = 0.95) -> float:
    """Exact one-sided upper bound on failure probability after zero failures in ``trials``."""
    _integer(trials, "trials", 1)
    confidence = _open_prob(confidence, "confidence")
    return -expm1(log1p(-confidence) / trials)


def beta_posterior(successes: int, trials: int, a: float = 1.0, b: float = 1.0) -> tuple[float, float]:
    _counts(successes, trials)
    a, b = _number(a, "a"), _number(b, "b")
    if a <= 0 or b <= 0:
        raise StatisticsError("prior parameters must be positive")
    return a + successes, b + trials - successes


def beta_posterior_mean(successes: int, trials: int, a: float = 1.0, b: float = 1.0) -> float:
    alpha, beta = beta_posterior(successes, trials, a, b)
    return alpha / (alpha + beta)


def beta_credible_interval(successes: int, trials: int, a: float = 1.0, b: float = 1.0,
                           level: float = 0.95) -> tuple[float, float]:
    """Equal-tailed Bayesian credible interval (SciPy beta quantiles). Not a Wilson interval."""
    alpha, beta = beta_posterior(successes, trials, a, b)
    level = _open_prob(level, "level")
    return (float(_stats.beta.ppf((1 - level) / 2, alpha, beta)),
            float(_stats.beta.ppf((1 + level) / 2, alpha, beta)))


# --- repeatability [D] ---------------------------------------------------------------------


def repeatability(outcomes: Iterable[Hashable]) -> dict:
    """Outcomes must already be canonicalised into hashable categories by the caller."""
    counts = Counter(outcomes)
    n = sum(counts.values())
    if n == 0:
        raise StatisticsError("at least one outcome is required")
    return {
        "trials": n,
        "distinct_outcomes": len(counts),
        "category_counts": dict(counts.most_common()),
        "modal_agreement": max(counts.values()) / n,
        "pairwise_agreement": sum(c * (c - 1) for c in counts.values()) / (n * (n - 1)) if n > 1 else None,
        "entropy_nats": -sum((c / n) * log(c / n) for c in counts.values()) if n > 1 else None,
    }


# --- repeated success [S] -----------------------------------------------------------------


def at_least_one_success(p: float, k: int) -> float:
    p = _prob(p)
    _integer(k, "k", 1)
    return 1 - (1 - p) ** k


def all_k_succeed(p: float, k: int) -> float:
    p = _prob(p)
    _integer(k, "k", 1)
    return p ** k


def pass_at_k(successes: int, trials: int, k: int) -> float:
    """Unbiased per-task estimator of at least one success in k IID attempts."""
    _counts(successes, trials)
    _integer(k, "k", 1)
    if k > trials:
        raise StatisticsError("k cannot exceed trials")
    return 1 - comb(trials - successes, k) / comb(trials, k) if trials - successes >= k else 1.0


def pass_all_k(successes: int, trials: int, k: int) -> float:
    """Unbiased per-task estimator of all k attempts succeeding (pass^k)."""
    _counts(successes, trials)
    _integer(k, "k", 1)
    if k > trials:
        raise StatisticsError("k cannot exceed trials")
    return comb(successes, k) / comb(trials, k) if successes >= k else 0.0


# --- probability quality [S] ---------------------------------------------------------------


def brier_score(probabilities: Sequence, labels: Sequence) -> float:
    p, y = _pairs(probabilities, labels)
    return fmean((pi - yi) ** 2 for pi, yi in zip(p, y, strict=True))


def binary_log_loss(probabilities: Sequence, labels: Sequence, epsilon: float = 1e-15) -> float:
    """Finite log loss with predictions clipped to [epsilon, 1 - epsilon] (declared numeric policy)."""
    p, y = _pairs(probabilities, labels)
    epsilon = _number(epsilon, "epsilon")
    if not 0 < epsilon < 0.5:
        raise StatisticsError("epsilon must be strictly between 0 and 0.5")
    p = [min(1 - epsilon, max(epsilon, pi)) for pi in p]
    return -fmean(yi * log(pi) + (1 - yi) * log1p(-pi) for pi, yi in zip(p, y, strict=True))


def exact_log_loss(probabilities: Sequence, labels: Sequence) -> float:
    """Mathematical log loss; a confidently wrong endpoint prediction gives ``inf``."""
    p, y = _pairs(probabilities, labels)
    total = 0.0
    for pi, yi in zip(p, y, strict=True):
        q = pi if yi == 1 else 1 - pi
        if q == 0:
            return inf
        total += -log(q)
    return total / len(p)


def calibration_bins(probabilities: Sequence, labels: Sequence, bins: int = 10) -> dict:
    """Equal-width binary event-probability bins; p = 1 falls in the final bin. ECE is bin-dependent."""
    p, y = _pairs(probabilities, labels)
    _integer(bins, "bins", 1)
    buckets: list[list[tuple[float, int, int]]] = [[] for _ in range(bins)]
    for index, (pi, yi) in enumerate(zip(p, y, strict=True)):
        buckets[min(bins - 1, int(pi * bins))].append((pi, yi, index))
    rows, ece = [], 0.0
    for i, bucket in enumerate(buckets):
        prediction = fmean(a for a, _, _ in bucket) if bucket else None
        outcome = fmean(b for _, b, _ in bucket) if bucket else None
        if bucket:
            ece += len(bucket) / len(p) * abs(prediction - outcome)
        rows.append({"index": i, "lower": i / bins, "upper": (i + 1) / bins, "count": len(bucket),
                     "positives": sum(b for _, b, _ in bucket), "prediction": prediction, "outcome": outcome,
                     "members": [m for _, _, m in bucket]})
    return {"bins": rows, "ece": ece, "n": len(p), "method": f"equal_width_{bins}"}


def selective_risk(probabilities: Sequence, correctness: Sequence, threshold: float) -> dict:
    """Accept predictions with p >= threshold. Probabilities must predict answer correctness."""
    p, y = _pairs(probabilities, correctness)
    threshold = _prob(threshold, "threshold")
    accepted = [yi for pi, yi in zip(p, y, strict=True) if pi >= threshold]
    return {"threshold": threshold, "accepted": len(accepted), "review": len(p) - len(accepted), "total": len(p),
            "coverage": len(accepted) / len(p),
            "risk": 1 - fmean(accepted) if accepted else None,
            "risk_unavailable_reason": None if accepted else "no accepted predictions"}


def risk_coverage_curve(probabilities: Sequence, correctness: Sequence,
                        thresholds: Sequence[float] | None = None) -> list[dict]:
    p, y = _pairs(probabilities, correctness)
    if thresholds is None:
        thresholds = sorted({0.0, *p, 1.0})
    return [selective_risk(p, y, t) for t in thresholds]


# --- small helpers --------------------------------------------------------------------------


def linear_quantile(values: Sequence[float], q: float) -> float | None:
    """Linear interpolation between order statistics (Hyndman–Fan type 7). ``None`` for no values."""
    q = _prob(q, "quantile")
    data = sorted(_number(v, "value") for v in values)
    if not data:
        return None
    position = q * (len(data) - 1)
    lower = int(position)
    upper = min(lower + 1, len(data) - 1)
    return data[lower] + (position - lower) * (data[upper] - data[lower])


def token_logprob_summary(logprobs: Sequence[float]) -> dict | None:
    """Sequence log probability and mean token log probability. Not answer-correctness probability."""
    values = [_number(v, "log probability") for v in logprobs]
    if not values:
        return None
    if any(v > 0 for v in values):
        raise StatisticsError("log probabilities must be <= 0")
    total = sum(values)
    return {"sequence_log_probability": total, "mean_token_log_probability": total / len(values),
            "token_count": len(values), "sequence_probability": exp(total)}


def geval_expected_score(distribution: Mapping[float, float], tolerance: float = 1e-6) -> float:
    """Expected rubric score Σ s·P(s). Requires a complete, valid score distribution."""
    if not distribution:
        raise StatisticsError("score distribution is empty")
    probs = {float(_number(s, "score")): _prob(pr) for s, pr in distribution.items()}
    total = sum(probs.values())
    if abs(total - 1) > tolerance:
        raise StatisticsError(f"score probabilities sum to {total:.6f}, not 1; the distribution is incomplete "
                              "(a truncated top-token list must not be renormalised silently)")
    return sum(s * pr for s, pr in probs.items())
