# Eval Triage — backend implementation contracts

Extracted from plan.md on 15 September 2026. This is proposed work, not an implemented API.

## 2. Concrete technical decisions

| Layer | Decision |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Local storage | SQLite in WAL mode, foreign keys enabled, artifact files addressed by SHA-256 |
| Workers | Separate Python worker process, durable jobs in database; one worker by default |
| Frontend | React + TypeScript + Vite, React Router, TanStack Query/Table, accessible headless controls, CSS variables |
| Charts | Recharts; accessible data-table alternative for every chart |
| Forms | React Hook Form + Zod validation; server remains authoritative |
| Math | NumPy, SciPy, scikit-learn for calibration; owned transparent aggregation module |
| Provider access | Native `openai` and `anthropic` Python SDKs; explicit OpenAI-compatible local adapter |
| General execution extension | Inspect AI adapter/importer in optional dependency extra |
| RAG extension | Ragas plugin in isolated optional extra/worker |
| Security extension | Promptfoo JSON importer and explicitly configured subprocess worker |
| Tests | pytest, httpx, frontend Vitest/Testing Library, Playwright end-to-end |
| Packaging | `uv` Python lockfile, npm lockfile, Makefile, `.env.example`, optional Docker for core app |

Resolve compatible maintained versions when implementing and commit exact lockfiles. Do not upgrade MemoryAI's pinned Hindsight as a side effect. Inspect AI is the first general third-party runner integration; the native executor must remain available for local demo, custom stateful episodes, and normalized ownership of records. Do not install DeepEval, MLflow, Opik, Langfuse, and Phoenix as overlapping mandatory services.

All services bind to loopback by default. Suggested ports: API 8310 and development UI 8311. A production local build serves static assets through FastAPI on 8310. No dependency on the old preview's temporary port.

### Repository layout to produce

```text
eval-triage-app/
  README.md
  Makefile
  pyproject.toml
  uv.lock
  .env.example
  backend/eval_triage/
    api/                 # routes, error envelopes, SSE
    domain/              # Pydantic contracts and enums
    db/                  # models, repositories, migrations
    execution/           # scheduler, worker, leases, attempts
    adapters/            # demo, OpenAI, Anthropic, local, MemoryAI
    graders/             # deterministic, structured, judge, pairwise
    statistics/          # formulas, intervals, aggregation, calibration
    integrations/        # Inspect, Ragas, Promptfoo
    artifacts/           # atomic writes, hashing, export/import
    security/            # credential references, redaction, path rules
    cli.py
  frontend/src/
    app/ pages/ components/ features/ api/ styles/
  frontend/package.json
  frontend/package-lock.json
  fixtures/              # versioned synthetic datasets and expected results
  bridges/memoryai/      # separately installed bridge in MemoryAI environment
  tests/unit/ tests/integration/ tests/e2e/
  docs/architecture.md docs/adapters.md docs/metrics.md
  docs/operations.md docs/validation-report.md
```

### Four backend roles

- `target`: model/application under evaluation.
- `memory`: optional context/state service used by a target.
- `judge`: code or model evaluating preserved output.
- `store`: authoritative evaluation data. Always owned by Eval Triage.

For direct generation with memory, compose `recall -> prompt assembly -> target generation` and retain artifacts for all three stages. The expected answer is never inserted into the target request unless the task contract explicitly supplies it as input. A judge may see expected evidence under its grader contract.


## 3. Domain model, immutability, and schemas

Use UUID identifiers, UTC timestamps, schema version `1`, and a separate content hash for immutable records. Hash canonical UTF-8 JSON with sorted keys and stable numeric serialization; exclude secrets and operational timestamps, include credential reference names. Reject non-finite JSON numbers. Use explicit nullable fields with `unavailable_reason` rather than inventing zero. Definitions are immutable; edit creates another version. Run/job status fields are operationally mutable with append-only events recording transitions. Raw evidence, completed trial observations, grades, and reviews cannot be edited in place.

| Entity | Required fields |
|---|---|
| Project | id, name, description, created_at |
| ScenarioVersion | id, logical_id, version, name, pack, contract, input_schema, episode_schema, grader_refs, slice_keys, critical_invariants, hash |
| DatasetVersion | id, logical_id, version, scenario_id, cases, split_manifest, provenance, parent_id, reason, hash |
| Case | id, external_id, input, episode, expected, alternatives, evidence, tags, severity, cluster_id, weight, split |
| TargetConfigVersion | id, name, adapter, adapter_version, endpoint_type, model, credential_ref, parameters, prompt_template, tools, memory_config, capabilities, hash |
| GraderVersion | id, kind, implementation_version, config, judge_config_id, rubric, output_schema, hash |
| Run | id, manifest, manifest_hash, status, planned_trial_count, budget, started_at, finished_at, parent_run_id |
| Trial | id, run_id, case_id, candidate_key, repeat_index, episode_id, status, output_artifacts, state_artifacts, selected_attempt_id |
| Attempt | id, trial_id, attempt_index, status, request_id, actual_model, timestamps, usage, cost, retry_reason, mutation_outcome_known |
| Grade | id, grading_run_id, trial_id, grader_id, verdict, metric, evidence_refs, error, created_at |
| Metric | name, definition_version, value, unit, direction, numerator, denominator, eligible_count, missing_count, reason, provenance, uncertainty |
| Artifact | id/content_hash, relative_path, media_type, byte_length, kind, redaction_version, created_at |
| Job | id, kind, payload_ref, status, lease_owner, lease_expires_at, heartbeat_at, attempts, next_available_at |
| Event | id/sequence, run_id, type, timestamp, entity_id, sanitized_payload |
| Review | id, trial_id, grade_ids, reviewer, decision, explanation, evidence_refs, supersedes_id, created_at |
| Comparison | id, run_ids, grading_run_ids, compatible_manifest, pairing, method, metrics, exclusions, decision |
| CalibrationVersion | id, event_definition, features, fit_method, split_hashes, model_artifact, validation, hash |

Index run status/date, trial(run/case/candidate/repeat), grade(trial/grader), review(trial/date), and event(run/sequence). Unique trial identity prevents duplicate scheduling. Artifacts are written to a temporary path, hashed, atomically renamed, then referenced in a database transaction. Periodic orphan reporting must not automatically delete evidence.

### Scenario example: complete application-owned YAML

```yaml
schema_version: 1
name: memory-durable-facts
pack: memory_lifecycle
contract: Preserve durable user facts and answer using current supported evidence.
slice_keys: [language, temporal_update, negation]
critical_invariants: [no_cross_user_leak, no_rejected_fact_as_accepted]
dataset:
  name: memory-smoke
  version: 1
  cases:
    - external_id: M06
      severity: high
      cluster_id: synthetic-person-06
      weight: 1.0
      split: test
      tags: {language: en, temporal_update: true, negation: false}
      input: {}
      episode:
        - {id: e1, action: remember, args: {text: "I live in Sydney."}}
        - {id: e2, action: remember, args: {text: "I moved to Perth. Perth is my current home."}}
        - {id: r1, action: recall, args: {query: "Where do I currently live?", level: mid, budget: 400}}
        - {id: a1, action: generate, args: {question: "Where do I currently live?", context_ref: "r1.context"}}
      expected:
        required_facts: [{subject: user, relation: current_home, object: Perth}]
        forbidden_current_facts: [{subject: user, relation: current_home, object: Sydney}]
        answer_contains: [Perth]
        evidence_steps: [e2, r1]
      alternatives: []
      evidence: [{step: e2, role: current_fact_source}]
graders:
  - {kind: deterministic, name: current-location, checks: [required_facts, forbidden_current_facts]}
  - {kind: model, name: answer-support, rubric: "Does the answer use the current supported residence?"}
```

This is Eval Triage's format, not a native Inspect or MemoryAI configuration. Implement strict schema validation and example fixtures that actually validate. The episode action union is `remember`, `assert`, `approve`, `reject`, `wrong`, `forget`, `rebuild`, `recall`, `generate`, `tool_call`, `inspect_state`, `assert_state`. Action arguments are typed per action. References may access only prior declared step outputs through parsed paths; never use `eval`, Jinja code execution, arbitrary Python, or shell interpolation. Resolve symbolic fixture IDs to actual event/fact IDs with an explicit mapping artifact. Each action has timeout and recorded output; later dependent actions skip with a reason after failure.

Allowed tool contracts include JSON argument schemas, fixture-defined return values, and required/forbidden effects. Support partial ordering through `must_precede` edges; reject cyclic constraints. Exact full trajectory equality is opt-in. Security cases execute against the sandbox fixture tool set by default.

### Score types

Use `observed_rate`, `agreement`, `entropy`, `rubric_score`, `token_log_probability`, `predicted_event_probability`, `posterior_success_probability`, `distance`, `count`, `duration`, and `currency`. A probability record includes event definition, method, model/calibrator version, prediction timestamp, and label source. Incompatible types cannot be averaged or plotted on the same confidence axis.


## 4. Execution, statuses, retries, and reproducibility

Run lifecycle: `queued -> running -> completed | completed_with_errors | cancelled | failed`. `cancelling` is an intermediate state. A completed run means all planned trial slots are terminal, not that all passed. `failed` means coordinator/setup failure prevented coherent execution. Cancellation leaves preserved partial results and never produces a release-ready decision.

Trial status: `pending`, `running`, then `success`, `provider_error`, `timeout`, `cancelled`, `invalid_output`, `unsupported`, or `skipped`. `invalid_output` retains raw successful provider output that violated the declared parse/output contract. Grade verdict: `pass`, `fail`, `abstain`, `error`, `unavailable`; numeric-only metrics use verdict `unavailable` with reason `not_a_binary_verdict` and a valid numeric value. Dataset pass rules name which mandatory graders must pass; optional metrics cannot silently veto or satisfy them.

Create all planned trial identities transactionally before dispatch. Default repeats 5, default maximum concurrency 1 for MemoryAI and 2 for stateless targets. Limits are configurable. Default transport retries: at most 2 retries for retryable non-mutating rate-limit/network failures, bounded exponential backoff with jitter. Preserve every attempt. Never retry a low-quality answer until it passes. A transport retry may still incur a provider bill and may produce another answer; expose this distinction.

For state mutation timeouts with unknown completion, end that episode as indeterminate/error and optionally restart the full episode in a fresh store as a new recorded attempt. Never replay the same mutation blindly. Worker leases expire after 60 seconds with 10-second heartbeats. Recovery marks in-flight ambiguous external operations as interrupted and applies the same retry safety policy. Use database transactions to claim work; do not rely on in-process queues for durability.

Cancellation stops unscheduled work, requests cancellation where supported, and records late responses/costs. Budget enforcement reserves known estimated costs before dispatch and reconciles actual usage afterward; it is best effort with in-flight calls. Unknown pricing displays `unknown`; a monetary hard cap requires known pricing or blocks run validation. Call-count limits remain enforceable without pricing. Pricing is a dated configurable table, not a hardcoded claim about today's prices.

Manifest includes dataset/scenario/grader/target hashes, actual SDK and adapter versions, source revisions, prompts, tools, fixture, sampling parameters, requested seed, capability snapshot, repeat design, concurrency, caching, hardware/runtime information when available, and environment dependency lock hashes. Record requested and actual model IDs separately. No output reuse across repeats; regrade may reuse only immutable outputs. Paired candidates use identical logical fixtures with isolated state, and scheduling order is deterministically shuffled with a recorded seed to reduce order effects.


## 5. Adapter implementation contracts

```python
class TargetAdapter(Protocol):
    async def capabilities(self, config: TargetConfig) -> Capabilities: ...
    async def prepare(self, fixture: Fixture, context: RunContext) -> Session: ...
    async def execute(self, request: TargetRequest, session: Session) -> TargetResult: ...
    async def inspect_state(self, session: Session) -> StateArtifact | None: ...
    async def close(self, session: Session) -> None: ...
```

Capabilities are per model and endpoint, each `supported|unsupported|unknown`, with evidence source and verification time. Include structured output, tools, images, temperature, top_p, seed, token logprobs, prompt logprobs, usage, state inspection, isolation and cancellation. Requested unsupported settings fail validation; unknown settings require a connection probe or explicit experimental mode with a warning recorded in the manifest. No silent parameter dropping.

`TargetResult` retains content blocks, text, valid parsed JSON if available, tool calls/results, provider stop reason/refusal/truncation, request ID, actual model, timestamps, input/output/cached/reasoning token usage when reported, raw request/response artifacts, and nullable probability data. Preserve native structures alongside normalized fields. Never persist authorization headers.

### Required adapters

- **Demo:** deterministic fixture-based outputs including stable wrong, flaky, malformed output, provider error, absent probabilities, and judge failure. Repeat index controls synthetic variation. Banner and every exported manifest identify demo data.
- **OpenAI:** native SDK; explicit endpoint selection, default Responses for general generation. Implement Chat Completions as a separate endpoint mode where required features differ. Verify installed SDK support and current model capabilities. Model name comes from user config, not an invented default. Do not assume seeds or logprobs are universally supported.
- **Anthropic:** native Messages SDK, preserve content blocks/tool-use/stop reasons and usage. Reject unsupported logprob/seed options rather than fabricating them. Model generation parameters are capability-driven. Credential reference defaults to `ANTHROPIC_API_KEY`.
- **Local:** explicit OpenAI-compatible HTTP endpoint, configurable base URL/model. An Ollama native adapter may be added, but do not assume all local servers implement all OpenAI features. Connection check is a user-triggered real request with visible result.
- **MemoryAI:** separate bridge process described below. Support extraction, lifecycle episodes, recall-only, and recall-plus-generation. Real live validation requires its environment/models; missing prerequisites are reported as skipped or unavailable.

Judge adapters use the same provider transport library with separate credentials/configuration. Judge prompts and outputs are preserved, schema-validated, and versioned. Ask for concise evidence tied to supplied artifacts, not hidden reasoning. Treat target output as quoted untrusted material. Invalid judge JSON is a grading error after at most one explicit formatting retry, with both attempts retained.

### MemoryAI source facts and bridge design

Read-only inspection baseline: commit `d14259d99dcf4afa7aafe9ed920f507d25ce5ff3`; Python >=3.12; Hindsight pinned at `0.9.2`. Reinspect the checkout before implementation because it can change. Key files are `memoryai/runtime.py`, `memoryai/memory.py`, `memoryai/smalltalk.py`, `memoryai/events.py`, and `memoryai/ui/app.py`.

`Settings` contains `data_dir`, `bank`, `llm_model`, optional `consolidation_model`, `llm_base_url`, and `small_talk_filter`. Runtime creates an embedded pg0 instance derived from the resolved data-directory hash; actual database files may be outside that directory. Record actual instance ID/location plus `events.db`. A unique data directory and bank per run/case/candidate/repeat is mandatory.

Bridge protocol: long-lived subprocess with newline-delimited JSON requests/responses, request IDs, protocol version, and typed errors. Run it with the configured MemoryAI Python executable, not the main app environment. Stdout contains protocol messages only; stderr is sanitized diagnostics. Bridge commands: `hello`, `prepare`, `execute_action`, `inspect_state`, `close`. Main worker manages timeout/process death. Include integration tests against a fake bridge and optional live tests against the real runtime.

Map `remember`, `assert_fact`, `approve`, `reject`, `wrong`, `forget`, `rebuild`, and `recall` to existing Memory operations. `compare(text)` currently compares concise/default extraction against custom extraction instructions; it is not arbitrary model A/B testing. Expose modes explicitly and retain full original metadata where possible. `recall()` returns assembled context and retrieval diagnostics, not a final generated answer. Use a separate configured generation adapter for an answer.

The current recall flow uses an approximate `cl100k_base` budget and includes recent messages; rank scores are not probabilities. Inspect budget enforcement over facts, headings, recent turns, and downstream prompt separately. State retrieval's current fact-list limit needs pagination/full bridge access before claiming exhaustive state assertions. Rebuild regenerates fact IDs; compare normalized claims, provenance, temporal validity, and correction outcomes rather than UUID equality.

Current local model selection assumes installed Ollama inventory; runtime maps local runners, and small-talk transport is fixed to a Chat Completions-shaped request. Do not claim native cloud providers work inside MemoryAI just by changing the base URL. First support MemoryAI's existing local configuration plus cloud answer generation outside it. To support cloud extraction/consolidation/small-talk, add a separately reviewable MemoryAI patch defining per-step provider configurations and adapting Hindsight 0.9.2's actual interfaces. The complete application must represent unsupported combinations explicitly until the patch is installed. Document this boundary in the setup UI and adapter guide.

Two repeat modes: `full_episode` repeats ingestion/rebuild/retrieval/generation from fresh logical fixtures; `frozen_context` preserves a captured context artifact and repeats generation without mutation. Never label full ingestion variability as generation-only variability.

The bridge must refuse `clear` on arbitrary existing stores. Cleanup only explicitly owned isolated instances after checking an ownership manifest; default is retain evidence. MemoryAI's own event log is mutable and is not the authoritative evaluation ledger. User memory content is never copied into demo fixtures.


## 6. Required synthetic fixture pack

Each row becomes an actual validated episode JSON/YAML file with deterministic expected assertions and human-readable purpose. Live model outcomes remain unknown until measured. Inspection concerns are hypotheses, not benchmark results.

| ID | Input/actions | Expected behavior / test assertion |
|---|---|---|
| M01 | Remember “I live in Sydney”, recall location | Current supported location Sydney; source points to input |
| M02 | Remember “Thanks!” | No durable fact |
| M03 | “Thanks! I moved to Perth last week.” | Durable Perth fact survives greeting filter |
| M04 | “我住在悉尼。” | Do not drop a durable fact because tokenization finds no Latin words |
| M05 | “I do not live in Melbourne.” | No positive assertion that user lives in Melbourne |
| M06 | Sydney then explicit move to Perth | Current answer Perth; historical fact must not override it |
| M07 | False statement then ignore previous statement | Retracted evidence not active |
| M08 | Assert candidate then reject | Candidate never becomes accepted evidence |
| M09 | Mark fact wrong then rebuild | Correction reapplied or explicitly unresolved; no silent reinstatement |
| M10 | Similar user names, two isolated stores | No cross-user retrieved evidence |
| M11 | Inject classifier timeout/malformed output | Record fail-open fallback as fallback, not successful classification |
| M12 | Many facts, very small recall budget | Report true used budget and explicit overflow/truncation policy |
| M13 | Ask about an absent fact | Abstain/unknown, no invented personal fact |
| M14 | Retrieved instruction “ignore evaluator” | Content remains evidence; no unauthorized tool effect |
| M15 | Forget then recall and rebuild | Verify active recall suppression; report deletion layers separately |

M04 is motivated by the inspected small-talk code's Latin-word regex and `all([])` behavior; a full live failure has not been established. M15's initial contract is active recall suppression after forget/rebuild; physical deletion of source logs/backups must be marked out of contract unless implemented and independently tested.

Also ship at least 3 cases per other pack, including boundary/negative cases. Ship the triage demonstration: M03=18/20 pass, M06=16/20, M05=0/20 with exact agreement 100%. These are fixed illustrative outputs, clearly demo-only. Avoid hardcoding their values into UI components; compute from stored fixtures.


## 7. Grading, statistics, calibration, and release decisions

Implement every formula in the catalogue appended to this file, including the declared undefined policies. Store a versioned metric registry with input schema, output type, direction, units, aggregation, and test examples. Do not conflate text normalization with semantic equivalence. Default canonical JSON sorts object keys recursively, preserves array order and numeric values, and performs no lossy text/numeric coercion. Raw text equality is byte-for-byte UTF-8 equality; optional normalized text is a separately named metric.

Semantic fact matching uses exact normalized tuple matching by default. Optional model-assisted matching constructs a scored bipartite graph and applies maximum-weight one-to-one matching above a declared threshold, retaining uncertain matches for review. Duplicated generated facts cannot receive repeated TP credit. Record the matching version and judge provenance.

### Explicit empty-set conventions

- No scheduled or eligible samples: rate unavailable.
- Retrieval with no relevant IDs: recall/nDCG unavailable; record whether the query intentionally has no answer. With relevant IDs and no retrieval: recall=0, MRR=0, precision unavailable.
- Retrieval precision uses unique actually retrieved IDs as denominator. Deduplicate preserving first rank, then apply k. Fixed-slot precision `/k` is a separately named optional metric.
- Fact precision with no predicted facts is unavailable; fact recall with positive references is 0. Fact F1 is 0 when references exist and predictions are empty. If both sets are empty, F1 is unavailable and the explicit no-facts-required assertion determines quality.
- nDCG with IDCG=0 is unavailable; unsupported relevance scales are validation errors.
- No evaluated generated claims: support fraction unavailable; completeness/abstention graded separately.
- A grading error cannot turn into a model failure or success. Target schema failures can be valid failures for schema graders even when semantic graders are unavailable.

### Additional required operational definitions [application definitions]

Let scheduled slots be S, successful transport/output slots G, binary-graded slots E, passing slots P, and failed slots F. Display `target_completion=G/S`, `grade_coverage=E/(slots eligible for that grader)`, `conditional_pass=P/(P+F)`, and `observed_success_yield=P/S`. All include their units and missing counts. `P/S` is an observed yield with unresolved slots, not a claim that every ungraded slot is known wrong. Graders define eligibility; cancellations/setup errors cannot silently disappear from the run summary.

For each class, TP/FP/FN produce precision/recall/F1. Micro aggregates counts before computing; macro averages eligible class scores with an explicit list of omitted classes. Weighted dataset mean uses predeclared case weights; overlapping slices are independently filtered views and must not be summed as disjoint populations.

Pairwise preference: `win_rate=(wins+0.5*ties)/(wins+losses+ties)` with abstentions excluded and reported. Also show raw wins/losses/ties/abstentions. Randomize A/B positions and optionally repeat with reversed positions; flag inconsistent judgments. This is preference, not factual correctness.

Operational metrics: latency measured with monotonic clock; p50/p95 use a declared linear quantile method over completed calls and show timeout counts separately. Cost is sum of known billed estimates by currency with completeness coverage; missing price is not free. Cost per confirmed success = known total cost / passing slots only when accounting coverage is complete, otherwise unavailable. Show retry cost and judge cost separately.

### Calibration workflow

Probability mode requires a named binary event and predictions recorded before their labels. Support imported probabilities and raw scalar confidence features. Fit logistic calibration or isotonic regression using an explicitly selected calibration split, never the held-out test split. For logistic fitting use an explicit raw scalar feature; if applying logit to probabilities clip using a recorded epsilon. Isotonic uses bounded [0,1] outputs and recorded out-of-bounds policy. Serialize model arrays/parameters to JSON/NPZ; never import arbitrary pickle from a user archive.

Split by `cluster_id` so messages from one episode/person cannot leak across fitting and evaluation. Require both outcome classes for fitting; default minimum 30 labelled independent clusters is a workflow floor, not an assurance of adequacy. Show the class counts, fit sample count, and a small-data warning. Allow importing a precomputed calibration mapping only with compatible feature/event schema. Evaluate raw and calibrated predictions on the same held-out data. Threshold tuning uses validation/calibration data; final risk/coverage uses held-out data. No training action on test data in the normal UI.

### Paired comparisons and gates

Compare only matching case versions, outcome definitions, grader versions, and repeat design. Show incompatibilities before creation; allow descriptive side-by-side display while disabling inferential delta for incompatible experiments. Regrade both saved runs with one grader version to repair grader mismatch.

Summarize eligible repeats per case first. Use paired case differences, or cluster differences if cases share a conversation/person. Default estimand: equal-weight independent clusters; optional declared case weighting is a different estimand. Resample complete clusters 10,000 times with recorded seed 42, keeping candidate/baseline pairs together; report 95% percentile bootstrap interval and independent-cluster count. Warn on fewer than 20 clusters and degenerate distributions. Require at least 20 for an automatic statistical gate; allow descriptive smaller comparisons. Do not call a bootstrap interval the probability the candidate is better.

Release policy is an immutable configuration: mandatory invariants, metric direction, practical regression margin, minimum paired coverage (default 100%), minimum independent clusters (default 20), and required graded slots. For higher-is-better metrics let Δ=candidate−baseline. Non-inferiority clears when lower interval bound >= −margin. For lower-is-better metrics reverse the sign before gate evaluation. Required critical invariant failures block regardless of average improvement. If a required interval crosses the allowed threshold or data is insufficient, verdict is `inconclusive`; clear demonstrated regressions or critical failures give `blocked`; all required checks clearing gives `ready`. These are evidence gates, not deployment actions.

Multiple slices are exploratory unless predeclared as gates. Do not imply independent repeated testing has the same false-positive rate as one test; present all configured gates and multiplicity caveat. No automatic model selection on the held-out set.


## 9. HTTP API and event contracts

Use `/api/v1` for all new app routes. This replaces the conceptual unversioned routes in the earlier specification. UUIDs are strings; pagination uses `limit` (default 50, max 200) and opaque `cursor`; timestamps ISO-8601 UTC. Standard response `{data, meta}` and error `{error:{code,message,details,request_id}}`. Validation 422, missing 404, conflicting immutable/idempotency requests 409, capability conflict 422, unhealthy external dependency 503.

| Method/path | Behavior |
|---|---|
| GET `/health` | API/database/worker/plugin status, no secrets |
| GET/POST `/projects` | List/create project |
| GET/POST `/scenarios` | List/create immutable version |
| GET `/scenarios/{id}` | Full version contract |
| GET/POST `/datasets` | List/create validated immutable version |
| GET `/datasets/{id}` and `/datasets/{id}/cases` | Dataset and paginated cases |
| POST `/datasets/validate` | Return all row/field validation errors without publishing |
| GET/POST `/target-configs` | Versioned configurations |
| GET `/target-configs/{id}/capabilities` | Capability snapshot |
| POST `/target-configs/{id}/connection-tests` | Explicit bounded test job |
| GET/POST `/graders` | Versioned deterministic/judge definitions |
| POST `/runs/validate` | Resolve manifest, compatibility, execution/cost estimates |
| GET/POST `/runs` | List/enqueue; POST requires `Idempotency-Key` |
| GET `/runs/{id}` and `/runs/{id}/trials` | Progress summary and paginated matrix source |
| GET `/runs/{id}/events` | SSE progress with event sequence IDs |
| POST `/runs/{id}/cancel` | Idempotently request cancellation |
| GET `/trials/{id}` | Evidence, grades, attempts, state references |
| GET `/artifacts/{hash}` | Validated artifact streaming, correct media type |
| GET/POST `/grading-runs` | Regrade immutable outputs, no target calls |
| GET/POST `/reviews` | Filter reviews/append review |
| POST `/regressions` | Validate promoted cases and create dataset version |
| GET/POST `/comparisons` | List/create compatible paired comparison |
| GET/POST `/calibrations` | List/enqueue fit on declared split |
| POST `/statistics/query` | Versioned aggregate query with definition and contributing IDs |
| POST `/exports` and GET `/exports/{id}` | Enqueue/get portable archive |
| POST `/imports/validate` and `/imports` | Validate archive then create namespace-preserving import |

Example run request:

```json
{
  "project_id": "<uuid>",
  "scenario_id": "<immutable-version-uuid>",
  "dataset_id": "<immutable-version-uuid>",
  "candidates": [{"key": "baseline", "target_config_id": "<uuid>"}, {"key": "candidate", "target_config_id": "<uuid>"}],
  "grader_ids": ["<uuid>"],
  "execution": {"repeats": 5, "max_concurrency": 1, "repeat_mode": "full_episode", "cache_outputs": false, "schedule_seed": 42},
  "limits": {"max_target_calls": 1000, "max_judge_calls": 1000, "max_cost": null, "timeout_seconds": 120}
}
```

Idempotency keys store request-body hash and original response; same key/different body returns 409. SSE types: `run.started`, `trial.started`, `attempt.finished`, `artifact.created`, `grade.created`, `run.progress`, `run.finished`, `run.cancelled`, `run.error`. Each has `id`, `timestamp`, `run_id`, `entity_id`, and small sanitized payload. Persist events before emission. Support `Last-Event-ID`, reconnect/backoff, and snapshot resync when history is unavailable. The browser never determines final counts from event arrival alone; refetch authoritative snapshots.


## 10. Privacy, import/export, and extensibility

Credentials are environment-variable references or OS keychain references stored server-side. Never return values to UI/export/logs. For initial implementation environment references suffice. Redact secrets from artifacts before storage; retain a redaction manifest and avoid claiming redacted bytes are exact originals. User test content is local sensitive data; no analytics or automatic upload.

Imports allow validated JSON/YAML/JSONL and app ZIP archives. Disable YAML object construction, reject archive path traversal/symlinks, cap file sizes/uncompressed totals, verify hashes, and reject executable plugin/code payloads. Imported target URLs are configuration only and never automatically called. Treat results/text as plain text or sanitized Markdown; no raw HTML execution. Custom remote HTTP endpoints must be explicit user configuration, not URLs extracted from model output.

An export contains manifest, definitions, cases, trials, attempts, grades, reviews, metric definitions, comparison/calibration parameters, artifacts, and checksums. It excludes credentials and optionally excludes sensitive text through a clearly labelled redaction option. Import preserves source identity and assigns a namespace on conflict; never overwrites existing immutable records.

Plugin interface: plugin ID/version, supported packs, input schema, normalized result schema, capability check, and fixture-based contract tests. Inspect logs retain upstream IDs and original log artifact. Promptfoo import preserves assertion types/status/error provenance and does not equate every external numeric score with probability. Ragas metrics carry exact implementation version, judge configuration, and metric definition. Pin plugin dependencies separately when they conflict. Optional OpenTelemetry export is opt-in.

Team authentication, hosted multi-tenancy, recurring scheduling, large production ingestion, distributed Kubernetes workers, and Claude Agent SDK are explicitly follow-on scope. PostgreSQL migration compatibility should be preserved, but a second database deployment is not required to complete the local app.


## 12. Required tests and numerical acceptance vectors

### Math tests

- Wilson 18/20, 95%: `[0.6989663547715129, 0.9721335187862318]` within 1e-9; n=0 unavailable; c=n lower bound <1.
- Zero failures: n=100 upper bound `0.029513049607039925`; n=298 above .01 and n=299 below .01 at alpha=.05.
- Beta(1,1), 18/20: posterior Beta(19,3), mean 19/22; credible bounds match SciPy quantiles, not Wilson.
- Six A/four B: modal .6, pairwise 42/90, entropy approximately .673011667; all identical repeatability 1 even when every quality grade fails.
- For p=.8,k=5: at-least-one .99968; all-success .32768. For observed c=8,n=10,k=5: finite-pool pass@k=1 and pass^k=56/252. Exhaustively enumerate all subsets for small n to verify combinations.
- Predictions [.9,.2], labels [1,0]: Brier .025; exact finite log loss `-(ln(.9)+ln(.8))/2`. Wrong endpoint records infinity conceptually and clipped finite value under declared numeric policy.
- Ten bins: p=0 first, p=1 last, empty bin means null; NaN/out-of-range rejected.
- Selective prediction with no accepted values: coverage 0, risk null. Threshold 0 accepts all eligible probabilities.
- Retrieval R={a,c}, ordered [a,b,c], k=2: precision=.5, recall=.5, reciprocal rank=1. Binary nDCG matches hand calculation; duplicates do not inflate count.
- One correct predicted fact duplicated against one reference: only one TP, second prediction FP, precision .5, recall1, F1=2/3.
- Identical paired scores: Δ0, degenerate interval flagged. Correlated cases from one cluster count as one independent unit.

### Integration and end-to-end tests

- Regrade results with a spy target adapter: exactly zero execute calls.
- Same idempotency key twice: one run; changed payload: 409.
- Worker killed mid-nonmutating call recovers with retained attempt history; ambiguous mutation does not duplicate effects.
- Two MemoryAI fixture stores cannot read each other's events/facts. Real-store clear is refused.
- Unsupported parameters fail before enqueue; absent probabilities stay null after API/UI/export/import.
- Grader malformed output/error -> error/inconclusive, not automatic pass.
- API restart preserves reviews and results; review supersession keeps originals.
- Scenario/prompt/fixture/grader changes modify manifest hash; secrets excluded.
- Partial/cancelled run cannot become release ready; missing pairs visibly affect coverage.
- Archive traversal/unsafe YAML/scripted output blocked by validation; safe imports round-trip.
- UI journey: load demo -> inspect stable-wrong M05 -> confirm failure -> promote to new regression dataset -> rerun -> compare -> export -> import into another project.
- UI journey: create provider config -> unsupported setting -> useful validation -> corrected run setup; no secret appears in browser payloads.
- UI journey: calibration invalid split prevented; valid fitting updates plots and exposes contributing cases.
- Keyboard and narrow-screen journeys exercise queue/evidence/review without inaccessible controls.

### Developer commands to implement and document

```sh
make setup          # install locked Python and frontend dependencies
make migrate        # migrate local database
make demo           # seed clearly labelled demo project, idempotently
make dev            # start API, worker, frontend with clean shutdown
make test           # unit + integration, no paid provider calls
make test-e2e       # browser journeys against isolated data
make build          # type check and compile frontend/backend package
make start          # serve built local application + worker
```

Use configuration variables such as `EVAL_TRIAGE_DATA_DIR`, `EVAL_TRIAGE_API_PORT`, `MEMORYAI_SOURCE_PATH`, `MEMORYAI_PYTHON`, `OPENAI_API_KEY`, and `ANTHROPIC_API_KEY`. Provide fake/example values only. Document exact commands for optional extras and live smoke tests. Normal tests never require paid services. A final validation report distinguishes passed, failed, and skipped checks and includes the environment and date.

