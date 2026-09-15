# Eval Triage — formula catalogue and video extraction

## Provenance

**V:** visually observed in selected frames of the supplied second video.  
**R:** reconstructed mathematically from the observed diagram and supplied narration, not a verbatim displayed equation.  
**S:** additional statistical/research method, not attributed to the video.  
**D:** proposed application definition.

The accompanying `metrics.py` is an executable reference for the explicitly marked functions below. It is not a complete evaluation runner or a reproduction of all upstream metric implementations.

## 1. Video: accuracy gaps [V + R]

At approximately **11:40**, the slide numbered 22 shows:

| Population | Displayed accuracy |
|---|---:|
| Train set | 0.90 |
| Evaluation set | 0.89 |
| Test set from production distribution | 0.88 |
| Later production data | 0.87 |

Arrows identify overfitting, domain shift, and drift. A useful signed reconstruction for a higher-is-better metric is:

```text
generalization_gap = accuracy_train − accuracy_eval
domain_gap         = accuracy_eval − accuracy_initial_prod_test
temporal_gap       = accuracy_initial_prod_test − accuracy_later_prod
```

All three equal **0.01 = 1 percentage point** in the illustration. These are observed differences, not causal proof. Noise, population selection, model changes and labelling changes can also affect them. For loss metrics, reverse the sign convention or explicitly name the quantity. Code: `accuracy_gaps`.

[Video frame at 11:40](https://www.youtube.com/watch?v=2CIIQ5KZWUM&t=700s).

## 2. Video: slice accuracy [V + R]

At approximately **13:20**, slide 26 shows overall accuracy 0.90 and:

| Slice | Displayed accuracy |
|---|---:|
| Startups | 0.95 |
| Dogs | 0.90 |
| Food | 0.85 |
| Physics | 0.17 |

For disjoint, exhaustive slices, aggregate accuracy is:

```text
accuracy = Σ_s w_s × accuracy_s, where Σ_s w_s = 1
```

The slide does not supply slice counts/weights. The unweighted mean is **0.7175**, not 0.90. Therefore, do not reproduce 0.90 by averaging these four values equally or infer the original dataset from the illustration. Its point is that a headline score can conceal poor performance on an important slice. Code: `weighted_mean`.

[Video frame at 13:20](https://www.youtube.com/watch?v=2CIIQ5KZWUM&t=800s).

At about **22:40**, slide 48 presents a metric-selection tree: a correct answer → conventional metrics; a reference answer → reference matching; a previous answer → comparative preference; human feedback → feedback incorporation; otherwise static metrics. This is a selection heuristic, not a probability equation. [Decision tree](https://www.youtube.com/watch?v=2CIIQ5KZWUM&t=1360s).

## 3. Observed success and Wilson interval [S]

For `c` successful outcomes from `n` eligible independent Bernoulli trials:

```text
p_hat = c / n
z = normal quantile for the requested confidence level
d = 1 + z²/n
center = (p_hat + z²/(2n)) / d
half_width = z × sqrt(p_hat(1−p_hat)/n + z²/(4n²)) / d
interval = [center − half_width, center + half_width]
```

At 95% confidence, `z ≈ 1.959964`. For 18/20 passes, the interval is approximately **69.9%–97.2%**. A frequentist interval is a procedure with repeated-sampling coverage, not a posterior probability that this specific interval contains the parameter. Code: `wilson_interval`.

Use per-case repeated-trial intervals only for a controlled, plausibly independent repeat design. Pooling every repeat across heterogeneous cases as one binomial experiment can misrepresent uncertainty. Use case/episode clustering for dataset-level comparisons. [NIST confidence interval reference](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).

### Zero observed failures

For zero failures in `n` independent trials, an exact one-sided upper confidence bound for failure probability is:

```text
q_upper = 1 − alpha^(1/n)
```

At 95% confidence, `alpha = 0.05`: n=100 → about 2.95%; n=299 → below 1%. Code: `zero_failure_upper_bound`.

## 4. Bayesian probability estimate [S]

Under a declared Beta(a,b) prior for one Bernoulli success probability:

```text
p | data ~ Beta(a + c, b + n − c)
posterior_mean = (a + c) / (a + b + n)
```

The reference uses a configurable prior, default Beta(1,1). Code: `beta_posterior_mean`. For a credible interval, use beta-distribution quantiles in a numerical library; that calculation is not implemented in this minimal module. Do not call a Wilson interval a credible interval. Do not treat a smoothed pass rate as a calibrated prediction of an individual answer's correctness. [SciPy beta distribution and quantiles](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.beta.html).

## 5. Repeatability [D]

Choose a representation before counting: raw text, validated canonical JSON, canonical tool arguments, or human/metric-assigned semantic classes. Let class counts be `n_j`, total `n`.

```text
modal_agreement = max_j(n_j) / n
pairwise_agreement = Σ_j n_j(n_j−1) / [n(n−1)]
empirical_entropy = −Σ_j (n_j/n) ln(n_j/n)
```

Pairwise agreement estimates the chance that two sampled outputs from the observed pool match without replacement. Entropy is in nats. These quantities measure variation, not correctness. Code: `repeatability`.

For six A responses and four B responses: modal agreement = 0.6; pairwise agreement = 42/90 ≈ 0.4667. This example also illustrates why “most common answer frequency” and “two draws match” are different measures.

For one output, the reference marks pairwise agreement and entropy unavailable: repeatability has not been measured. Semantic classes require a versioned clustering/equivalence procedure, with ambiguous comparisons reviewed. Never use “semantically deterministic” without stating that procedure.

Define **observed flaky case** as a case with at least one pass and one fail among eligible repeats. It is a diagnostic label, not an unbiased estimate of how many production cases are intrinsically unreliable.

## 6. At least one success versus all successes [S]

For a fixed task with independent attempts sharing success probability `p`:

```text
P(at least one success in k attempts) = 1 − (1−p)^k
P(all k attempts succeed)            = p^k
```

With p=0.8 and k=5, these are **99.968%** and **32.768%**. A system can look excellent when given many chances while being unreliable when every attempt must work.

Given `c` successes among `n` sampled attempts, unbiased estimators for `k ≤ n` under the fixed-task IID model are:

```text
pass@k = 1 − C(n−c, k) / C(n, k)
pass^k = C(c, k) / C(n, k)
```

Treat combinations with top < k as zero. Average these per-task estimates over the declared task population. Do **not** raise an overall average pass rate to k when tasks have different success probabilities. Repeated full episodes must reset to comparable initial state. Code: `pass_at_k`, `pass_all_k`.

The first estimator is associated with code-generation evaluation; the all-success interpretation is useful for agent reliability. [HumanEval paper](https://arxiv.org/abs/2107.03374), [τ-bench](https://arxiv.org/abs/2406.12045), [agent-eval explanation](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## 7. Probability quality [S]

For a binary outcome `y_i ∈ {0,1}` and a probability prediction `p_i` made before seeing its label:

```text
Brier = mean_i [(p_i − y_i)²]
LogLoss = −mean_i [y_i ln(p_i) + (1−y_i) ln(1−p_i)]
```

Smaller is better. The binary Brier convention here has range [0,1]. The reference log-loss function clips predictions to `[epsilon,1−epsilon]` for finite numerical output and validates epsilon. This clipping is a numerical convention: in the exact mathematical score, a confidently wrong p=0 or p=1 prediction gives infinite loss. Code: `brier_score`, `binary_log_loss`.

These scores cannot be computed from a pass/fail label alone as evidence of calibrated probability. An LLM saying “90% confident,” a judge scoring 0.9, and a token likelihood of 0.9 are different inputs with different meanings. Fit a calibration mapping on a separate labelled set and assess it on held-out cases. [Probability calibration](https://scikit-learn.org/stable/modules/calibration.html).

### Reliability bins and expected calibration error

For fixed bins B_m:

```text
bin_prediction_m = mean(p_i in B_m)
bin_outcome_m    = mean(y_i in B_m)
ECE = Σ_m |B_m|/N × |bin_outcome_m − bin_prediction_m|
```

Code: `calibration_bins`, returning both bin contents and ECE. This is binary event-probability calibration, not multiclass top-label ECE. Empty bins have null means. The reference uses equal-width bins and places p=1 in the final bin. ECE depends on binning and sample size and can hide poor behavior in slices; show counts and a reliability diagram as well. A small ECE on a small selected dataset is not a release guarantee. [On Calibration of Modern Neural Networks](https://arxiv.org/abs/1706.04599).

## 8. Selective prediction [D based on S]

If `p_i` means predicted probability that the selected answer is correct, accept answers at threshold `t`:

```text
coverage(t) = count(p_i ≥ t) / N
risk(t) = count(y_i = 0 and p_i ≥ t) / count(p_i ≥ t)
```

This allows the UI to answer: “If we send uncertain cases for review, how much workload remains automated, and how often are accepted answers wrong?” Risk is undefined when nothing is accepted. Code: `selective_risk`. Threshold selection belongs on validation data; evaluate the chosen threshold on held-out data. A binary class probability `P(class=1)` is not automatically answer-correctness confidence.

## 9. Retrieval and fact scoring [S/D]

For relevant IDs R and retrieved top-k IDs T_k:

```text
Precision@k = |R ∩ T_k| / |T_k|
Recall@k = |R ∩ T_k| / |R|
MRR = mean(1 / rank_of_first_relevant_item), using 0 if none
DCG@k = Σ_(i=1..k) (2^relevance_i − 1) / log2(i+1)
nDCG@k = DCG@k / ideal_DCG@k
```

Deduplicate IDs and define what happens when R or T_k is empty. This catalogue uses retrieved-count precision; a fixed-slot `/k` version must be named differently. Relevance labels can be human-authored or model-generated; record which. Exact ID retrieval metrics and framework-specific “contextual precision” are not interchangeable.

For extracted facts, use one-to-one matching to reference facts before computing TP, FP, FN; duplicates must not earn repeated credit:

```text
Precision = TP / (TP+FP)
Recall = TP / (TP+FN)
F1 = 2TP / (2TP+FP+FN)
SupportedClaimFraction = supported generated claims / evaluated generated claims
```

A no-claim answer requires a separate completeness/abstention verdict. Returning nothing must not receive a perfect overall quality score just because it contains no unsupported claim. The Ragas definition of faithfulness is grounded in support for generated claims; implementations can involve claim extraction and entailment judgments. These are not pure deterministic measurements. [Ragas faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/), [Ragas paper](https://arxiv.org/abs/2309.15217).

Retrieval and semantic fact-matching functions are specified here but not implemented in the minimal mathematics module; integrate established libraries with explicit definitions.

## 10. Token probabilities and G-Eval [S]

For an observed token log probability `l_t`:

```text
P(token_t | context, previous_tokens) = exp(l_t)
log P(sequence | context) = Σ_t l_t
mean_token_log_probability = (Σ_t l_t) / token_count
```

Sequence probability depends on length, tokenizer and conditioning context; it is not the probability the answer is true. Top-token lists may omit relevant alternatives. Do not interpret renormalization over a truncated list as full probability mass.

G-Eval includes probability-weighted numerical grading. A generic expected rubric score is `Σ_s s P(score=s)`, provided that the relevant score distribution is available and valid. This remains an expected **rubric score**, not a calibrated correctness probability. Multitoken score encodings and incomplete logprobs require explicit handling. This method is connected to the first video's metric discussion, not visually extracted from Tobin's slides. [G-Eval paper](https://arxiv.org/abs/2303.16634), [OpenAI token-logprob API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

## 11. Paired candidate comparison [S/D]

Let `d_i = candidate_score_i − baseline_score_i`, using one summary per independent case or episode.

```text
delta = mean_i(d_i)
bootstrap: sample case indices with replacement; keep each A/B pair together
recompute delta for every resample
interval: chosen bootstrap interval method
```

The reference `paired_delta_interval` implements a reproducible **percentile** bootstrap over paired case summaries for illustration. It is not a hierarchical bootstrap. It reports the independent-case count. For production inference, choose a suitable interval method, inspect degenerate samples, and implement conversation/user-level clustering where needed. Never interpret a bootstrap interval as `P(candidate is better)`.

[SciPy bootstrap documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html).

## 12. Undefined values and score provenance

- No eligible examples → unavailable, not zero or perfect.
- Failed grader → grading error, not automatic model failure or pass.
- Unsupported logprobs → unavailable with reason.
- No accepted predictions → selective risk unavailable.
- Insufficient repeats → repeatability not measured.
- Judge-generated labels → report judge version and validation quality.
- Missing outcomes in a candidate comparison → show coverage and exclusion policy.

For every score, persist formula/version, numerator, denominator, units, source labels, and uncertainty method. These details belong in the result's evidence panel.
