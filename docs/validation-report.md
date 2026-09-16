# Validation report

Date: 16 September 2026. Every result below was produced in this environment;
nothing was estimated.

| Environment | |
|---|---|
| Machine | macOS 26.6.2, arm64 |
| Python | 3.12.13 (uv 0.11.30, locked by `uv.lock`) |
| Node | v24.18.0, npm 11.16.0 (locked by `frontend/package-lock.json`) |
| Browser tests | Playwright 1.63.0, Chromium |
| MemoryAI | `/Users/deepakbawa/Documents/AI/memoryai` at `d14259d` (read-only) |
| Code | commits M1–M11 (`git log`); results below are for the final commit |

## Definition of done (plan.md §0)

| Requirement | Status | Evidence |
|---|---|---|
| A fresh checkout installs, migrates and starts through documented commands | **Verified** (offline) | Fresh-clone rehearsal below |
| A user without credentials completes the full workflow with a labelled demo adapter | **Verified** | Playwright journey 03 and the smoke suite |
| A configured user can execute real OpenAI, Anthropic, local OpenAI-compatible and isolated MemoryAI targets | **Verified** for MemoryAI (real runtime) and the local OpenAI-compatible runner; **not verified live** for OpenAI and Anthropic | Live MemoryAI suite below (it also drove `gemma3:4b` through the local OpenAI-compatible adapter); cloud providers pass mock-transport tests only |
| Definitions, trials, grades, comparisons, reviews and exports survive restart | **Verified** | `tests/integration/test_restart.py` |
| Every displayed number has its definition, denominator, eligibility, provenance and unavailable behaviour | **Verified** | `MetricValue` contract tests; Vitest `MetricValue.test.tsx` |
| All required screens and workflows work; no placeholders or invented measurements | **Verified** for the demo and mocked providers | Playwright smoke per screen and five journeys |
| Tests prove isolation, job recovery, statistics, evidence preservation, regrading and the main UI journeys | **Verified** | Suites listed below |
| Installation, architecture, adapter, test and limitations reports | **Delivered** | `README.md`, `docs/architecture.md`, `docs/adapters.md`, this report |

## Results

| Check | Result |
|---|---|
| `make test` — pytest (unit + integration) | **210 passed**, 4 deselected (the live MemoryAI tests, run separately with `-m live_memoryai`) |
| Live MemoryAI — bridge contract (`-m live_memoryai`) | **3 passed** in 76 s against the real runtime |
| Live MemoryAI — M01–M15 through the engine | **1 passed** in 3 min 25 s; measured outcomes below |
| `make test` — Vitest | **54 passed** (7 files, including WCAG AA contrast of every text/background token pair in both themes) |
| `make build` — compile check, ruff, production build | Passed; no bundle-size warning (initial JS 260 kB / 80 kB gzip) |
| `make test-e2e` — Playwright | **20 passed**: smoke of all 11 screens, detail screens, demo counts from stored grades, provider journey, triage → confirm → promote → rerun → compare → export → import, calibration refusal and valid fit, integrations import, keyboard-only triage, every screen at 375 px without page-level horizontal scroll, collapsed navigation and triage tabs. Every request and response is checked for a planted sentinel secret. |
| Reference mathematics (`docs/test_metrics.py`) | 12 passed |
| `make start` | Production UI and API on 8310 with a worker: health OK in 3 s, CSP header present, SPA fallback, hashed assets, unknown API → 404, foreign Host header → 400, clean shutdown |

### Fresh-clone rehearsal

A `git clone` of the final commit into an empty directory, with a new data
directory. Nothing was downloaded: installs ran offline from local caches.

| Step | Outcome |
|---|---|
| `uv sync --frozen --offline` | Passed |
| `npm ci --offline` | Passed |
| `npx playwright install chromium` (part of `make setup`) | **Skipped** — it downloads a browser; the machine's existing Playwright browser cache was used |
| `make test` in the clone | 210 passed · 54 passed |
| `make build` | Passed |
| `make migrate demo` | Passed |
| `make start` | Worker healthy in 4 s; both demo runs executed to completion (240/240 and 120/120 trials, `completed_with_errors` by design); UI served; clean shutdown |

### Live MemoryAI suite (real runtime)

The fifteen lifecycle episodes M01–M15 ran against the real MemoryAI runtime
(commit `d14259d`) in brand-new isolated stores, with `gemma3:4b` on local
Ollama for both MemoryAI's own model and the `generate` steps, and a cached
`cl100k_base` tokenizer.

**These are measurements, not expectations.** The test asserts only that every
episode executed, was graded, captured its evidence and was cleaned up.

| Measure | Result |
|---|---|
| Episodes executed | 15 of 15, all trial status `success` |
| Outcomes | **12 pass, 3 fail**, all 15 resolved (no unresolved or grading errors) |
| Failing cases | M04 and M12 (mandatory `memory-contract`), M07 (mandatory `answer-checks`) |
| Episode latency | 0.6 s–71.8 s (M12 slowest; median ≈ 6.7 s) |
| Isolation | One brand-new store per episode (M10 uses two); all owned, retained, then dropped by `gc` |
| MemoryAI's own store | Untouched — its pg0 instance (`memoryai-c9cb1f0756`) was never opened, and the protected-instance guard refuses it by construction |

M04 and M12 are the two behaviours the fake backend reproduces as hypotheses
from source inspection, now observed live: M04's non-Latin text is classified
as small talk by MemoryAI's Latin-word rule (`all([])` is true), and M12's
recall exceeds the requested token budget because the facts block is not
trimmed. M07 failed the answer checks because the local `gemma3:4b` answer did
not contain the required strings — a generation-model result, not a MemoryAI
defect. None of these are Eval Triage defects; they are exactly the kind of
finding the tool exists to surface.

### Performance sanity check

`python -m eval_triage.testing.perf_check`: 200 cases × 2 candidates × 5
repeats on the demo adapter, in-process worker loop, one machine.

| Measure | Result |
|---|---|
| Trials | 2,000 of 2,000 completed (plus 2,000 grading jobs) |
| Execution and grading | 114 s (≈17.5 trials/s) |
| Validate / enqueue | 0.10 s / 0.52 s |
| Summary (raw / JSON / semantic) | 0.21 / 0.21 / 0.21 s |
| Triage queue · trial list · statistics query · comparison | 0.19 · 0.13 · 0.18 · 0.31 s |
| Integrity | No job claimed twice, no trial stage with a second attempt, no duplicate grade, 0 worker warnings |
| Database size | 15 MB |

## Not verified, with reasons

| Item | Status | Reason |
|---|---|---|
| Live OpenAI and Anthropic provider checks | **Skipped** by the user's choice (no paid calls) | Adapters are verified against mock transports: request shapes, capability tables, error mapping, retries, auth-header stripping. |
| `inspect-ai` and `ragas` packages | **Not installed** | Installing or locking them as extras needs a PyPI download, which was not approved. Both importers are verified with recorded synthetic fixtures; the Inspect runner and Ragas grader are verified only against stand-in modules. |
| Real Promptfoo | **Not exercised** | The suite runner is tested with a stand-in command; import is tested with a synthetic `results.json`. |

## Defects found and fixed during validation

* The demo probability fixture had too few clusters for a default calibration
  fit (20 < 30); enlarged to 40 + 40 clusters.
* The worker logged spurious "lost lease" warnings when a heartbeat fired
  after a job had completed; renewal now stops before a job leaves RUNNING
  (warnings 6 → 0; integrity unchanged).
* On narrow screens the open navigation covered its only close control, and
  tapping the current page's link left it open; fixed with an in-panel close
  button, backdrop, Escape and focus management.
* The trial detail showed its outcome as unknown; it now shows the latest
  grading run's outcome.
* The live bridge contract tests close their stores with `retain=True` (the
  product retains stores by design) while using a temporary database, so
  `gc` had no record of them and one Postgres instance was left behind. The
  tests now drop their own stores through the same ownership checks; the
  instance left by the first run was dropped the same way.

## Limitations

* OpenAI and Anthropic execution was not verified live (above). MemoryAI and
  the local OpenAI-compatible runner were.
* The live MemoryAI results are one run of one model (`gemma3:4b`) on one
  machine: a measurement of that configuration, not a benchmark of MemoryAI.
* Throughput is bounded by SQLite writes (the worker re-checks run completion
  after every job): about 17.5 trials/s on the demo adapter with one worker.
* Single user, no authentication; loopback only by design.
* Ragas LLM-based metrics are unsupported (no evaluator LLM is wired into
  Ragas); only non-LLM metrics run.
* Imported external results are viewable and exportable but are not converted
  into Eval Triage datasets or runs; text-redacted exports omit them.
* Accessibility automation covers token contrast, keyboard-only triage and
  375 px layouts; no automated axe audit was run. Browser tests use Chromium
  only.
* The optional Docker setup in the plan was omitted.
* The Playwright specs live in `frontend/e2e/` (not `tests/e2e/`) so they
  resolve the frontend's `node_modules`.

## External prerequisites

| For | Needs |
|---|---|
| Real providers | API keys in environment variables (referenced by name), pricing entries for cost limits |
| Local OpenAI-compatible runner | e.g. Ollama with the chosen model |
| Live MemoryAI | The MemoryAI checkout and `.venv`, Ollama with `gemma3:4b`, cached Hugging Face models (`bge-small-en-v1.5`, `ms-marco-MiniLM-L-6-v2`) and a cached `tiktoken` `cl100k_base` encoding |
| Optional integrations | `inspect-ai`, `ragas`, or a local `promptfoo` command |
| End-to-end tests | The Playwright Chromium browser (`make setup`) |
