# Adapters and integrations

A **target configuration** (Providers screen, `/api/v1/target-configs`) is a
versioned record of adapter, endpoint mode, model, base URL, credential
*reference*, parameters, prompt template, tools and MemoryAI settings. Editing
creates a new version; runs keep the version they used.

## Capabilities and validation

Every configuration carries a capability table — structured output, tools,
images, temperature, top_p, seed, token and prompt logprobs, usage, state
inspection, isolation, cancellation, episodes, retrieval — each `supported`,
`unsupported` or `unknown`, with its evidence source and verification time.
Run validation blocks any requested parameter whose capability is unsupported
(the error links to the provider so it can be fixed as a new version).
Unknown capabilities need a connection test or the configuration's
experimental mode, which is recorded as a warning in every run manifest.
Parameters are never dropped silently.

## Credentials

Enter the **name** of an environment variable (for example `OPENAI_API_KEY`),
never the key. The UI refuses values that look like keys. The API reports only
whether the variable is set (`credential_status`); values are read at call
time and never stored or returned. Export archives contain reference names
only.

## Built-in adapters

| Adapter | Endpoint modes | Notes |
|---|---|---|
| `demo` | `demo` | Offline and deterministic. Outputs come from `fixtures/demo/`; every run, trial and screen is labelled demo. Shows stable-wrong, flaky, malformed, provider-error, absent-probability and judge-failure cases. |
| `openai` | `responses` (default), `chat_completions` | Native OpenAI SDK with `max_retries=0` (Eval Triage owns retries). Credential default `OPENAI_API_KEY`. Optional `base_url`. |
| `anthropic` | `messages` | Native Anthropic SDK. Content blocks, tool use, stop reasons and usage are recorded. Seeds and logprobs are not offered by this API and are rejected before enqueue. Credential default `ANTHROPIC_API_KEY`. |
| `openai_compatible` | `chat_completions` | Local runners such as Ollama (`http://127.0.0.1:11434/v1`). Capabilities start `unknown`: run a connection test or use experimental mode. |
| `memoryai` | `bridge` | Isolated MemoryAI episodes through the bridge (below). |

Capability tables and prices are dated. Prices live in
`config/pricing.default.json` (demo only) and can be extended in
`$EVAL_TRIAGE_DATA_DIR/pricing.json`; a model without a price shows cost as
*unknown*, never zero, and a monetary cap is refused when pricing is unknown.

A **connection test** is an explicit, user-triggered job that sends one small
bounded request and records the result.

## MemoryAI

MemoryAI stays untouched: Eval Triage never installs into its virtual
environment, never reads, copies or clears its `data/` directory, and never
calls `use_models()` (which pins models machine-wide).

* **Bridge process.** `bridges/memoryai/evalai_bridge` runs under MemoryAI's
  own interpreter (`MEMORYAI_PYTHON`, default `<MEMORYAI_SOURCE_PATH>/.venv/bin/python`)
  with `PYTHONPATH=bridges/memoryai`. *Deviation from the plan:* the plan
  suggested installing the bridge into MemoryAI's environment; running it from
  this repository via `PYTHONPATH` achieves the same without modifying the
  user's environment. `MEMORYAI_*` and `HINDSIGHT_API_*` variables are removed
  from its environment and Hugging Face runs offline.
* **Protocol.** Newline-delimited JSON over stdin/stdout with request ids, a
  protocol version and typed errors. Commands: `hello`, `prepare`,
  `execute_action`, `inspect_state`, `close`, `drop_store`, `shutdown`. There is
  deliberately no `clear`. Stdout is reserved for the protocol (library output
  is redirected to stderr). A timeout, crash or protocol error kills the
  process; processes are recycled every 25 episodes.
* **Isolation.** Every episode gets its own absolute data directory and bank
  under `$EVAL_TRIAGE_DATA_DIR/memoryai-stores/`. `prepare` refuses a directory
  or pg0 instance that already exists and writes an ownership manifest
  (`.evalai-owned.json`, with a nonce that is also stored in the database)
  before starting. Stores are **retained** by default; `evalai memoryai gc`
  shows what it would drop and `evalai memoryai gc --yes` drops only stores
  whose manifest nonce and instance name match Eval Triage's records — never
  the instance derived from MemoryAI's real `data/`.
* **Evidence.** New event ids are found by diffing the event log; recall
  results are captured once through an engine proxy and mapped back to facts,
  documents and steps; `inspect_state` pages through all memory units and
  reports MemoryAI's own 200-item truncation separately, so a state assertion
  claims exhaustiveness only after a full paging pass. Fault injection for the
  small-talk check is accepted only in test mode.
* **Cloud boundary.** Models used *inside* MemoryAI must be local
  (`memory_config.llm_base_url` must be a loopback URL; default model
  `gemma3:4b` via Ollama). Cloud providers are available as *generation*
  targets (`memory_config.generation_target_config_id`) for `generate` steps,
  not inside MemoryAI.
* **Backends.** `memory_config.backend: real` uses the MemoryAI runtime;
  `fake` is a deterministic stand-in with MemoryAI's shapes and known quirks
  that needs neither Ollama nor Postgres.
* **Live prerequisites** (for the real backend): the MemoryAI checkout and its
  `.venv`, Ollama with `gemma3:4b`, the cached Hugging Face models
  (`bge-small-en-v1.5`, `ms-marco-MiniLM-L-6-v2`) and a cached `tiktoken`
  `cl100k_base` encoding (see [operations.md](./operations.md#the-bridge-tokenizer)).
  The live tests — the bridge contract plus M01–M15 through the engine — run
  with `uv run --frozen pytest -m live_memoryai`. They take a few minutes,
  create one isolated store per episode and drop every store afterwards.
  Measured results are in the [validation report](./validation-report.md#live-memoryai-suite-real-runtime).

## Optional integrations

The core app never imports these packages; each shows as *unavailable* with a
reason when its prerequisite is missing (Settings › External results).

| Integration | Built in | Needs |
|---|---|---|
| **Promptfoo** | Import of `promptfoo eval -o results.json` files: assertion types, pass/fail, reasons and errors are kept with provenance; Promptfoo's score is recorded as a score, never a probability. | Running suites: `EVAL_TRIAGE_PROMPTFOO_COMMAND` (an existing local promptfoo command) and `EVAL_TRIAGE_PROMPTFOO_WORKDIR` (configs must live inside it). Eval Triage never installs promptfoo. |
| **Inspect AI** | Import of Inspect JSON eval logs (`--log-format json` or `inspect log convert --to json`): run, task and sample ids and epochs are kept; C/I/P/N letters and numeric scores are kept as reported. | Running tasks: the `[inspect]` extra. Task specs are resolved by Inspect relative to the working directory; absolute paths are normalised for you. |
| **Ragas** | — | The `[ragas]` extra. Used as an external grader (`kind: external`, `config.plugin: ragas`) for non-LLM metrics; results record the Ragas version, metric definition and judge configuration. LLM-based metrics are reported unavailable. A numeric score yields a verdict only with a declared threshold. |

Install the optional extras with:

```bash
uv sync --extra inspect --extra ragas
```

Ragas is pinned to `>=0.2,<0.3` with `langchain-community<0.4` and
`rapidfuzz`: newer Ragas releases depend on `instructor`, which caps `openai`
below 2.0 and would downgrade the core SDK, and they import a
langchain-community module that no longer exists. A package that is installed
but cannot be imported is reported as *unavailable with its reason*, never as a
grading error.

Imported results are immutable, keep the original file as an artifact (stored
redacted if it contains secret-like values) and travel with project export and
import. See [validation-report.md](./validation-report.md) for what has and has
not been exercised against the real packages.

The optional Docker setup described in the plan was omitted; the application
runs directly with `uv` and `npm`.
