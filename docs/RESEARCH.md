# Eval Triage: AI evaluation research

**Research date:** 15 September 2026  
**Purpose:** choose a credible open-source foundation and define an evaluation product for LLM calls, retrieval, agents, and MemoryAI.

## 1. Recommended direction

Build Eval Triage as a focused evaluation and investigation application. Its central question should be: **“What failed, how reliably does it fail, what evidence supports that judgment, and did the proposed change improve it?”**

Use a small Python service, a dedicated UI, explicit target adapters, and immutable experiment records. Make MemoryAI the first stateful target and an optional source of contextual memory for applications under evaluation. Keep the evaluation database separate from MemoryAI's learned facts. A system being tested must not also decide or overwrite its own ground truth.

Recommended composition:

| Responsibility | Initial choice | Reason for this project |
|---|---|---|
| Product UI, scenarios, review queue, release decisions | Eval Triage | Your distinguishing workflow; existing tools do not supply your MemoryAI lifecycle contract |
| General evaluation execution | Inspect AI integration | Python tasks, solvers, scorers, logs, agent support, extensibility |
| Pure checks and statistics | Small owned module; mature numerical libraries for advanced inference | Transparent formulas and consistent interpretation across providers |
| Retrieval/grounding metrics | Ragas integration when needed | Established retrieval and answer-level evaluation methods |
| Security suites | Promptfoo as a separate worker/importer | Declarative attack and assertion workflows; existing result viewer |
| Model access | Native OpenAI and Anthropic SDK adapters; local endpoint adapters | Preserve capabilities and raw provider metadata |
| Stateful memory | MemoryAI adapter over its Python operations | Reuse extraction, recall, retraction, review, and replay behavior |
| Initial storage | SQLite plus file artifacts | Simple local operation; move to PostgreSQL for concurrent/team use |
| Tracing | Portable trace/span identifiers; optional OpenTelemetry export | Avoid making a third-party dashboard the application's data model |

This is an architecture recommendation, not evidence that this combination outperforms alternatives. Inspect's documented extension and scoring surfaces support this direction. A short integration spike should prove cancellation, repeated trials, state isolation, and log import before committing to its internal APIs. [Inspect documentation](https://inspect.aisi.org.uk/), [scorers](https://inspect.aisi.org.uk/scorers.html), [log format](https://inspect.aisi.org.uk/eval-logs.html).

**Alternative:** if the first version is mostly “input → answer → assertions” in Python, use DeepEval instead of Inspect. If the goal becomes “get a ready-made evaluation dashboard immediately,” trial Opik or MLflow before building the full UI. These are different product choices; installing everything adds overlapping datasets, score models, and storage.

## 2. What to retain from your videos

### Video 1 — Mete Atamel: Beyond the Prompt

The supplied transcript covers a useful progression: define what “good” means; distinguish deterministic checks from model grading; evaluate retrieval separately from generation; inspect tool use and agent trajectories; add security evaluation. Its framework examples include DeepEval, Ragas, Promptfoo, and TruLens. The published slide deck corroborates that structure, although it is an earlier deck and should not be treated as a frame-exact copy of the supplied recording. [Video](https://www.youtube.com/watch?v=b2qel03SU4I), [speaker's slides](https://speakerdeck.com/meteatamel/beyond-the-prompt-evaluating-testing-and-securing-llm-applications).

Translate this into **scenario packs** rather than a long unstructured list of metrics. An extraction pack needs field correctness; a retrieval pack needs evidence coverage; a tool pack needs valid arguments and permitted outcomes.

Several statements need more precise product treatment:

- A valid schema does not imply correct values. Keep schema conformance, refusal, truncation, and semantic correctness separate.
- A similarity value of 0.7 is not a 70% probability of correctness.
- Grounded answers can still be wrong if the supplied context is wrong or obsolete.
- Exact matching of a complete tool sequence is appropriate only when that order is required. Otherwise grade allowed constraints and final state; several paths may be valid.
- A judge-driven decision graph can have deterministic branching while its model judgments remain variable.
- Security scanners are measurable components. Their false positives and false negatives need evaluation too.

These are design conclusions from the distinction between what each measurement observes and the real outcome it is intended to represent. The G-Eval paper and later agent-evaluation guidance reinforce the need to validate model graders and outcome checks. [G-Eval](https://arxiv.org/abs/2303.16634), [Anthropic agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

### Video 2 — Josh Tobin: Evaluating LLM-based Applications

The supplied transcript makes four central arguments:

1. Evaluate the task your users perform, with your prompts and application configuration.
2. Grow coverage from difficult, unusual, and production-derived examples.
3. Check that automated metrics predict outcomes people actually care about.
4. Use carefully designed human review to validate automated evaluation.

The video also warns that aggregate accuracy can hide severe failures within a topic. I visually inspected the 11:40 diagram and 13:20 example. The first shows accuracies 0.90, 0.89, 0.88, and 0.87 for training, evaluation, initial test, and later production. The second shows overall 0.90 with topic values 0.95, 0.90, 0.85, and 0.17. See the formula catalogue for the mathematical reconstruction and its limits. [Methodology diagram](https://www.youtube.com/watch?v=2CIIQ5KZWUM&t=700s), [topic example](https://www.youtube.com/watch?v=2CIIQ5KZWUM&t=800s).

Do not interpret the video's remark that drift “doesn't matter” as an operational rule. Changing traffic, memory content, retrieval indexes, policies, providers, and graders can all change application behavior. Measure these changes on the relevant slices, and distinguish a changed test population from a regression on a frozen dataset.

The supplied transcript and inspected frames do **not establish a comprehensive probability-scoring formula attributed to Tobin**. The formulas added here for confidence intervals, calibration, and repeated success are separate mathematical methods with their own sources. This prevents a misleading “extracted from video” claim.

## 3. The evaluation model Eval Triage needs

### Three axes, plus operational cost

| Axis | Question | Suitable output |
|---|---|---|
| Correctness | Did it satisfy this task's contract? | Pass/fail, field F1, supported-claim fraction, final-state success |
| Repeatability | Does the same controlled experiment give the same result? | Exact/structural agreement, semantic agreement, pass variability |
| Probability quality | Do predicted probabilities match observed outcomes? | Brier score, log loss, reliability diagram, risk versus coverage |
| Efficiency | What resources did this behavior require? | Latency distributions, tokens, retries, cost per successful task |

A model that always returns the wrong city is highly repeatable and incorrect. A model can produce many differently worded correct answers. The same judge can give unstable scores to one fixed answer. Each of these requires a different investigation.

The UI should use precise names:

- **Observed pass rate:** fraction of trials that passed a specified grader.
- **Estimated pass probability:** statistical estimate under stated sampling assumptions.
- **Predicted correctness probability:** a model/calibrator prediction for a particular output, validated on held-out labels.
- **Judge rubric score:** an ordinal or numerical judgment; not automatically a probability.
- **Token log probability:** likelihood of a generated token under a particular model/context.
- **Retrieval rank score:** ordering signal; not a correctness probability.

Probability calibration means, for example, that outputs assigned about 0.8 probability succeed about 80% of the time in an appropriate population. Brier score and log loss also measure discrimination, so neither alone is a pure calibration diagnostic. [scikit-learn calibration guide](https://scikit-learn.org/stable/modules/calibration.html).

### Reproducibility contract

Record the exact dataset version, case ID, conversation/cluster ID, target configuration, full rendered prompt hash, model identifier returned by the provider, endpoint type, sampling settings, seed when supported, prompt template, tool definitions, memory fixture, retrieval corpus, embedding/reranker versions, evaluator definition, and execution environment.

Run two distinct experiments:

1. **Controlled repeatability:** same request, state, and supported seed/settings; disable response-result caches.
2. **Operational reliability:** repeat under the deployment's actual sampling and retry policy, with explicitly managed state.

Provider prompt-prefix caching is different from a local response cache: it generally reuses prompt computation, not a previously generated answer. Record both so latency and variability are interpretable. A response cache can produce a false impression of perfect repeatability.

OpenAI documents seed-based generation as best effort and warns that determinism is not guaranteed. Claude's current API reference also warns that temperature zero is not fully deterministic, and describes model-dependent restrictions on sampling parameters. Therefore, a universal “temperature = 0” switch is unsuitable. Show whether a parameter is supported and what actually went into the request. [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Claude Messages reference](https://platform.claude.com/docs/en/api/messages/create).

## 4. Open-source landscape

### Method and limits

The comparison below uses maintainer repositories and official documentation inspected for this report. “Fit” is my judgment for Eval Triage, based on local operation, extensibility, stateful scenarios, inspectable evidence, and integration burden. I did not install and benchmark each framework. License labels refer to the reviewed upstream core; packages, plugins, enterprise directories, model weights, and datasets can have separate terms. Pin releases and retain dependency notices during implementation.

| Tool | Reviewed core license | Strength | Limitation for this project | Recommended role |
|---|---|---|---|---|
| **Inspect AI** | MIT | Extensible Python execution, scoring, agents, detailed logs/viewer | Custom product triage and MemoryAI lifecycle adapter still required | First general runner integration |
| **DeepEval** | Apache-2.0 | Python test workflow; extensive task, RAG, and agent metrics | Hosted Confident AI is distinct from the OSS library; score interpretation remains your responsibility | Runner alternative or selective graders |
| **Promptfoo** | MIT | Declarative provider comparisons, assertions, red teaming, local results UI | Separate runtime and result schema; stateful memory setup needs custom integration | Security packs and configuration-based suites |
| **Ragas** | Apache-2.0 in current repository | Retrieval/answer metrics and synthetic test generation | Grader cost/bias and reference requirements vary by metric | Retrieval metrics adapter |
| **TruLens** | MIT | Tracing with feedback at application steps | Overlaps with your own traces and other platforms | Alternative tracing/evaluation integration |
| **MLflow** | Apache-2.0 | Experiments, tracing, model/application evaluation | General platform; specialized triage remains custom | Best fit when broader ML tracking is also needed |
| **Opik** | Apache-2.0 | Self-hosted traces, datasets, experiments, annotations | Running/forking a full platform increases product and operational scope | Strong ready-made UI candidate to trial |
| **Langfuse** | MIT core; enterprise portions separate | Trace-centric workflow, prompts, evaluation and datasets | Some enterprise functions use a commercial license; overlaps with Eval Triage storage/UI | Team observability alternative |
| **Phoenix** | Elastic License 2.0 for server | Strong trace/retrieval inspection and experiments | Source-available terms restrict offering substantial functionality as a hosted service | Internal companion if terms fit; avoid default rebranding foundation |
| **Evidently** | Apache-2.0 | Data-quality, drift and evaluation reporting | Not a full stateful agent runner | Later production distribution analysis |
| **garak** | Apache-2.0 | Broad model vulnerability probes/detectors | Model scanning differs from application end-to-end security | Optional model-level probe import |
| **PyRIT** | MIT | Programmable generative-AI risk campaigns | More specialist security orchestration than routine correctness tests | Later adversarial scenarios |
| **lm-evaluation-harness** | MIT | Reproducible public model benchmarks and local model backends | Public model capability is not your application quality | Separate model pre-screening |
| **HELM** | See repository license before pinning | Multi-scenario foundation-model assessment | Substantial benchmark apparatus; application fixtures still required | Research comparison, not MVP core |
| **LiteLLM** | Verify selected SDK/proxy and enterprise components | Broad provider routing and normalization | Abstraction can obscure unsupported parameters and provider-specific output | Optional later gateway, not a grader |

Primary sources for the rows: [Inspect](https://github.com/UKGovernmentBEIS/inspect_ai), [DeepEval](https://github.com/confident-ai/deepeval), [Promptfoo](https://github.com/promptfoo/promptfoo), [Ragas](https://github.com/vibrantlabsai/ragas), [TruLens](https://github.com/truera/trulens), [MLflow](https://github.com/mlflow/mlflow), [Opik](https://github.com/comet-ml/opik), [Langfuse](https://github.com/langfuse/langfuse), [Langfuse enterprise terms](https://github.com/langfuse/langfuse/blob/main/ee/LICENSE), [Phoenix](https://github.com/Arize-ai/phoenix), [Phoenix terms](https://github.com/Arize-ai/phoenix/blob/main/LICENSE), [Evidently](https://github.com/evidentlyai/evidently), [garak](https://github.com/NVIDIA/garak), [PyRIT](https://github.com/microsoft/PyRIT), [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness), [HELM](https://github.com/stanford-crfm/helm), [LiteLLM](https://github.com/BerriAI/litellm).

### Build versus adapt

**Own:** scenario schema, repeated-trial semantics, memory isolation, evidence links, metric meanings, calibrator versions, review decisions, and release gates. These define the reliability of Eval Triage.

**Reuse:** provider clients, general runner mechanics, well-documented retrieval metrics, numerical statistics, tracing protocols, and red-team datasets/engines.

**Avoid in the first version:** forking a large dashboard for branding alone; treating proprietary hosted products as part of an OSS library; deploying three competing trace stores; implementing every published metric; making a public leaderboard the primary quality target.

For an entirely local setup, use local targets and a local judge, with rule-based checks first. “Open-source evaluator” does not imply “free inference” or “local inference.” Report judge hardware/model requirements and assess judge agreement before using it for release decisions. An open-weight model's own license is also distinct from the evaluation framework license.

## 5. Scenario catalogue

| Pack | Cases to include | Primary evidence and measures |
|---|---|---|
| Structured extraction | Missing values, negation, multiple entities, conflicting updates, multilingual text | JSON validity; per-field precision/recall/F1; source-supported facts |
| Classification/routing | Imbalanced classes, ambiguous input, abstention, unseen category | Confusion matrix, macro F1, per-class recall, calibration |
| Retrieval | Relevant/irrelevant documents, hard negatives, empty evidence, stale facts | Recall@k, precision@k, nDCG, context budget, retrieval trace |
| Grounded answers | Supported claims, contradictions, citation mismatch, insufficient context | Claim support, citation validity, answer correctness, appropriate abstention |
| Summarization | Required facts, omissions, invented facts, changed numbers/negation | Fact coverage plus unsupported-claim rate; task rubric |
| Tool use | Wrong tool, malformed args, extra action, invalid order, retry | Schema checks, allowed sequence constraints, final-state verification |
| Stateful agents | Multi-turn goals, tool failure, recovery, contamination across runs | Whole-episode outcome and trace; repeated success |
| Memory lifecycle | Remember, correct, retract, reject, forget, rebuild, recall | Fact states, provenance, temporal truth, leak/omission rate |
| Robustness/security | Direct and retrieved instructions, memory poisoning, unauthorized tools | Attack success plus benign-task success; separate threat scenarios |
| Multimodal, later | OCR, visual facts, image-grounded answers | Task-specific ground truth and visual evidence, not text-only proxy scores |

Memory benchmarks provide useful inspiration: LongMemEval covers information extraction, cross-session reasoning, temporal reasoning, knowledge updates, and abstention; LoCoMo examines long-term conversational memory. Adapt these ideas to your lifecycle operations and users rather than claiming benchmark performance from a small custom suite. [LongMemEval](https://arxiv.org/abs/2410.10813), [LoCoMo](https://arxiv.org/abs/2402.17753).

Behavioral invariance tests are especially valuable: paraphrase the input without changing its meaning, insert irrelevant context, reorder independent facts, or replace names while preserving roles. Specify whether the expected output should stay the same or change predictably. [CheckList paper](https://arxiv.org/abs/2005.04118).

## 6. Dataset and experimentation discipline

Maintain four separately versioned collections:

1. **Development:** inspect freely and use to improve prompts.
2. **Regression:** previously working important cases and confirmed past failures.
3. **Locked evaluation:** withheld from prompt, grader, and threshold tuning.
4. **Production audit:** representative sampled traffic, with selection probabilities where possible.

A separate labelled calibration split is required when mapping model/judge features to probabilities. Split by user/conversation/document cluster, not just message, so adjacent turns and near duplicates do not leak across splits. When labelled data is scarce, use cross-fitting and report the limitation.

Start with roughly 30–50 carefully authored cases across the first two packs as an engineering pilot, then expand to hundreds of independent cases for more sensitive comparisons. This is a proposed plan, not a universal sample-size rule. Synthetic examples help discover failure modes; they should not be presented as representative production traffic without validation. OpenAI recommends task-specific evaluation, production-informed examples, and ongoing expansion. [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

For each case store the expected behavior, allowed alternatives, prohibited behavior, category, severity, evidence, and rationale. Include “no relevant fact,” “correctly refuse,” and “insufficient evidence” cases. A metric must not reward producing extra claims simply because some are correct.

### Repeated trials and uncertainty

Use a case × candidate × repeat layout. Five repeats on a pilot reveal obvious variability; 20–30 repeats on a suspect case are useful for diagnosis. Neither is a proof of determinism.

Two hundred distinct cases, two candidates, and five repeats require **2,000 target executions**, before retries. Two judges per output require at least 4,000 judge calls, and claim-splitting or multi-turn evaluation may use more. Save outputs so graders can be rerun without regenerating targets.

An important precision example: with zero failures in 100 independent trials, a one-sided 95% upper confidence bound on the failure probability is about 2.95%. To bound it below 1% with zero failures takes at least 299 such trials. Dependence, dataset selection, and evolving memory invalidate the simple independent-trial interpretation.

For candidate comparisons, use the same case IDs and fixtures. Compute a difference per independent case/episode and bootstrap those paired differences; cluster by conversation or user when required. Do not pretend that all repeated calls are independent new user cases. Paired resampling is supported by SciPy, but cluster grouping must be implemented deliberately. [SciPy bootstrap documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html).

Report improvements and regressions separately, including critical slices. Predeclare important gates and practical effect sizes. Repeatedly searching many prompts on one test set selects noise; use a locked final evaluation and, when making many formal claims, an appropriate multiplicity or sequential-testing procedure.

## 7. Trustworthy grading and triage

Prefer deterministic checks wherever the contract permits: schema validity, numerical tolerance, required fields, authorized tool names, database-state assertions, and evidence identifiers. Use model judgment for the remaining semantic questions.

A good judge returns a narrowly scoped verdict, evidence spans, and an explanation tied to the rubric. The evaluated content is untrusted input to the judge. It must not override the rubric or call tools. Keep generation, judging, and human annotation identities separate.

Validate the judge on expert-labelled examples. Measure its confusion matrix, especially false passes on critical failures; repeat grading on frozen outputs; hide provider names; randomize A/B order; and audit disagreements. Similar judges can share errors, so majority vote is not an independent guarantee. Position, verbosity, and self-preference biases are documented in LLM-as-judge research. [MT-Bench and Chatbot Arena judge study](https://arxiv.org/abs/2306.05685).

Use human review for ambiguous or consequential cases and to improve grader validity. Reviewers should select concrete failure categories and supporting passages. Track reviewer disagreement and adjudication; do not overwrite historical judgments. Review a random sample of auto-passes as well as the failure queue, otherwise undetected failures remain invisible.

Suggested triage ordering:

1. Confirmed critical invariant failures.
2. Regressions on important slices.
3. Judge-human or judge-judge disagreement.
4. Cases that pass on some repeats and fail on others.
5. Newly observed or underrepresented input categories.
6. Ordinary low-severity failures.

Any numeric priority is an operational heuristic unless explicitly trained and calibrated. Label it “review priority,” never “failure probability.”

## 8. What the MemoryAI inspection changes

The local project pins `hindsight-all==0.9.2`, calls `MemoryEngine` directly, uses FastAPI for its UI routes, and writes an SQLite event log. Its runtime can select extraction and consolidation models, but these selections currently resolve to Ollama or llama.cpp. [Local project definition](/Users/deepakbawa/Documents/AI/memoryai/pyproject.toml), [runtime](/Users/deepakbawa/Documents/AI/memoryai/memoryai/runtime.py:55).

Useful existing operations:

- `compare()` performs two extraction dry runs, differing in extraction instructions. It is **not** currently an arbitrary model A/B comparison.
- `recall()` builds context and exposes rank/pruning information. It does **not** generate a final answer, and the returned rank score is not a probability.
- `remember()`, `approve()`, `reject()`, `wrong()`, and `forget()` provide lifecycle actions worth testing.
- `rebuild()` replays events and attempts to reapply corrections, potentially creating new IDs and different fact wording.
- `Settings.instance` derives an embedded database instance name from `data_dir`, which helps isolate test stores.

[Extraction and recall code](/Users/deepakbawa/Documents/AI/memoryai/memoryai/memory.py:282), [rebuild code](/Users/deepakbawa/Documents/AI/memoryai/memoryai/memory.py:408), [database isolation](/Users/deepakbawa/Documents/AI/memoryai/memoryai/runtime.py:83).

Two candidate regression cases emerge directly from source inspection:

1. The small-talk rule tokenizes only `[a-z']+` and applies `all()` to those tokens. A message containing only non-Latin letters produces an empty token sequence and is classified as filler. Add a durable non-Latin fact to the first extraction suite; this observation is about the rule, not a measured full-pipeline failure.
2. The recall budget check adds recent turns only if the combined context fits. The already-built facts block and headings are not themselves reduced by that loop. Add boundary tests using the actual downstream tokenizer and include the wrapper text in the budget contract.

[Small-talk implementation](/Users/deepakbawa/Documents/AI/memoryai/memoryai/smalltalk.py), [recall budget logic](/Users/deepakbawa/Documents/AI/memoryai/memoryai/memory.py:311).

These are inspection findings, not fixes performed in this research task. The integration specification turns them into explicit scenarios. Never run the application's destructive `clear()` against the user's existing store as an evaluation reset.

## 9. Release policy and delivery sequence

An evaluation run should end in **ready**, **blocked**, or **inconclusive**, with an explanation and evidence. Missing results, unsupported capabilities, low sample sizes, or unresolved judge failures should produce “inconclusive,” not a green pass.

Example proposed gate for an initial extraction release:

- No observed violation of a designated critical invariant; show how many opportunities were tested and the remaining uncertainty.
- Candidate-minus-baseline correctness interval above the declared non-inferiority margin on the locked suite.
- Required slice coverage met; insufficiently sampled slices remain visibly unresolved.
- Probability predictions pass the agreed held-out validation procedure if the product displays them.
- Latency/cost budgets met under a declared workload and retry policy.

Define the actual thresholds from business costs and baseline data; do not borrow a library's default 0.5 or 0.7 threshold as a release standard.

### Implementation milestones

1. **Prove the measurement model:** implement scenario schema, local storage, deterministic graders, formula tests, and a recorded-output fixture adapter.
2. **Prove MemoryAI replay:** isolated stores, sequential episode actions, extraction/recall evidence, immutable run manifests.
3. **Build core UI:** scenario browser, run matrix, repeated-output detail, failure queue, review decisions, candidate comparison.
4. **Add providers:** OpenAI, Anthropic, Ollama and llama.cpp through capability-aware adapters; contract tests for raw results and errors.
5. **Add semantic grading:** one rubric, expert-labelled validation set, frozen-output regrading, then Ragas/DeepEval metrics where needed.
6. **Add probability validation:** calibration split, reliability diagram, selective prediction, drift checks.
7. **Add broader packs:** agent tools, adversarial memory, imported security suites, multimodal scenarios.

The highest-value first vertical slice is: **a durable-fact extraction case → repeated MemoryAI runs → rule and semantic evidence → baseline comparison → human triage → permanent regression case**.
