# Metrics

Eval Triage keeps four questions apart and never folds them into one
"confidence" number:

1. **Quality** — did the output satisfy the contract? (pass rules, check
   results, fact and retrieval metrics)
2. **Repeatability** — do repeats agree with each other? (agreement, entropy,
   pass@k, pass^k)
3. **Probability quality** — are predicted probabilities for a named event
   trustworthy? (Brier, log loss, ECE, reliability, selective risk)
4. **Operations** — did the system run? (completion, coverage, latency, cost)

The formulas are specified in [FORMULAS.md](./FORMULAS.md) (identical to
section 14 of [plan.md](./plan.md)); the production implementations live in
`backend/eval_triage/statistics/` and are tested against the plan's reference
vectors and `docs/metrics.py`.

## MetricValue

Every number the API returns and the UI shows is a `MetricValue`:

| Field | Meaning |
|---|---|
| `value` | The number, or `null` — never a silent zero |
| `unavailable_reason` | Why `value` is `null` (for example "k=5 exceeds graded repeats") |
| `unit`, `direction` | What the number measures, and whether higher is better |
| `numerator`, `denominator` | The counts it was computed from |
| `eligible_count`, `missing_count` | What was eligible, and what was missing |
| `uncertainty` | Method, level, bounds and a label such as "95% Wilson interval (frequentist)" |
| `definition_version` | The registry entry (`name@version`) |
| `contributing_trial_ids` | The exact trials behind the number (the UI links to each) |

`GET /api/v1/metrics` returns the registry. `POST /api/v1/statistics/query`
refuses to combine metrics of different score types.

## Outcomes and slot rates

A trial's outcome comes from the dataset's pass rule (see
[architecture.md](./architecture.md#grading-and-outcomes)). For each
candidate, slots are counted as **S** scheduled, **G** generated (target
returned output), **E** eligible and binary-graded, **P** passed and **F**
failed:

| Metric | Formula | Reads as |
|---|---|---|
| `target_completion` | G / S | Did the target produce output? |
| `grade_coverage` | graded / eligible | Did grading reach a verdict? |
| `conditional_pass` | P / (P + F) | Pass rate among graded slots |
| `observed_success_yield` | P / S | Passes among everything scheduled (unresolved slots are not claimed to be wrong) |

## Per-case quality and repeatability

Repeats are summarised **per case first**.

* `observed_pass_rate` = passes / binary-graded repeats, with a **Wilson**
  95% interval (frequentist; valid only for plausibly independent repeats).
  For 18 of 20 this is 69.9–97.2%.
* `beta_posterior` = Bayesian posterior mean under a declared prior (default
  Beta(1,1)) with an equal-tailed 95% **credible** interval. Wilson and Beta
  intervals answer different questions and are always labelled separately.
* `zero_failure_upper_bound` — the exact one-sided bound after no failures.
* `pass_at_k` = 1 − C(n−c, k)/C(n, k) and `pass_all_k` = C(c, k)/C(n, k), shown
  only for k ≤ n graded repeats (never pass-rate^k).
* `modal_agreement` = max_j n_j / n, `pairwise_agreement` =
  Σ n_j(n_j−1) / n(n−1), `output_entropy` = −Σ (n_j/n) ln(n_j/n). Output
  categories use one of three declared representations: **raw** text,
  **canonical JSON** (unparsable outputs are ineligible and counted), or
  **semantic** (`semantic:pass_rule_outcome_v1`, the pass-rule outcome). High
  agreement measures variation, not correctness: M05 in the demo is 20/20
  consistent and 20/20 wrong.

## Retrieval, facts and classification

Precision/recall@k (after de-duplication; a separately named fixed-slot
precision), reciprocal rank, nDCG with graded gains (unavailable when the
ideal DCG is 0); one-to-one fact matching (exact normalised by default; an
optional threshold matcher discards pairs below the threshold) with fact
precision, recall and F1; accuracy and micro/macro F1 (omitted classes are
listed); pairwise win rate (abstentions excluded and reported). Each returns
`null` with a reason where its denominator is empty.

## Probability quality

Records carry the named event ("the generated answer is correct"), score
type, method, source version, prediction time, label and label source. Only
compatible score types are combined.

* **Brier** score, **clipped log loss** (declared epsilon; the exact loss is
  infinite for confident errors), and **ECE** over 10 equal-width bins by
  default. The reliability diagram shows counts, including empty bins, and
  every bin opens its records.
* **Selective prediction** at threshold t: coverage (share accepted) and
  selective risk (error rate among accepted). With no accepted predictions the
  risk is "Unavailable: no accepted predictions".
* **Calibration** fits on the *calibration* split only (the held-out test split
  is refused), requires both classes and at least 30 independent clusters,
  splits by cluster, and stores parameters as JSON (logistic without
  penalty, or bounded isotonic). Results are shown on the held-out split with
  raw and calibrated curves side by side.
* Token log-probabilities and G-Eval expected scores are likelihood and rubric
  quantities, not probabilities that an answer is true. When a model does not
  offer logprobs the UI shows an unavailable panel instead of a gauge.

## Operations

`latency_p50` / `latency_p95` (type-7 quantiles over completed calls;
timeouts counted separately), `cost_total` by currency with coverage (a
missing price is unknown, not free) and `cost_per_confirmed_success` only when
coverage is complete. Retry and judge costs are reported separately.

## Comparisons and release gates

* Runs are paired on `(external_id, case_hash)`, so a dataset v1 → v2 comparison
  pairs unchanged cases and lists added or changed cases as exclusions.
  Compatibility checks (graders, pass rule, repeat design, scenario) run first;
  when they fail, inferential deltas are disabled.
* `case_pass_rate` (mean per-case pass fraction) is compared with a **paired
  cluster percentile bootstrap** (10,000 resamples, seed 42, equal-weight
  clusters). The interval describes the resampling procedure; it is not the
  probability that the candidate is better. Fewer than 20 independent clusters
  and degenerate samples are flagged.
* A release policy declares metrics, directions and margins, critical
  invariants and minimum paired coverage. The gate is **Ready** only when every
  required check clears its margin and no critical invariant failed,
  **Blocked** when a required check or invariant fails, and **Inconclusive**
  otherwise (for example when the interval crosses the margin). With several
  gated metrics a multiplicity caveat is shown. The gate is evidence, not a
  deployment action.

## External scores

Scores imported from Promptfoo or Inspect, and Ragas metric values, keep the
tool's own definition and implementation version and are marked
`is_probability: false`. They are never averaged with Eval Triage's metrics.

## Registry

| Metric | Score type | Unit | Direction |
|---|---|---|---|
| observed_pass_rate | observed_rate | fraction of graded repeats | higher is better |
| wilson_interval | observed_rate | fraction | neutral |
| beta_posterior | posterior_success_probability | probability | higher is better |
| zero_failure_upper_bound | observed_rate | failure probability | lower is better |
| modal_agreement | agreement | fraction of repeats | neutral |
| pairwise_agreement | agreement | probability two repeats match | neutral |
| output_entropy | entropy | nats | neutral |
| pass_at_k | observed_rate | probability | higher is better |
| pass_all_k | observed_rate | probability | higher is better |
| brier | distance | squared error | lower is better |
| log_loss_clipped | distance | nats | lower is better |
| ece | distance | probability | lower is better |
| selective_risk | observed_rate | error fraction of accepted | lower is better |
| coverage | observed_rate | fraction accepted | higher is better |
| precision_at_k, precision_fixed_slots_at_k, recall_at_k | observed_rate | fraction | higher is better |
| reciprocal_rank, ndcg_at_k | observed_rate | 1/rank, fraction of ideal | higher is better |
| fact_precision, fact_recall, fact_f1 | observed_rate | fraction / F1 | higher is better |
| supported_claim_fraction | observed_rate | fraction of claims | higher is better |
| accuracy, macro_f1, micro_f1 | observed_rate | fraction / F1 | higher is better |
| win_rate | observed_rate | fraction of eligible judgements | higher is better |
| target_completion, grade_coverage, conditional_pass, observed_success_yield | observed_rate | fraction | higher is better |
| case_pass_rate | observed_rate | mean per-case pass fraction | higher is better |
| latency_p50, latency_p95 | duration | ms | lower is better |
| cost_total, cost_per_confirmed_success | currency | currency | lower is better |
| paired_delta | observed_rate | difference | higher is better |
| accuracy_gap | observed_rate | difference | neutral |
| mean_token_log_probability | token_log_probability | nats per token | neutral |
| geval_expected_score | rubric_score | rubric points | higher is better |
