"""Command-line entry point: ``evalai <command>``."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time

from eval_triage.config import get_settings


def _cmd_migrate(_args) -> int:
    from eval_triage.db.migrate import upgrade

    settings = get_settings()
    settings.ensure_dirs()
    upgrade(settings.db_path)
    print(f"database migrated: {settings.db_path}")
    return 0


def _cmd_serve(args) -> int:
    import uvicorn

    settings = get_settings()
    host = args.host or settings.api_host
    port = args.port or settings.api_port
    settings.model_copy(update={"api_host": host}).check_bind_host()
    uvicorn.run("eval_triage.api.app:create_app", factory=True, host=host, port=port, log_level="info",
                reload=args.reload)
    return 0


def _cmd_worker(args) -> int:
    from eval_triage.worker import run_worker

    return run_worker(once=args.once, worker_id=args.worker_id)


def _cmd_start(args) -> int:
    """Run the API and one worker; stop both on Ctrl-C or when either exits."""
    _cmd_migrate(args)
    env = dict(os.environ)
    worker = subprocess.Popen([sys.executable, "-m", "eval_triage.cli", "worker"], env=env)
    api = subprocess.Popen([sys.executable, "-m", "eval_triage.cli", "serve"]
                           + (["--port", str(args.port)] if args.port else []), env=env)
    procs = [api, worker]

    def _stop(*_):
        for proc in procs:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGTERM, _stop)
    try:
        while all(proc.poll() is None for proc in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _stop()
        for proc in procs:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


def _cmd_demo(_args) -> int:
    from eval_triage.demo import seed_demo

    settings = get_settings()
    _cmd_migrate(_args)
    result = seed_demo(settings)
    print(json.dumps(result, indent=2))
    return 0


def _cmd_memoryai_gc(args) -> int:
    from eval_triage.adapters.memoryai.ownership import gc_stores

    result = gc_stores(get_settings(), dry_run=not args.yes)
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evalai", description="Eval Triage local application")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="create or upgrade the local database").set_defaults(func=_cmd_migrate)

    serve = sub.add_parser("serve", help="serve the API (and built UI when present)")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_cmd_serve)

    worker = sub.add_parser("worker", help="run a durable job worker")
    worker.add_argument("--once", action="store_true", help="drain available jobs then exit")
    worker.add_argument("--worker-id")
    worker.set_defaults(func=_cmd_worker)

    start = sub.add_parser("start", help="migrate, then run API and worker together")
    start.add_argument("--port", type=int)
    start.set_defaults(func=_cmd_start)

    sub.add_parser("demo", help="seed the clearly labelled demo project (idempotent)").set_defaults(func=_cmd_demo)

    memoryai = sub.add_parser("memoryai", help="MemoryAI bridge maintenance")
    memoryai_sub = memoryai.add_subparsers(dest="memoryai_command", required=True)
    gc = memoryai_sub.add_parser("gc", help="drop isolated stores created by Eval Triage")
    gc.add_argument("--yes", action="store_true", help="actually drop; default is a dry run")
    gc.set_defaults(func=_cmd_memoryai_gc)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
