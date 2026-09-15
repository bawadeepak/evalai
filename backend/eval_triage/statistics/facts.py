"""One-to-one fact matching and fact precision/recall/F1.

Default matching (``exact_normalized_v1``) compares (subject, relation, object)
triples after Unicode NFKC normalisation, casefolding and whitespace collapse —
text normalisation, not semantic equivalence. Each reference fact can be
matched at most once, so duplicated predictions cannot earn repeated credit.

Optional model-assisted matching takes a similarity matrix, solves maximum-weight
one-to-one assignment and **discards assigned pairs below the threshold**; pairs
just above it are flagged for human review.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from eval_triage.statistics.core import StatisticsError

EXACT_VERSION = "exact_normalized_v1"
WEIGHTED_VERSION = "max_weight_bipartite_v1"


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def normalize_triple(fact) -> tuple[str, str, str]:
    if isinstance(fact, dict):
        parts = (fact.get("subject"), fact.get("relation"), fact.get("object"))
    else:
        parts = tuple(fact)
    if len(parts) != 3 or any(p is None for p in parts):
        raise StatisticsError(f"fact {fact!r} must have subject, relation and object")
    return tuple(normalize_text(p) for p in parts)  # type: ignore[return-value]


def fact_scores(tp: int, fp: int, fn: int) -> dict:
    predicted, references = tp + fp, tp + fn
    precision = tp / predicted if predicted else None
    recall = tp / references if references else None
    f1 = None if predicted == 0 and references == 0 else 2 * tp / (2 * tp + fp + fn)
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision,
        "precision_reason": None if predicted else "no predicted facts",
        "recall": recall,
        "recall_reason": None if references else "no reference facts",
        "f1": f1,
        "f1_reason": None if f1 is not None else "no reference and no predicted facts; the explicit "
                                                  "no-facts-required assertion decides quality",
    }


def match_exact(predicted: Sequence, reference: Sequence) -> dict:
    pred = [normalize_triple(f) for f in predicted]
    ref = [normalize_triple(f) for f in reference]
    used: set[int] = set()
    matches: list[tuple[int, int]] = []
    unmatched_pred: list[int] = []
    for pi, fact in enumerate(pred):
        hit = next((ri for ri, r in enumerate(ref) if ri not in used and r == fact), None)
        if hit is None:
            unmatched_pred.append(pi)
        else:
            used.add(hit)
            matches.append((pi, hit))
    unmatched_ref = [ri for ri in range(len(ref)) if ri not in used]
    return {"matches": matches, "unmatched_predicted": unmatched_pred, "unmatched_reference": unmatched_ref,
            "version": EXACT_VERSION,
            **fact_scores(len(matches), len(unmatched_pred), len(unmatched_ref))}


def match_weighted(similarity: Sequence[Sequence[float]], threshold: float, review_margin: float = 0.1) -> dict:
    """``similarity[p][r]`` in [0, 1] between predicted p and reference r."""
    matrix = np.asarray(similarity, dtype=float)
    if matrix.ndim != 2:
        raise StatisticsError("similarity must be a 2-D matrix")
    if matrix.size and (not np.all(np.isfinite(matrix)) or matrix.min() < 0 or matrix.max() > 1):
        raise StatisticsError("similarities must be finite values in [0, 1]")
    if not 0 < threshold <= 1:
        raise StatisticsError("threshold must be in (0, 1]")
    n_pred, n_ref = matrix.shape
    matches, review = [], []
    if matrix.size:
        rows, cols = linear_sum_assignment(matrix, maximize=True)
        for p, r in zip(rows.tolist(), cols.tolist(), strict=True):
            score = float(matrix[p, r])
            if score >= threshold:
                matches.append((p, r, score))
                if score < threshold + review_margin:
                    review.append((p, r, score))
    matched_p = {p for p, _, _ in matches}
    matched_r = {r for _, r, _ in matches}
    return {"matches": matches, "needs_review": review,
            "unmatched_predicted": [p for p in range(n_pred) if p not in matched_p],
            "unmatched_reference": [r for r in range(n_ref) if r not in matched_r],
            "threshold": threshold, "version": WEIGHTED_VERSION,
            **fact_scores(len(matches), n_pred - len(matches), n_ref - len(matches))}
