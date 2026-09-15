"""A worker killed mid-call is recovered: attempt history is kept, non-mutating work resumes,
and interrupted memory episodes restart in a fresh store rather than replaying mutations."""

import os
import signal
import subprocess
import sys
import time

from sqlalchemy import select

from eval_triage.db.models import Attempt, Run, Trial
from tests.integration.helpers import demo_target, import_fixture, make_project, run_all, start_run


def _spawn_worker(settings):
    env = {**os.environ, "EVAL_TRIAGE_DATA_DIR": str(settings.data_dir), "EVAL_TRIAGE_LEASE_SECONDS": "2",
           "EVAL_TRIAGE_HEARTBEAT_SECONDS": "0.5", "EVAL_TRIAGE_WORKER_POLL_SECONDS": "0.05",
           "EVAL_TRIAGE_WORKER_SLOTS": "1"}
    return subprocess.Popen([sys.executable, "-m", "eval_triage.cli", "worker", "--worker-id", "doomed"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_for_running_attempt(ctx, run_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with ctx.db.read() as session:
            running = session.scalars(select(Attempt).join(Trial).where(Trial.run_id == run_id,
                                                                        Attempt.status == "running")).first()
            if running:
                return running.id
        time.sleep(0.1)
    raise AssertionError("worker never started an attempt")


def _kill_mid_call(settings, ctx, run_id):
    proc = _spawn_worker(settings)
    try:
        attempt_id = _wait_for_running_attempt(ctx, run_id)
    finally:
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
    time.sleep(2.2)  # let the 2 s lease expire
    return attempt_id


def test_killed_worker_non_mutating_call_recovers(settings, ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml", include=["C01"])
    slow = demo_target(ctx, project, "slow", delay_ms=4000)
    run_id = start_run(ctx, project, suite, {"baseline": slow}, repeats=1)
    interrupted_id = _kill_mid_call(settings, ctx, run_id)
    run_all(ctx, seconds=60)
    with ctx.db.read() as session:
        attempts = session.scalars(select(Attempt).join(Trial).where(Trial.run_id == run_id)
                                   .order_by(Attempt.started_at)).all()
        assert [a.status for a in attempts] == ["interrupted", "success"]
        assert attempts[0].id == interrupted_id and attempts[0].error["code"] == "interrupted"
        assert session.get(Run, run_id).status == "completed"


def test_killed_worker_memory_episode_restarts_in_fresh_store(settings, ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "memoryai", include=["M03"])
    slow = demo_target(ctx, project, "slow-memory", profile="baseline", delay_ms=0)
    run_id = start_run(ctx, project, suite, {"baseline": slow}, repeats=1)
    # Slow the demo memory backend so the kill lands mid-episode.
    from eval_triage.adapters import demo as demo_module

    original = demo_module.DemoMemoryBackend.execute_action
    env_marker = settings.data_dir / "slow-episode"
    env_marker.write_text("1")
    proc = _spawn_worker_with_slow_episode(settings)
    try:
        _wait_for_running_attempt(ctx, run_id)
    finally:
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
    time.sleep(2.2)
    assert original is demo_module.DemoMemoryBackend.execute_action
    run_all(ctx, seconds=60)
    with ctx.db.read() as session:
        attempts = session.scalars(select(Attempt).join(Trial).where(Trial.run_id == run_id,
                                                                     Attempt.stage == "episode")
                                   .order_by(Attempt.attempt_index)).all()
        assert [a.status for a in attempts] == ["interrupted", "success"]
        assert attempts[0].mutation_outcome_known is False
        trial = session.scalars(select(Trial).where(Trial.run_id == run_id)).one()
        # the successful attempt ran the whole episode from scratch: event ids restart at 1, none duplicated
        assert {step: ids for step, ids in trial.output["event_ids"].items() if ids} == {"e1": [1]}


def _spawn_worker_with_slow_episode(settings):
    code = (
        "import asyncio, sys\n"
        "from eval_triage.adapters import demo\n"
        "orig = demo.DemoMemoryBackend.execute_action\n"
        "async def slow(self, session, step, resolved):\n"
        "    await asyncio.sleep(5)\n"
        "    return await orig(self, session, step, resolved)\n"
        "demo.DemoMemoryBackend.execute_action = slow\n"
        "from eval_triage.cli import main\n"
        "sys.exit(main(['worker', '--worker-id', 'doomed-episode']))\n"
    )
    env = {**os.environ, "EVAL_TRIAGE_DATA_DIR": str(settings.data_dir), "EVAL_TRIAGE_LEASE_SECONDS": "2",
           "EVAL_TRIAGE_HEARTBEAT_SECONDS": "0.5", "EVAL_TRIAGE_WORKER_POLL_SECONDS": "0.05",
           "EVAL_TRIAGE_WORKER_SLOTS": "1"}
    return subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
