# Eval Triage — UI implementation details

Extracted from plan.md on 15 September 2026. This is a build specification. The main plan takes precedence if companion copies differ.

## 8. Complete UI specification

### Global shell

Left navigation: Overview, Scenarios, Datasets, Runs, Triage, Probability Lab, Compare, Providers, Settings. Project selector at top; service/worker health at bottom. Header shows page title, relevant dataset/run identity, and one primary action. Light and dark theme, 14–16px body type, readable line lengths, compact tables, restrained green accent. Status uses words/icons as well as color. Red means confirmed failure, amber means warning/inconclusive, grey unavailable; green never implies statistical certainty.

Desktop >=1200px: 224px navigation and flexible content. Triage columns roughly 260px queue / flexible evidence / 300px review. At 768–1199px, review becomes a tab/drawer. Below 768px, navigation collapses and queue/evidence/review become separate tabs; tables scroll within their own region and do not force page overflow. All controls keyboard-accessible, visible focus, labelled form errors, contrast WCAG AA. Charts have accessible tables and do not rely on hover alone. Persist URL filters and selected trial so evidence can be shared locally/bookmarked.

### Screen-by-screen behavior

| Screen | Main content and controls | Actions and persistence |
|---|---|---|
| Overview `/` | Recent runs, completion/error/grade coverage, active jobs, critical regressions, onboarding | Create scenario, import dataset, configure provider, load labelled demo |
| Scenarios `/scenarios` | Pack cards, contract, version, counts, grader list | Create/clone/edit-as-new-version, validate, run |
| Wizard `/scenarios/new` | Task contract → evidence type → input/episode schema → graders → invariants/slices → preview | Save version only after validation; preserve draft locally |
| Datasets `/datasets` | Immutable versions, splits, counts, tags, provenance | Import JSON/JSONL/YAML, edit draft rows, validate, publish new version, export |
| Dataset detail | Case table, expected values, evidence, cluster/split labels, coverage | Case editor with schema hints, split by cluster, duplicate detection, no in-place version mutation |
| Run setup `/runs/new` | Dataset/scenario, baseline optional, candidate required, providers, repeats, judges, limits, isolation | Capability validation, estimated calls/cost, enqueue with idempotency key |
| Runs `/runs` | Status, manifest, progress, time, target/judge errors | Filter, open, cancel, clone setup; cancelled runs remain visible |
| Results `/runs/:id` | Summary counts; matrix by case/candidate; trial strip and slices | Filter failures/flaky/changed/incomplete, open evidence, regrade, export, compare |
| Triage `/triage` | Failure queue and detailed evidence/review | Decisions, annotations, more trials, regression promotion |
| Probability `/probability` | Event selector, label/probability coverage, reliability and risk/coverage plots | Select split/calibrator, fit using allowed split, inspect bins/cases, export |
| Compare `/compare` | Paired runs, deltas/intervals, regressions, missingness, gates | Validate compatibility, create comparison, export decision evidence |
| Providers `/providers` | Adapter/config versions, endpoint/model, secret-reference status, capabilities | Add/edit-as-version, connection test, copy config; never return secret values |
| Settings `/settings` | Store path, workers, limits, redaction, plugin availability, retention | Validate paths/limits, export/import project, health diagnostics |

### Wizard based on video 2

Ask in sequence: Is there a correct answer? Is there a reference? Is there a baseline answer? Is there labelled human feedback? Otherwise define a static rubric/invariant. Use the answer to preselect graders, while allowing several evidence types together. For exact answers suggest exact/class metrics; references suggest content/claim checks; baseline suggests blinded preference; feedback suggests regression cases and held-out validation; no reference suggests rubric/safety/structure. Explain that overlap/similarity does not alone establish correctness. Do not claim the tree is a probability algorithm.

### Run setup details

Show fully resolved configurations including prompt, tools, requested parameters, memory mode, fixture, judge, and capability snapshots before Run. Repeats input integer >=1; default 5. Show planned target executions = cases × candidates × repeats, and estimated stage calls per episode separately. Judge counts depend on grader plan; estimates are labelled. Cost unknown remains text, not $0. Hard validation errors disable Run and link to the offending control. Enqueue once on double click through idempotency. Route to results immediately after job creation.

### Results matrix details

Sticky columns: case ID, severity, short input. Metric columns: baseline pass count, candidate pass count, delta, modal agreement, pairwise agreement, p50 latency, error count, review state. Each number links to its contributing trials. Distinguish raw/JSON/semantic agreement using a selector with definition displayed. A trial strip shows one tile per repeat with target and grading statuses; selecting one opens exact evidence. “More trials” creates a linked run with fresh repeats; original results stay unchanged and combined analysis explicitly states its sampling design.

### Triage detail — most important screen

Queue filters: scenario, slice, severity, confirmed/unreviewed, changed, flaky, stable-wrong, grading-error, provider-error. Default priority critical failures, regressions, then uncertain labels; sorting remains visible.

Evidence tabs: **Overview**, **Output diff**, **Trace**, **Memory state**, **Grades**, **Attempts**. Overview shows full input, expected contract, actual output, repeat counts, and source references. Diff supports raw text and parsed JSON; absent parse gets raw view plus error. Trace shows each step, tool call, elapsed time, usage, and retrieved evidence. Memory state compares before/after claims with provenance and active/historical/rejected state. Grades show rubric, version, concise evidence and judgement. Attempts expose retries, timeouts, and mutation uncertainty.

Review panel actions: `Confirm failure`, `Acceptable variation`, `Ambiguous / needs label`, `Grader incorrect`, `Request more trials`, `Promote to regression`. Persist reviewer name locally from settings; require reason for ambiguous or grader-incorrect. Reviews append and may supersede earlier reviews. Human review never silently overwrites machine grades; offer an explicit adjudicated view with provenance. Promotion requires an explicit expected contract, creates a new dataset version, and links to source run/trial/review.

Keyboard shortcuts when not typing: J/K queue navigation, Enter opens case, Escape closes drawer; all other actions retain visible buttons. Do not bind a single key to a destructive or irreversible action.

### Probability Lab details

Top selector names the event, such as “this generated answer is correct.” Cards show N predictions, N labels, coverage, Brier, clipped log loss, ECE, and calibration version. Reliability diagram uses 10 fixed equal-width bins by default, displays sample counts and empty bins, with predicted probability on X and observed positive rate on Y. Click a bin to open cases. Toggle raw/calibrated curves only when both are available.

Threshold slider 0–1 shows coverage, selective risk, accepted/review counts and held-out split label. If no accepted predictions, risk reads “Unavailable: no accepted predictions.” Repeatability tab shows output category counts, modal and pairwise agreement, entropy, pass@k/pass^k with eligible k, and per-case Wilson/Beta estimates. Bayesian intervals and frequentist intervals have distinct labels. Unsupported logprobs produce a helpful unavailable panel rather than an empty confidence gauge.

### Compare and release details

Choose baseline, candidate and matched grading versions. Show compatibility findings and case exclusions first. Display one row per metric with baseline, candidate, paired Δ, interval, units, independent cluster count, margin, and gate status. Below: improved/regressed/unchanged cases and critical slices. Final banner says Ready / Blocked / Inconclusive with exact reasons. Export includes manifest hashes and evidence links. No “deploy” button in the initial local product.

### Required UI states

Every page implements loading skeleton, truly empty state with next action, partial data state, server error with retry, disconnected progress stream with reconnection notice, and unavailable feature with reason. Preserve typed drafts during recoverable errors. Toasts summarize actions but persistent inline states carry important errors. Cancellation asks a concise confirmation because it interrupts active work, not because creating a run needs extra permission. No confirmation for ordinary saves/reviews.

