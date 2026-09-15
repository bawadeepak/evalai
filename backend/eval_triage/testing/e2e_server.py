"""Isolated server for Playwright: ``python -m eval_triage.testing.e2e_server``.

Creates a temporary data directory, migrates it, seeds and executes the demo
in-process, starts a fast-polling worker subprocess, waits for its heartbeat and
then serves the built UI and API on 127.0.0.1:8320 (``EVAL_TRIAGE_E2E_PORT``).
Everything is removed on exit unless ``EVAL_TRIAGE_E2E_KEEP=1``.

A sentinel secret is placed in ``EVALAI_E2E_SECRET`` so browser tests can
assert that no response ever carries a credential value.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SENTINEL_SECRET = "sk-evalai-E2E-SENTINEL-3b1f6c0a-never-in-browser"


def _configure(data_dir: Path, port: int) -> None:
    os.environ.update({
        "EVAL_TRIAGE_DATA_DIR": str(data_dir),
        "EVAL_TRIAGE_TESTING": "true",
        "EVAL_TRIAGE_API_PORT": str(port),
        "EVAL_TRIAGE_WORKER_POLL_SECONDS": "0.05",
        "EVAL_TRIAGE_HEARTBEAT_SECONDS": "0.5",
        "EVAL_TRIAGE_LEASE_SECONDS": "5",
        "EVALAI_E2E_SECRET": SENTINEL_SECRET,
    })


def _wait_for_heartbeat(ctx, timeout: float = 30.0) -> bool:
    from eval_triage.api.routes.health import worker_status

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if worker_status(ctx)["status"] == "ok":
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    port = int(os.environ.get("EVAL_TRIAGE_E2E_PORT", "8320"))
    data_dir = Path(tempfile.mkdtemp(prefix="evalai-e2e-"))
    _configure(data_dir, port)

    import uvicorn

    from eval_triage.api.app import build_context, create_app
    from eval_triage.config import get_settings, reset_settings
    from eval_triage.db.migrate import upgrade
    from eval_triage.demo import seed_demo
    from eval_triage.worker import drain

    reset_settings()
    settings = get_settings()
    settings.ensure_dirs()
    upgrade(settings.db_path)
    ctx = build_context(settings)
    seed_demo(settings, ctx)
    drain(ctx, max_seconds=180)  # demo runs finish before the first test starts

    worker = subprocess.Popen([sys.executable, "-m", "eval_triage.cli", "worker"], env=dict(os.environ))

    def cleanup(*_args) -> None:
        if worker.poll() is None:
            worker.send_signal(signal.SIGTERM)
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
        if os.environ.get("EVAL_TRIAGE_E2E_KEEP") != "1":
            shutil.rmtree(data_dir, ignore_errors=True)

    try:
        if not _wait_for_heartbeat(ctx):
            print("e2e server: worker did not report a heartbeat", file=sys.stderr)
            return 1
        print(f"e2e server: data {data_dir}, serving http://127.0.0.1:{port}", flush=True)
        uvicorn.run(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
