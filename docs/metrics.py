"""Eval Triage reference mathematics. Standard library only; no provider calls.

Definitions and assumptions are in FORMULAS.md. These functions do not infer
ground truth, calibrate a model, or turn arbitrary scores into probabilities.
"""

from collections import Counter
from math import comb, expm1, isfinite, log, log1p, sqrt
from random import Random
from statistics import NormalDist, fmean


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _prob(value, name="probability"):
    value = _number(value, name)
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0, 1]")
    return value


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _counts(successes, trials):
    _integer(trials, "trials", 1)
    _integer(successes, "successes")
    if successes > trials:
        raise ValueError("successes cannot exceed trials")


def _pairs(probabilities, labels):
    p, y = list(probabilities), list(labels)
    if not p or len(p) != len(y):
        raise ValueError("probabilities and labels must have equal nonzero length")
    p = [_prob(value) for value in p]
    if any(type(value) not in (int, bool) or value not in (0, 1) for value in y):
        raise ValueError("labels must be binary integers or booleans")
    return p, y


def accuracy_gaps(train, evaluation, initial_production, later_production):
    a, b, c, d = [_prob(x, "accuracy") for x in
                  (train, evaluation, initial_production, later_production)]
    return {"generalization_gap": a - b, "domain_gap": b - c, "temporal_gap": c - d}


def weighted_mean(values, weights):
    values, weights = list(values), list(weights)
    if not values or len(values) != len(weights):
        raise ValueError("values and weights must have equal nonzero length")
    values = [_number(x, "value") for x in values]
    weights = [_number(x, "weight") for x in weights]
    if any(w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError("weights must be nonnegative with positive total")
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


def wilson_interval(successes, trials, confidence=0.95):
    """Two-sided Wilson interval for independent Bernoulli trials."""
    _counts(successes, trials)
    confidence = _prob(confidence, "confidence")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be strictly between 0 and 1")
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    half = z * sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def zero_failure_upper_bound(trials, confidence=0.95):
    """Exact one-sided bound, only for a design with zero observed failures."""
    _integer(trials, "trials", 1)
    confidence = _prob(confidence, "confidence")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be strictly between 0 and 1")
    return -expm1(log1p(-confidence) / trials)


def beta_posterior_mean(successes, trials, a=1.0, b=1.0):
    """Mean for a declared Beta prior and a single Bernoulli probability."""
    _counts(successes, trials)
    a, b = _number(a, "a"), _number(b, "b")
    if a <= 0 or b <= 0:
        raise ValueError("prior parameters must be positive")
    return (a + successes) / (a + b + trials)


def repeatability(outcomes):
    """Outcomes must be caller-canonicalized, hashable categories."""
    counts = Counter(outcomes)
    n = sum(counts.values())
    if n == 0:
        raise ValueError("at least one outcome is required")
    return {
        "trials": n,
        "distinct_outcomes": len(counts),
        "modal_agreement": max(counts.values()) / n,
        "pairwise_agreement": sum(c * (c - 1) for c in counts.values()) / (n * (n - 1)) if n > 1 else None,
        "entropy_nats": -sum((c / n) * log(c / n) for c in counts.values()) if n > 1 else None,
    }


def pass_at_k(successes, trials, k):
    """Per-task estimator for at least one success in k IID attempts."""
    _counts(successes, trials)
    _integer(k, "k", 1)
    if k > trials:
        raise ValueError("k cannot exceed trials")
    return 1 - comb(trials - successes, k) / comb(trials, k) if trials - successes >= k else 1.0


def pass_all_k(successes, trials, k):
    """Per-task estimator for all k attempts succeeding (pass^k)."""
    _counts(successes, trials)
    _integer(k, "k", 1)
    if k > trials:
        raise ValueError("k cannot exceed trials")
    return comb(successes, k) / comb(trials, k) if successes >= k else 0.0


def brier_score(probabilities, labels):
    p, y = _pairs(probabilities, labels)
    return fmean((pi - yi) ** 2 for pi, yi in zip(p, y))


def binary_log_loss(probabilities, labels, epsilon=1e-15):
    p, y = _pairs(probabilities, labels)
    epsilon = _number(epsilon, "epsilon")
    if not 0 < epsilon < 0.5:
        raise ValueError("epsilon must be strictly between 0 and 0.5")
    p = [min(1 - epsilon, max(epsilon, pi)) for pi in p]
    return -fmean(yi * log(pi) + (1 - yi) * log1p(-pi) for pi, yi in zip(p, y))


def calibration_bins(probabilities, labels, bins=10):
    """Equal-width binary event-probability bins; ECE is bin-dependent."""
    p, y = _pairs(probabilities, labels)
    _integer(bins, "bins", 1)
    buckets = [[] for _ in range(bins)]
    for pi, yi in zip(p, y):
        buckets[min(bins - 1, int(pi * bins))].append((pi, yi))
    rows, ece = [], 0.0
    for i, bucket in enumerate(buckets):
        prediction = fmean(a for a, _ in bucket) if bucket else None
        outcome = fmean(b for _, b in bucket) if bucket else None
        if bucket:
            ece += len(bucket) / len(p) * abs(prediction - outcome)
        rows.append({"lower": i / bins, "upper": (i + 1) / bins,
                     "count": len(bucket), "prediction": prediction, "outcome": outcome})
    return {"bins": rows, "ece": ece, "n": len(p)}


def selective_risk(probabilities, correctness, threshold):
    """Probabilities must predict answer correctness, not a class label."""
    p, y = _pairs(probabilities, correctness)
    threshold = _prob(threshold, "threshold")
    accepted = [yi for pi, yi in zip(p, y) if pi >= threshold]
    return {"accepted": len(accepted), "total": len(p),
            "coverage": len(accepted) / len(p),
            "risk": 1 - fmean(accepted) if accepted else None}


def _quantile(sorted_values, q):
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (position - lower) * (sorted_values[upper] - sorted_values[lower])


def paired_delta_interval(baseline, candidate, confidence=0.95, resamples=5000, seed=42):
    """Percentile bootstrap on paired independent-case summaries, not repeats.

    Illustrative implementation. Caller must establish correct clustering and
    account for selection/multiplicity. Degenerate samples can yield zero width.
    """
    baseline, candidate = list(baseline), list(candidate)
    if len(baseline) < 2 or len(baseline) != len(candidate):
        raise ValueError("at least two equally sized paired case summaries are required")
    confidence = _prob(confidence, "confidence")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be strictly between 0 and 1")
    _integer(resamples, "resamples", 100)
    differences = [_number(b, "candidate") - _number(a, "baseline")
                   for a, b in zip(baseline, candidate)]
    rng, n = Random(seed), len(differences)
    draws = sorted(fmean(differences[rng.randrange(n)] for _ in range(n)) for _ in range(resamples))
    alpha = (1 - confidence) / 2
    return {"delta": fmean(differences), "lower": _quantile(draws, alpha),
            "upper": _quantile(draws, 1 - alpha), "cases": n,
            "method": "paired_case_percentile_bootstrap", "resamples": resamples,
            "seed": seed, "degenerate": draws[0] == draws[-1]}


if __name__ == "__main__":
    import json
    print(json.dumps({
        "video_gaps": accuracy_gaps(.9, .89, .88, .87),
        "wilson_18_of_20": wilson_interval(18, 20),
        "zero_failures_100_upper": zero_failure_upper_bound(100),
        "repeatability_example": repeatability(["A"] * 6 + ["B"] * 4),
        "pass_at_5_from_8_of_10": pass_at_k(8, 10, 5),
        "pass_all_5_from_8_of_10": pass_all_k(8, 10, 5),
    }, indent=2))
