"""Performance sanity check: ~200 cases × 2 candidates × 5 repeats on the demo adapter.

    uv run --frozen python -m eval_triage.testing.perf_check [--cases 200] [--repeats 5] [--keep]

Uses a temporary data directory and the in-process worker loop, then times the
analysis endpoints the UI calls. Prints JSON. It is a sanity check for local use
(orders of magnitude, not a benchmark) and is not part of the default test suite.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

LABELS = ["billing", "technical", "account", "other"]


def document(cases: int) -> dict:
    return {
        "schema_version": 1, "name": "perf-routing", "pack": "exact_classification",
        "contract": 'Route each message to one queue. Reply with JSON {"label": "<queue>"}.',
        "allowed_labels": LABELS, "slice_keys": ["queue"],
        "graders": [{"name": "label", "kind": "deterministic", "checks": ["label_match"]}],
        "dataset": {"name": "perf-routing", "cases": [
            {"external_id": f"P{i:04d}", "cluster_id": f"perf-{i:04d}", "split": "test",
             "tags": {"queue": LABELS[i % 4]}, "input": {"text": f"Synthetic support message {i}"},
             "expected": {"label": LABELS[i % 4]}} for i in range(cases)]},
    }


class _WarningCounter:
    """Counts worker warnings (for example lost leases) during the run."""

    def __init__(self) -> None:
        import logging

        self.messages: list[str] = []
        outer = self

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if record.levelno >= logging.WARNING:
                    outer.messages.append(record.getMessage())

        self.handler = _Handler()
        logging.getLogger("eval_triage.worker").addHandler(self.handler)

    def close(self) -> None:
        import logging

        logging.getLogger("eval_triage.worker").removeHandler(self.handler)


def integrity(ctx) -> dict:
    """Evidence that nothing ran twice: claims per job, attempts per trial stage, grades per slot."""
    from collections import Counter

    from sqlalchemy import select

    from eval_triage.db.models import Attempt, Grade, Job

    with ctx.db.read() as session:
        jobs = session.execute(select(Job.kind, Job.attempts, Job.status)).all()
        attempts = Counter(session.execute(select(Attempt.trial_id, Attempt.stage)).all())
        grades = Counter(session.execute(select(Grade.grading_run_id, Grade.trial_id, Grade.grader_id)).all())
    return {
        "jobs": dict(Counter(f"{kind}:{status}" for kind, _, status in jobs)),
        "jobs_claimed_more_than_once": sum(1 for _, n, _ in jobs if (n or 0) > 1),
        "trial_stages_with_more_than_one_attempt": sum(1 for n in attempts.values() if n > 1),
        "duplicate_grades": sum(1 for n in grades.values() if n > 1),
    }


def _timed(label: str, timings: dict, fn):
    started = time.perf_counter()
    result = fn()
    timings[label] = round(time.perf_counter() - started, 3)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--keep", action="store_true", help="keep the temporary data directory")
    args = parser.parse_args(argv)

    data_dir = Path(tempfile.mkdtemp(prefix="evalai-perf-"))
    os.environ["EVAL_TRIAGE_DATA_DIR"] = str(data_dir)

    from fastapi.testclient import TestClient

    from eval_triage.api.app import create_app
    from eval_triage.config import Settings
    from eval_triage.worker import drain

    settings = Settings(data_dir=data_dir, worker_poll_seconds=0.01, heartbeat_seconds=0.5, lease_seconds=60,
                        frontend_dist=data_dir / "no-frontend")
    app = create_app(settings)
    ctx = app.state.ctx
    timings: dict[str, float] = {}
    try:
        with TestClient(app) as client:
            project = client.post("/api/v1/projects", json={"name": "perf check"}).json()["data"]["id"]
            created = _timed("import_scenario_and_dataset_s", timings, lambda: client.post(
                "/api/v1/scenarios", json={"project_id": project, "document": document(args.cases)}).json()["data"])
            configs = {}
            for key, profile in (("baseline", "baseline"), ("candidate", "candidate")):
                configs[key] = client.post("/api/v1/target-configs", json={
                    "project_id": project, "name": f"perf {key}", "adapter": "demo", "model": f"demo-perf-{key}",
                    "parameters": {"profile": profile}}).json()["data"]["id"]
            body = {"project_id": project, "scenario_id": created["scenario"]["id"],
                    "dataset_id": created["dataset"]["id"], "name": "perf check",
                    "candidates": [{"key": k, "target_config_id": v} for k, v in configs.items()],
                    "execution": {"repeats": args.repeats}}
            _timed("validate_s", timings, lambda: client.post("/api/v1/runs/validate", json=body).raise_for_status())
            run = _timed("enqueue_s", timings, lambda: client.post(
                "/api/v1/runs", json=body, headers={"Idempotency-Key": "perf-check-0001"}).json()["data"])
            warnings = _WarningCounter()
            try:
                _timed("execute_and_grade_s", timings, lambda: drain(ctx, max_seconds=3600))
            finally:
                warnings.close()
            detail = client.get(f"/api/v1/runs/{run['id']}").json()["data"]
            for representation in ("raw", "json", "semantic"):
                _timed(f"summary_{representation}_s", timings, lambda r=representation: client.get(
                    f"/api/v1/runs/{run['id']}/summary", params={"representation": r}).raise_for_status())
            _timed("triage_s", timings, lambda: client.get(f"/api/v1/runs/{run['id']}/triage").raise_for_status())
            _timed("trials_list_s", timings, lambda: client.get(
                f"/api/v1/runs/{run['id']}/trials", params={"limit": 2000}).raise_for_status())
            _timed("statistics_query_s", timings, lambda: client.post("/api/v1/statistics/query", json={
                "run_id": run["id"], "metric": "observed_pass_rate", "group_by": "case"}).raise_for_status())
            _timed("comparison_s", timings, lambda: client.post("/api/v1/comparisons/validate", json={
                "project_id": project, "baseline_run_id": run["id"], "baseline_key": "baseline",
                "candidate_run_id": run["id"], "candidate_key": "candidate"}).raise_for_status())
        planned = args.cases * 2 * args.repeats
        report = {
            "cases": args.cases, "candidates": 2, "repeats": args.repeats, "planned_trials": planned,
            "run_status": detail["status"], "terminal_trials": detail["terminal_trials"],
            "trial_counts": detail["trial_counts"],
            "trials_per_second": round(planned / timings["execute_and_grade_s"], 1)
            if timings["execute_and_grade_s"] else None,
            "timings": timings,
            "integrity": {**integrity(ctx), "worker_warnings": len(warnings.messages),
                          "lost_lease_warnings": sum("lost lease" in m for m in warnings.messages)},
            "database_bytes": settings.db_path.stat().st_size,
            "python": sys.version.split()[0],
            "note": "Demo adapter (no provider calls); in-process worker loop; one machine, one run. "
                    "Orders of magnitude only.",
        }
        print(json.dumps(report, indent=2))
        return 0 if detail["status"].startswith("completed") and detail["terminal_trials"] == planned else 1
    finally:
        ctx.db.dispose()
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
