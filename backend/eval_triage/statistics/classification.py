"""Per-class precision/recall/F1 (micro and macro) and pairwise preference rates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from eval_triage.statistics.core import StatisticsError


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else None
    return {"tp": tp, "fp": fp, "fn": fn, "support": tp + fn, "precision": precision, "recall": recall, "f1": f1}


def class_metrics(pairs: Sequence[tuple[str, str]], labels: Sequence[str]) -> dict:
    """``pairs`` are (expected, predicted). Predictions outside ``labels`` count as false positives
    for no class and false negatives for the expected class; they are listed separately."""
    labels = list(dict.fromkeys(labels))
    if not labels:
        raise StatisticsError("labels must be non-empty")
    confusion: dict[str, Counter] = {label: Counter() for label in labels}
    out_of_vocabulary = 0
    for expected, predicted in pairs:
        if expected not in confusion:
            raise StatisticsError(f"expected label {expected!r} is not an allowed label")
        confusion[expected][predicted] += 1
        if predicted not in confusion:
            out_of_vocabulary += 1
    per_class = {}
    for label in labels:
        tp = confusion[label][label]
        fn = sum(confusion[label].values()) - tp
        fp = sum(confusion[other][label] for other in labels if other != label)
        per_class[label] = _prf(tp, fp, fn)
    total_tp = sum(c["tp"] for c in per_class.values())
    total_fp = sum(c["fp"] for c in per_class.values())
    total_fn = sum(c["fn"] for c in per_class.values())
    eligible = {label: m["f1"] for label, m in per_class.items() if m["support"] > 0 and m["f1"] is not None}
    omitted = sorted(set(labels) - set(eligible))
    n = len(pairs)
    return {
        "per_class": per_class,
        "micro": _prf(total_tp, total_fp, total_fn),
        "macro_f1": {"value": sum(eligible.values()) / len(eligible) if eligible else None,
                     "classes": sorted(eligible), "omitted_classes": omitted,
                     "reason": None if eligible else "no class has support"},
        "accuracy": total_tp / n if n else None,
        "n": n,
        "out_of_vocabulary_predictions": out_of_vocabulary,
        "confusion": {label: dict(confusion[label]) for label in labels},
    }


PREFERENCE_OUTCOMES = ("win", "loss", "tie", "abstain")


def pairwise_win_rate(outcomes: Sequence[str]) -> dict:
    """Candidate-perspective outcomes. win_rate = (wins + 0.5 ties) / (wins + losses + ties);
    abstentions are excluded and reported. This is preference, not factual correctness."""
    counts = Counter(outcomes)
    unknown = set(counts) - set(PREFERENCE_OUTCOMES)
    if unknown:
        raise StatisticsError(f"unknown preference outcomes {sorted(unknown)}")
    wins, losses, ties, abstain = (counts[o] for o in PREFERENCE_OUTCOMES)
    eligible = wins + losses + ties
    return {"wins": wins, "losses": losses, "ties": ties, "abstentions": abstain, "eligible": eligible,
            "win_rate": (wins + 0.5 * ties) / eligible if eligible else None,
            "reason": None if eligible else "no non-abstaining judgements"}


def position_consistency(pairs: Sequence[tuple[str, str]]) -> dict:
    """Each pair is (judgement with original order, judgement with reversed order), both expressed
    from the candidate's perspective. A consistent judge gives the same outcome both times."""
    inconsistent = [i for i, (a, b) in enumerate(pairs) if a != b]
    return {"pairs": len(pairs), "inconsistent": len(inconsistent), "inconsistent_indices": inconsistent}
