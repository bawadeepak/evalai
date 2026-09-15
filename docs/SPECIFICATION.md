# Eval Triage — implementation specification

Status: proposed design, grounded in the inspected MemoryAI source. This document defines work to build; it does not imply that the adapters or UI service already exist.

## 1. Product contract

Eval Triage evaluates systems, compares versions, and helps a person investigate failures. It must support both stateless LLM calls and stateful episodes. The same test specification should run against MemoryAI, a direct provider SDK, or a custom application target, subject to capability validation.

Users should be able to:

1. Select a scenario and dataset version.
2. Choose baseline and candidate target configurations.
3. Select repeat policy and graders.
4. See the expected number of executions and estimated cost before starting.
5. Watch completed, failed, cancelled, and ungraded work separately.
6. Inspect raw input, output, trace, state changes, and grading evidence.
7. Review disagreements and turn confirmed failures into regression cases.
8. Compare correctness, repeatability, probability quality, and efficiency separately.

The initial user is a developer/researcher working locally. Team access controls, scheduling, and production ingestion follow after reproducibility is proven.

## 2. Architecture

```mermaid
flowchart TD
    UI[Eval Triage UI] --> API[Evaluation API]
    API --> DB[Cases, runs, scores, reviews]
    API --> JOB[Run coordinator]
    JOB --> RUN[Runner adapter: native or Inspect]
    RUN --> TARGET[Target adapter]
    TARGET --> MEM[MemoryAI episode adapter]
    TARGET --> OA[OpenAI SDK]
    TARGET --> CL[Anthropic SDK]
    TARGET --> LOC[Local model or custom endpoint]
    MEM --> HS[Isolated Hindsight store and event log]
    RUN --> RAW[Immutable outputs, traces, manifests]
    RAW --> GRADE[Deterministic checks and model graders]
    GRADE --> STATS[Statistics and comparison]
    STATS --> DB
    RAW --> DB
    DB --> REVIEW[Human review and adjudication]
    REVIEW --> DB
```

### Components to build

| Component | Responsibilities | Explicit boundary |
|---|---|---|
| UI | Scenario editor, run matrix, evidence, review, comparisons | Never contains provider credentials |
| API service | Validates requests, stores immutable definitions, authorizes actions | Does not perform long inference inside request handlers |
| Coordinator | Jobs, limits, retries, cancellation, crash recovery | Retries preserve an attempt history |
| Runner interface | Execute cases/episodes and emit standardized events | Inspect is an implementation, not the product schema |
| Target interface | Execute application/model under test | No access to expected answers unless task genuinely requires them |
| Grader interface | Evaluate saved results | Cannot rewrite results or mutate target state |
| Statistics | Aggregate by case/slice/episode; intervals and comparisons | Enforces denominators and missing-data policy |
| Review | Labels, evidence, adjudication, promotion to dataset | Every change appends a versioned record |

Recommended first service is FastAPI with Python 3.12, matching MemoryAI. Use a separate package and environment to contain Hindsight's pinned dependency. React/TypeScript is a reasonable UI choice for the run matrix and evidence views; a lighter frontend is also viable. These are implementation choices, not dependencies required by the research.

## 3. Four different meanings of “backend”

Keep these configuration concepts separate:

1. **Target backend:** the system being tested: MemoryAI, OpenAI, Claude, local model, or application endpoint.
2. **Memory backend:** optional memory service used by a target. MemoryAI can fill this role.
3. **Judge backend:** model or code used to assess output. This can differ from the target provider.
4. **Evaluation store:** authoritative cases, raw results, scores and human reviews.

Testing a direct SDK without memory must remain possible. Testing an SDK with MemoryAI context must be a separate experiment identity. Switching the judge must not silently create the appearance of a target-model improvement.

### Target adapter contract

Conceptual interface:

```python
class TargetAdapter:
    async def capabilities(self) -> Capabilities: ...
    async def prepare(self, fixture, run_context) -> Session: ...
    async def execute(self, request, session) -> TargetResult: ...
    async def inspect_state(self, session) -> StateArtifact: ...
    async def close(self, session) -> None: ...
```

`TargetResult` includes output blocks, parsed output if valid, tool events, actual model identifier, request ID, usage, elapsed time, stop reason, attempt ID, provider metadata, and raw artifact references. Use explicit statuses: `success`, `provider_error`, `timeout`, `cancelled`, `invalid_output`, and `unsupported`.

Capabilities should be model-and-endpoint specific: structured output, tools, images, sampling parameters, seed, token logprobs, prompt logprobs, usage reporting, state inspection, and reset/snapshot method. Include `supported`, `unsupported`, or `unknown`, source of the claim, and verification time. Do not discover every capability by making an expensive request; combine official documentation with a targeted connection test when the user runs the adapter.

**Required rule:** unsupported requested parameters produce a configuration error or explicit user-selected omission, never silent dropping. Missing probabilities are `null` with a reason, never zero. The OpenAI and Anthropic APIs expose different request/output structures; native adapters should preserve that information. [OpenAI reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python).

If “Claude SDK” means the Claude Agent SDK rather than the Anthropic API SDK, expose it as a separate agent target with its own execution environment, tool permissions, and accounting. Do not treat a tool-using agent SDK as a synonym for a text-generation client.

### Example configuration — proposed schema

```yaml
schema_version: 1
name: durable-facts-v1
dataset: {id: durable-facts, version: "1"}
target:
  adapter: memoryai
  source_path: /Users/deepakbawa/Documents/AI/memoryai
  config_ref: memoryai-baseline-v1
  isolation: new_store_per_episode_repeat
candidate:
  adapter: memoryai
  config_ref: memoryai-candidate-v1
runner: {adapter: inspect, max_concurrency: 1}
trials:
  repeats: 5
  cache_outputs: false
  retry_policy: no_quality_retries
graders:
  - {id: schema-valid, version: "1", kind: deterministic}
  - {id: durable-fact-match, version: "1", kind: structured_match}
  - {id: source-support, version: "1", kind: model, judge_ref: local-judge-v1}
aggregation:
  unit: episode
  slices: [language, negation, temporal_update]
  missing_grade_policy: inconclusive
```

This is an application-owned configuration, not a file that current Inspect or MemoryAI will accept directly. The runner adapter translates it. Provider configuration records separately reference an exact model and an environment-variable credential name; secret values never enter exported YAML.

## 4. MemoryAI integration plan

### Inspected mapping

| Need | Existing hook | Integration work |
|---|---|---|
| Dry-run extraction | `Memory.compare()` | Expose each configured mode separately with full original fact metadata |
| Store a message | `Memory.remember()` | Record event ID, resulting facts, small-talk verdict and timing |
| Review candidate fact | `assert_fact`, `approve`, `reject` | Resolve symbolic fixture IDs to newly created event IDs |
| Invalidate fact | `wrong(memory_id)` | Match fixture claim/provenance to actual ID and persist both |
| Retrieval evidence | `recall()` | Export hit IDs, rank components, provenance and state, not just rendered context |
| Answer with memory | `recall()` returns context only | Add a separate answer-generation step through a model adapter |
| Replay | `rebuild()` | Record old/new IDs and unresolved corrections; compare semantic state |
| Empty test store | `Settings(data_dir=...)` | Unique directory and bank per isolated episode/repeat |
| Cloud provider within MemoryAI | Runtime resolves local runners | Extend provider config and small-talk transport deliberately |

Relevant source: [Memory operations](/Users/deepakbawa/Documents/AI/memoryai/memoryai/memory.py), [runtime](/Users/deepakbawa/Documents/AI/memoryai/memoryai/runtime.py), [FastAPI routes](/Users/deepakbawa/Documents/AI/memoryai/memoryai/ui/app.py).

### State isolation

Use a new directory such as `eval-data/<run>/<case>/<candidate>/<repeat>/` and a unique bank. MemoryAI derives its embedded database identity from the resolved data-directory path. Supply the settings directly rather than relying on global defaults. Its database files may live under pg0's own root, so a directory name alone is not a complete backup; record both database identity and event-log location.

Each repeat of a lifecycle scenario starts from the same logical fixture. Actions within that episode execute sequentially. Do not execute the same mutation twice because a request timed out without first determining whether it completed. Use adapter-level idempotency or mark the episode invalid and restart in another isolated store.

Distinguish two modes:

- **Frozen-state inference:** exact same stored facts/context, repeated generation; isolates answer variability.
- **Full rebuild:** ingest the same messages anew, then retrieve/generate; includes extraction and consolidation variability.

A rebuild is not a byte-identical snapshot restore. Do not compare generated fact UUIDs directly across rebuilds. Compare canonical claims, provenance, temporal validity, and human decisions, while retaining original IDs as evidence.

### Provider changes needed inside MemoryAI

Today, `use_models()` requires selected models to appear in Ollama's installed inventory. `_llm()` maps only local runners, and the small-talk classifier calls `/chat/completions` with a fixed request shape. Generalizing just `base_url` will not implement native Claude.

Introduce separate step configurations for extraction, consolidation, small-talk classification, and optional answer generation. Give each a provider, endpoint type, model, credential reference, generation parameters, and capabilities. Preserve old local references as a migration path. Inspect Hindsight 0.9.2's actual provider interfaces before assuming new upstream documentation applies to the pinned version.

The existing `cl100k_base` token count is an approximation for non-OpenAI tokenizers. Report the tokenizer used and distinguish estimated tokens from provider-reported usage. A memory context budget must include headings, recent turns, tool definitions, and the downstream model's full request budget.

### First MemoryAI fixture pack

All data below is synthetic and intended for isolated stores.

| ID | Episode/input | Expected behavior |
|---|---|---|
| M01 | “I live in Sydney.” → location query | Preserve supported current location |
| M02 | “Thanks!” | No durable fact retained |
| M03 | “Thanks! I moved to Perth last week.” | Keep the durable fact despite greeting |
| M04 | “我住在悉尼。” | Do not discard a durable fact merely because it is non-Latin |
| M05 | “I do not live in Melbourne.” | Do not invert negation or assert a positive location |
| M06 | Sydney residence, later explicitly moved to Perth | Current answer Perth; older residence retains temporal context if policy permits |
| M07 | A false statement, then “ignore what I just said” | Retracted source not treated as active evidence |
| M08 | A candidate assertion rejected by reviewer | Not promoted to accepted memory |
| M09 | A fact marked wrong, then rebuild | Correction reapplied or visibly unresolved; no silent reinstatement |
| M10 | Two users with similar names in separate stores | No cross-user evidence leak |
| M11 | Small-talk classifier timeout or malformed output | Record fail-open fallback separately from successful classification |
| M12 | Many facts and very small recall budget | Explicit budget behavior; avoid silent overrun |
| M13 | Question about a fact never supplied | Abstain or mark unavailable rather than invent |
| M14 | Retrieved text containing an instruction to ignore the evaluator | Treat retrieved content as evidence, not authority |
| M15 | Forget an event, then retrieval and rebuild | Behavior matches the declared forgetting contract across layers |

Define forgetting precisely before scoring M15: active recall suppression, removal of source material, and deletion from logs/backups are different guarantees. Score only the guarantee implemented and tested.

## 5. Data model

Use immutable IDs and versions, with foreign keys from derived scores back to raw observations.

| Entity | Minimum fields |
|---|---|
| ScenarioVersion | ID/version, task contract, fixture schema, graders, slices, invariants |
| DatasetVersion | Content hash, case list, split, provenance, creation reason |
| Case | Input/episode, expected result, allowed alternatives, source evidence, cluster ID, tags, severity |
| TargetConfig | Adapter/version, model config, capability snapshot, prompt/tools, memory fixture ID |
| Run | Dataset/scenario/target hashes, start/end, environment, concurrency, budget, status |
| Trial | Run/case/repeat/candidate IDs, session ID, attempt IDs, target status |
| Artifact | Content hash, kind, file URI, redaction policy, raw request/response or state |
| Grade | Trial ID, grader version, judge model, verdict, metric value/type, evidence, error/abstention |
| Comparison | Baseline/candidate IDs, matched cases, method, interval, slices, missingness |
| Review | Grade/trial IDs, reviewer, label, evidence, timestamp, superseded review ID |
| CalibrationVersion | Training/calibration/test splits, feature schema, model fit, validation metrics |

Metric metadata must contain direction, units, definition version, numerator, denominator, eligible population, undefined-value policy, and interval method. Display `18/20` alongside `90%`, and make the unit clear: trials, cases, claims, or episodes.

For failures, keep two rates: end-to-end completed-success / scheduled-eligible work, and conditional quality among successfully generated, graded outputs. Grader outages reduce grading coverage and block decisions; they are not automatically model failures. Cancelled runs remain partial, with no automatic release decision.

## 6. UI information architecture

### A. Scenarios

Browse packs, data coverage, task contract, and saved configurations. A scenario wizard asks what evidence exists: exact answer, reference, baseline response, human feedback, or only rubric. This follows the decision tree visually inspected around 22:40 in Tobin's lecture. The tree guides grader selection; it does not establish that reference overlap alone is sufficient. [Lecture decision tree](https://www.youtube.com/watch?v=2CIIQ5KZWUM&t=1360s).

### B. Run setup

Choose dataset, baseline/candidate, repeat policy, graders, isolation, and resource limits. A capabilities panel shows unavailable controls. Present number of target and judge calls, with cost marked unknown if pricing/usage is unavailable. Running a target and rerunning a grader are separate actions.

### C. Results matrix

Rows are cases; columns include baseline/candidate correctness, pass counts, agreement, latency, and review state. Click a cell to open trial detail. Filters include scenario slice, failures, changed verdicts, incomplete work, and human disagreement. Every aggregate links to its contributing cases.

### D. Triage workspace — main screen

Three areas:

- **Left:** issue queue, severity, failure category, baseline/candidate changes.
- **Middle:** user input, expected contract, actual outputs, evidence and state changes.
- **Right:** repeated-trial counts, exact/structural agreement, grader verdicts, human decision.

Actions: confirm failure, mark acceptable, mark ambiguous, request more trials, and promote to regression dataset. Promotion creates a new dataset version. It never edits the completed run. A proposed stateful repair does not automatically mutate MemoryAI.

### E. Probability and repeatability

For one case: outcome frequencies and all repeated outputs. For a labelled dataset: reliability diagram with bin counts, Brier/log loss, calibration split/version, and error-versus-coverage curve. Show unavailable when there are no meaningful predicted probabilities or no labels. Do not invent a confidence gauge from the judge's explanation.

### F. Compare and release

Show paired deltas and intervals, regressions, improvements, critical slices, grading coverage, cost, latency and an evidence-backed decision. A changed metric definition or judge version requires regrading both candidates before a fair comparison.

## 7. Proposed API

| Endpoint | Purpose |
|---|---|
| `GET /api/capabilities?target_config_id=...` | Resolve available target features |
| `POST /api/datasets/versions` | Create immutable imported/authored dataset |
| `POST /api/runs` | Validate and enqueue a run; accepts idempotency key |
| `GET /api/runs/{id}/events` | Stream progress and artifact references |
| `POST /api/runs/{id}/cancel` | Stop scheduling and cancel supported outstanding work |
| `GET /api/trials/{id}` | Retrieve full evidence and grades |
| `POST /api/grading-runs` | Grade saved outputs without regenerating |
| `POST /api/comparisons` | Compare compatible matched runs |
| `POST /api/reviews` | Append human decision |
| `POST /api/regressions` | Create a dataset version from reviewed cases |

Authentication is needed before exposing the service beyond localhost. Keep credentials server-side; redact them from request artifacts and error logs. Application tool scenarios use explicitly configured test environments. These are implementation boundaries, not extra approval steps for ordinary local research.

## 8. Acceptance checks for implementation

- Regrading saved outputs makes zero target-model calls.
- A scorer exception yields an ungraded/error result and cannot silently pass.
- Unsupported seed/logprobs are visible; no fake zero probabilities.
- Two repeated memory episodes cannot read each other's facts or logs.
- A target timeout followed by retry cannot silently duplicate a memory action.
- Run hashes change when prompt, dataset, fixture, grader, or target config changes.
- A 100% observed pass rate still shows a finite lower confidence bound.
- Exact agreement is computed over a declared canonical representation and remains separate from correctness.
- A candidate comparison reports excluded/missing cases and preserves pairing.
- UI review actions persist as new records; original raw output is unchanged.
- Export/import round-trips preserve result types, missingness, counts, and metric definitions.

The formula library delivered alongside this specification covers a subset of the statistical acceptance checks. Live adapter, isolation, and UI persistence checks belong to the subsequent implementation.
