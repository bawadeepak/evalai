# Operations

## Commands

| Command | What it does |
|---|---|
| `make setup` | Install locked Python (`uv sync --frozen`) and frontend (`npm ci`) dependencies, and the Playwright Chromium browser |
| `make migrate` | Create or upgrade the database (`evalai migrate`) |
| `make demo` | Seed the clearly labelled demo project (idempotent); a running worker executes its runs |
| `make dev` | API with reload, a worker and the Vite dev UI on http://127.0.0.1:8311 |
| `make build` | Compile check, lint and production frontend build |
| `make start` | Migrate, then serve the built UI and API on http://127.0.0.1:8310 with one worker |
| `make test` | pytest (unit and integration, no paid calls) and Vitest |
| `make test-e2e` | Build, then the Playwright journeys against an isolated temporary server on port 8320 |
| `make clean-data` | Delete `.data/` after confirmation |

The CLI behind these is `uv run --frozen evalai <command>`: `migrate`,
`serve [--host --port --reload]`, `worker [--once]`, `start [--port]`, `demo`,
`memoryai gc [--yes]`.

## Configuration

All settings are environment variables (prefix `EVAL_TRIAGE_`); see
`.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `EVAL_TRIAGE_DATA_DIR` | `.data/` in the repository | Database, artifacts, MemoryAI stores |
| `EVAL_TRIAGE_API_HOST` / `EVAL_TRIAGE_API_PORT` | `127.0.0.1` / `8310` | Bind address |
| `EVAL_TRIAGE_ALLOW_NON_LOOPBACK` | `false` | Required to bind anything but loopback (there is no authentication) |
| `EVAL_TRIAGE_WORKER_SLOTS` | `4` | Concurrent jobs per worker |
| `EVAL_TRIAGE_LEASE_SECONDS` / `EVAL_TRIAGE_HEARTBEAT_SECONDS` | `60` / `10` | Job lease and renewal interval |
| `EVAL_TRIAGE_WORKER_POLL_SECONDS` | `0.5` | Idle polling interval |
| `MEMORYAI_SOURCE_PATH` | `../memoryai` next to this repository | The MemoryAI checkout |
| `MEMORYAI_PYTHON` | `<MEMORYAI_SOURCE_PATH>/.venv/bin/python` | Interpreter for the bridge |
| `EVAL_TRIAGE_MEMORYAI_HF_OFFLINE` | `true` | Hugging Face offline inside the bridge (nothing is downloaded implicitly) |
| `EVAL_TRIAGE_TIKTOKEN_CACHE_DIR` | unset | An existing tiktoken cache for the bridge |
| `EVAL_TRIAGE_PROMPTFOO_COMMAND` / `EVAL_TRIAGE_PROMPTFOO_WORKDIR` | unset | Enable the Promptfoo suite runner |
| `EVAL_TRIAGE_PROMPTFOO_TIMEOUT_SECONDS` | `900` | Suite timeout |
| `EVAL_TRIAGE_FRONTEND_DIST` | `frontend/dist` | Built UI served by the API |
| Provider keys (e.g. `OPENAI_API_KEY`) | — | Referenced by name from provider configurations |

## Data directory

```
$EVAL_TRIAGE_DATA_DIR/
  eval_triage.sqlite (+ -wal, -shm)   all records
  artifacts/                          content-addressed evidence files
  memoryai-stores/                    isolated MemoryAI stores (retained by default)
  inspect-logs/                       logs from Inspect runs (when used)
  pricing.json                        optional price overrides
```

**Backups.** Stop the service and copy the whole directory, or use Settings ›
Export for a portable, checksummed project archive (credentials are never
included; text redaction is optional). Imports always create a new project.

**Migrations** run automatically on `make start` and `make migrate` (Alembic;
revisions in `backend/eval_triage/db/migrations/versions/`).

**MemoryAI stores** are retained for inspection. Settings shows their disk
usage. `uv run --frozen evalai memoryai gc` lists what would be dropped;
`--yes` drops only stores Eval Triage created (nonce and instance verified).

## Health

`GET /api/v1/health` reports the API, database (revision, journal mode),
worker (`ok` = a heartbeat within three intervals; `stale`; `absent`),
optional plugins and MemoryAI availability. The UI footer shows the same.
Runs stay queued while no worker is running.

## Performance

`uv run --frozen python -m eval_triage.testing.perf_check` runs 200 cases × 2
candidates × 5 repeats on the demo adapter in a temporary directory and prints
timings and integrity checks (no job claimed twice, no duplicate attempts or
grades). Measured results are in [validation-report.md](./validation-report.md).
Throughput is bounded by SQLite writes: after every job the worker re-checks
whether the run is finished.

## Troubleshooting

| Symptom | Check |
|---|---|
| Runs stay queued | The footer says the worker is not running: use `make start` or `uv run --frozen evalai worker` |
| `address already in use` on 8310 | Another instance is running (`lsof -nP -iTCP:8310 -sTCP:LISTEN`), or set `EVAL_TRIAGE_API_PORT` |
| "Frontend not built" at `/` | Run `make build` (or use `make dev`) |
| A provider run is refused | Read the linked validation error: missing credential variable, unsupported parameter, or unknown capability without a probe |
| MemoryAI runs refused | Settings › MemoryAI shows whether the checkout and interpreter were found; the real backend also needs Ollama and the cached models listed in [adapters.md](./adapters.md) |
| The bridge fails offline | The tokenizer or embedding models are not cached; the bridge never downloads them |
