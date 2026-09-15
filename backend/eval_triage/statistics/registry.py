"""Versioned metric registry: what each number means, its units, direction and provenance.

Provenance tags follow the formula catalogue: **V** visually observed in the
source video, **R** reconstructed from it, **S** standard statistical method,
**D** application definition.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from eval_triage.domain.enums import Direction, ScoreType
from eval_triage.domain.metrics import MetricValue, Uncertainty

H, L, N = Direction.HIGHER_IS_BETTER, Direction.LOWER_IS_BETTER, Direction.NEUTRAL


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    version: str
    title: str
    score_type: ScoreType
    unit: str
    direction: Direction
    provenance: str
    formula: str
    description: str
    aggregation: str = "per case, then across independent clusters"

    def to_dict(self) -> dict[str, Any]:
        return {k: (v.value if hasattr(v, "value") else v) for k, v in asdict(self).items()}


def _d(name, title, score_type, unit, direction, provenance, formula, description, version="1",
       aggregation="per case, then across independent clusters") -> MetricDefinition:
    return MetricDefinition(name, f"{name}@{version}", title, score_type, unit, direction, provenance, formula,
                            description, aggregation)


_DEFINITIONS = [
    _d("observed_pass_rate", "Observed pass rate", ScoreType.OBSERVED_RATE, "fraction of graded repeats", H, "D",
       "P / (P + F)", "Share of binary-graded slots that passed the dataset pass rule. Not a probability of "
       "success for a new case."),
    _d("wilson_interval", "Wilson 95% interval", ScoreType.OBSERVED_RATE, "fraction", N, "S",
       "center ± z·sqrt(p(1−p)/n + z²/4n²) / (1 + z²/n)", "Frequentist interval with repeated-sampling "
       "coverage; valid only for plausibly independent repeats of one case."),
    _d("beta_posterior", "Beta posterior (credible interval)", ScoreType.POSTERIOR_SUCCESS_PROBABILITY,
       "probability", H, "S", "Beta(a + c, b + n − c)", "Bayesian estimate of one case's success probability "
       "under a declared prior (default Beta(1,1)). Not a calibrated correctness prediction."),
    _d("zero_failure_upper_bound", "Zero-failure upper bound", ScoreType.OBSERVED_RATE, "failure probability",
       L, "S", "1 − α^(1/n)", "Exact one-sided bound after observing no failures in n independent trials."),
    _d("modal_agreement", "Modal agreement", ScoreType.AGREEMENT, "fraction of repeats", N, "D",
       "max_j n_j / n", "Share of repeats in the most common output category. Measures variation, not "
       "correctness."),
    _d("pairwise_agreement", "Pairwise agreement", ScoreType.AGREEMENT, "probability two repeats match", N, "D",
       "Σ n_j(n_j−1) / n(n−1)", "Chance two outputs drawn without replacement are in the same category."),
    _d("output_entropy", "Output entropy", ScoreType.ENTROPY, "nats", N, "D", "−Σ (n_j/n) ln(n_j/n)",
       "Spread of outputs across categories."),
    _d("pass_at_k", "pass@k", ScoreType.OBSERVED_RATE, "probability", H, "S", "1 − C(n−c,k)/C(n,k)",
       "Estimated chance at least one of k attempts succeeds; averaged per task, never pass-rate^k."),
    _d("pass_all_k", "pass^k", ScoreType.OBSERVED_RATE, "probability", H, "S", "C(c,k)/C(n,k)",
       "Estimated chance all k attempts succeed (agent reliability)."),
    _d("brier", "Brier score", ScoreType.DISTANCE, "squared error", L, "S", "mean (p − y)²",
       "Probability quality for a named binary event; mixes calibration and discrimination.",
       aggregation="over predictions"),
    _d("log_loss_clipped", "Log loss (clipped)", ScoreType.DISTANCE, "nats", L, "S",
       "−mean[y ln p + (1−y) ln(1−p)], p clipped to [1e−15, 1−1e−15]",
       "Finite log loss under a declared clipping policy; exact loss is infinite for confident errors.",
       aggregation="over predictions"),
    _d("ece", "Expected calibration error", ScoreType.DISTANCE, "probability", L, "S",
       "Σ |B_m|/N · |outcome_m − prediction_m| (10 equal-width bins)",
       "Binary event calibration error; bin- and sample-size dependent.", aggregation="over predictions"),
    _d("selective_risk", "Selective risk", ScoreType.OBSERVED_RATE, "error fraction of accepted", L, "D",
       "count(y=0, p≥t) / count(p≥t)", "Error rate among automatically accepted answers at threshold t.",
       aggregation="over predictions"),
    _d("coverage", "Coverage", ScoreType.OBSERVED_RATE, "fraction accepted", H, "D", "count(p≥t) / N",
       "Share of predictions accepted without review at threshold t.", aggregation="over predictions"),
    _d("precision_at_k", "Precision@k", ScoreType.OBSERVED_RATE, "fraction of retrieved", H, "S",
       "|R ∩ T_k| / |T_k| (unique retrieved)", "Retrieved-count precision after de-duplication."),
    _d("precision_fixed_slots_at_k", "Precision@k (fixed slots)", ScoreType.OBSERVED_RATE, "fraction of k", H,
       "S", "|R ∩ T_k| / k", "Separately named fixed-slot variant."),
    _d("recall_at_k", "Recall@k", ScoreType.OBSERVED_RATE, "fraction of relevant", H, "S", "|R ∩ T_k| / |R|",
       "Unavailable when no relevant documents are declared."),
    _d("reciprocal_rank", "Reciprocal rank", ScoreType.OBSERVED_RATE, "1/rank", H, "S",
       "1 / rank of first relevant (0 if none)", "Mean over queries gives MRR."),
    _d("ndcg_at_k", "nDCG@k", ScoreType.OBSERVED_RATE, "fraction of ideal", H, "S", "DCG@k / IDCG@k",
       "Graded gains 2^rel − 1; unavailable when IDCG is 0."),
    _d("fact_precision", "Fact precision", ScoreType.OBSERVED_RATE, "fraction of predicted facts", H, "S",
       "TP / (TP + FP)", "One-to-one matched; unavailable with no predicted facts."),
    _d("fact_recall", "Fact recall", ScoreType.OBSERVED_RATE, "fraction of reference facts", H, "S",
       "TP / (TP + FN)", "Zero when references exist and nothing matched."),
    _d("fact_f1", "Fact F1", ScoreType.OBSERVED_RATE, "F1", H, "S", "2TP / (2TP + FP + FN)",
       "Unavailable when there are neither references nor predictions."),
    _d("supported_claim_fraction", "Supported claim fraction", ScoreType.OBSERVED_RATE, "fraction of claims", H,
       "S", "supported claims / evaluated claims", "Unavailable with no evaluated claims; completeness is "
       "graded separately."),
    _d("accuracy", "Accuracy", ScoreType.OBSERVED_RATE, "fraction", H, "S", "correct / n", "Classification."),
    _d("macro_f1", "Macro F1", ScoreType.OBSERVED_RATE, "F1", H, "S", "mean of eligible class F1",
       "Omitted classes are listed."),
    _d("micro_f1", "Micro F1", ScoreType.OBSERVED_RATE, "F1", H, "S", "F1 over pooled TP/FP/FN",
       "Pooled counts before computing."),
    _d("win_rate", "Win rate (preference)", ScoreType.OBSERVED_RATE, "fraction of eligible judgements", H, "D",
       "(wins + 0.5 ties) / (wins + losses + ties)", "Preference, not factual correctness; abstentions "
       "excluded and reported."),
    _d("target_completion", "Target completion", ScoreType.OBSERVED_RATE, "fraction of scheduled", H, "D",
       "G / S", "Slots with a successful output."),
    _d("grade_coverage", "Grade coverage", ScoreType.OBSERVED_RATE, "fraction of eligible", H, "D",
       "E / eligible", "Eligible slots that received a binary grade."),
    _d("conditional_pass", "Conditional pass", ScoreType.OBSERVED_RATE, "fraction of graded", H, "D",
       "P / (P + F)", "Pass rate among binary-graded slots."),
    _d("observed_success_yield", "Observed success yield", ScoreType.OBSERVED_RATE, "fraction of scheduled", H,
       "D", "P / S", "Unresolved slots are not claimed to be wrong."),
    _d("case_pass_rate", "Case pass rate", ScoreType.OBSERVED_RATE, "mean per-case pass fraction", H, "D",
       "mean over cases of P_i / (P_i + F_i)", "Repeats summarised per case first; used for paired comparison."),
    _d("latency_p50", "Latency p50", ScoreType.DURATION, "ms", L, "D", "linear (type 7) quantile",
       "Over completed calls; timeouts counted separately.", aggregation="over completed calls"),
    _d("latency_p95", "Latency p95", ScoreType.DURATION, "ms", L, "D", "linear (type 7) quantile",
       "Over completed calls; timeouts counted separately.", aggregation="over completed calls"),
    _d("cost_total", "Known cost", ScoreType.CURRENCY, "currency", L, "D", "Σ known billed estimates",
       "By currency with coverage; missing price is not free.", aggregation="sum"),
    _d("cost_per_confirmed_success", "Cost per confirmed success", ScoreType.CURRENCY, "currency / pass", L, "D",
       "known total cost / passing slots", "Only when accounting coverage is complete."),
    _d("paired_delta", "Paired delta", ScoreType.OBSERVED_RATE, "difference", H, "S",
       "mean over clusters of (candidate − baseline)", "Cluster percentile bootstrap interval; not "
       "P(candidate is better)."),
    _d("accuracy_gap", "Accuracy gap", ScoreType.OBSERVED_RATE, "difference", N, "R",
       "acc_train − acc_eval, acc_eval − acc_prod_test, acc_prod_test − acc_later",
       "Observed differences (video slide 22), not causal proof."),
    _d("mean_token_log_probability", "Mean token log probability", ScoreType.TOKEN_LOG_PROBABILITY,
       "nats per token", N, "S", "(Σ_t l_t) / token_count", "Likelihood under the model and context; not the "
       "probability the answer is true."),
    _d("geval_expected_score", "Expected rubric score (G-Eval)", ScoreType.RUBRIC_SCORE, "rubric points", H, "S",
       "Σ s · P(score = s)", "Requires a complete score distribution; not a calibrated probability."),
]

METRICS: dict[str, MetricDefinition] = {d.name: d for d in _DEFINITIONS}


def definition(name: str) -> MetricDefinition:
    try:
        return METRICS[name]
    except KeyError as exc:
        raise KeyError(f"unknown metric {name!r}") from exc


def metric_value(name: str, value: float | None, *, reason: str | None = None, numerator: float | None = None,
                 denominator: float | None = None, eligible: int | None = None, missing: int | None = None,
                 uncertainty: Uncertainty | None = None, trial_ids: list[str] | None = None,
                 case_ids: list[str] | None = None, **provenance: Any) -> MetricValue:
    d = definition(name)
    return MetricValue(
        name=name, definition_version=d.version, score_type=d.score_type, value=value, unit=d.unit,
        direction=d.direction, numerator=numerator, denominator=denominator, eligible_count=eligible,
        missing_count=missing, unavailable_reason=reason if value is None else None, uncertainty=uncertainty,
        contributing_trial_ids=list(trial_ids or []), contributing_case_ids=list(case_ids or []),
        provenance={"formula": d.formula, "source": d.provenance, **provenance},
    )


def registry_payload() -> list[dict[str, Any]]:
    return [d.to_dict() for d in _DEFINITIONS]
