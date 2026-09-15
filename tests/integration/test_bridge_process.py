"""Bridge process behaviour (fake backend): stdout hygiene, timeouts, crashes, truncation,
test-mode fault injection, ownership-checked clean-up, recycling, and full episodes."""

import asyncio
import json
import os
import signal
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import select

from eval_triage.adapters.memoryai import bridge_client as bc
from eval_triage.adapters.memoryai.bridge_client import BridgeCrashed, BridgeError, BridgeProcess
from eval_triage.db.models import Grade, GraderVersion, MemoryStoreOwnership, Trial
from eval_triage.db.repositories import DefinitionError, create_target_config
from tests.integration.helpers import import_fixture, make_project, run_all, start_run


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _session(settings, env=None, episode="ep", **prepare):
    process = BridgeProcess(settings, "fake", env)
    await process.start()
    prepared = await process.request("prepare", {"episode_id": episode, "stores": ["main"], "nonce": "k" * 32,
                                                 **prepare})
    return process, prepared


def test_stdout_noise_cannot_corrupt_protocol(settings):
    async def go():
        process = BridgeProcess(settings, "fake", {"EVALAI_BRIDGE_TEST_NOISE": "1"})
        await process.start()
        # A print() inside the bridge would go to stderr; the protocol stream stays clean.
        result = await process.request("hello")
        await process.stop()
        return result

    assert _run(go())["backend"] == "fake"


def test_timeout_kills_the_process(settings):
    async def go():
        process, prepared = await _session(settings, {"EVALAI_BRIDGE_TEST_DELAY": "5"})
        with pytest.raises(TimeoutError):
            await process.request("execute_action", {"session_id": prepared["session_id"], "step": {
                "id": "e1", "action": "remember", "store": "main", "args": {"text": "I live in Perth."}}}, timeout=0.5)
        assert not process.alive
        with pytest.raises(BridgeCrashed):
            await process.request("hello")

    _run(go())


def test_process_death_is_reported(settings):
    async def go():
        process, _ = await _session(settings)
        os.kill(process.proc.pid, signal.SIGKILL)
        await asyncio.sleep(0.3)
        with pytest.raises(BridgeCrashed):
            await process.request("hello")

    _run(go())


def test_truncation_detected_and_paged_past(settings):
    async def go():
        process, prepared = await _session(settings, episode="many")
        for i in range(205):
            await process.request("execute_action", {"session_id": prepared["session_id"], "step": {
                "id": f"e{i}", "action": "remember", "store": "main",
                "args": {"text": f"I own vintage camera number {i} from Berlin."}}})
        state = await process.request("inspect_state", {"session_id": prepared["session_id"]})
        await process.stop()
        return state

    state = _run(go())
    assert state["truncated_in_memoryai_state"] is True and state["exhaustive"] is True
    assert len([f for f in state["facts"] if f["state"] == "active"]) == 205


def test_fault_injection_only_in_test_mode(settings):
    async def go():
        process = BridgeProcess(settings, "fake")
        await process.start()
        with pytest.raises(BridgeError) as refused:
            await process.request("prepare", {"episode_id": "f1", "stores": ["main"],
                                              "fault_injection": {"smalltalk": "timeout"}})
        prepared = await process.request("prepare", {"episode_id": "f2", "stores": ["main"], "test_mode": True,
                                                     "fault_injection": {"smalltalk": "timeout"}})
        result = await process.request("execute_action", {"session_id": prepared["session_id"], "step": {
            "id": "e1", "action": "remember", "store": "main",
            "args": {"text": "Thanks! I started a new job at the hospital."}}})
        await process.stop()
        return refused.value, result

    refused, result = _run(go())
    assert refused.type == "not_supported"
    assert result["smalltalk"]["outcome"] == "fallback" and result["smalltalk"]["fault_injected"] == "timeout"


def test_drop_requires_ownership(settings):
    async def go():
        process, prepared = await _session(settings, episode="drop")
        data_dir = prepared["stores"]["main"]["data_dir"]
        await process.request("close", {"session_id": prepared["session_id"], "retain": True})
        errors = []
        for params in ({"data_dir": data_dir, "nonce": "wrong"}, {"data_dir": "/tmp", "nonce": "k" * 32}):
            try:
                await process.request("drop_store", params)
            except BridgeError as exc:
                errors.append(exc.type)
        dropped = await process.request("drop_store", {"data_dir": data_dir, "nonce": "k" * 32})
        await process.stop()
        return errors, dropped, data_dir

    errors, dropped, data_dir = _run(go())
    assert errors == ["isolation_refused", "isolation_refused"]
    assert dropped["removed"] and not Path(data_dir).parent.exists()


def test_pool_recycles_processes(settings):
    async def go():
        pool = bc.BridgePool()
        pool.recycle_after = 2
        key = ("config", "fake")
        pids = []
        for _ in range(3):
            process = await pool.acquire(settings, key, "fake")
            pids.append(process.proc.pid)
            await pool.release(key, process, healthy=True)
        await pool.close_all()
        return pids

    pids = _run(go())
    assert pids[0] == pids[1] and pids[2] != pids[0]


def test_memoryai_config_rules(ctx):
    project = make_project(ctx)
    with ctx.db.write() as session:
        with pytest.raises(DefinitionError, match="local runners"):
            create_target_config(session, project, name="cloud", adapter="memoryai",
                                 memory_config={"llm_base_url": "https://api.example.com/v1"})
        row = create_target_config(session, project, name="m", adapter="memoryai", memory_config={"backend": "fake"})
        assert row.memory_config["llm_model"] == "gemma3:4b" and row.capabilities["episodes"]["state"] == "supported"
        assert row.capabilities["cloud_models_inside_memoryai"]["state"] == "unsupported"


def test_memoryai_episodes_through_the_engine_with_fake_backend(ctx, client):
    project = make_project(ctx)
    cases = ["M01", "M02", "M03", "M04", "M05", "M08", "M10", "M11", "M12", "M15"]
    suite = import_fixture(ctx, project, "memoryai", include=cases)
    with ctx.db.write() as session:
        generation = create_target_config(session, project, name="answers", adapter="demo", model="demo").id
        memory = create_target_config(session, project, name="memoryai (fake bridge)", adapter="memoryai",
                                      memory_config={"backend": "fake", "generation_target_config_id": generation}).id
    missing_generation = None
    with ctx.db.write() as session:
        missing_generation = create_target_config(session, project, name="no-gen", adapter="memoryai",
                                                  memory_config={"backend": "fake"}).id
    rejected = client.post("/api/v1/runs/validate", json={
        "project_id": project, "scenario_id": suite["scenario_id"], "dataset_id": suite["dataset_id"],
        "candidates": [{"key": "baseline", "target_config_id": missing_generation}], "execution": {"repeats": 1}})
    assert rejected.json()["error"]["details"]["errors"][0]["code"] == "generation_target_missing"
    run_id = start_run(ctx, project, suite, {"baseline": memory}, repeats=1)
    run_all(ctx, seconds=180)
    with ctx.db.read() as session:
        rows = session.execute(select(Trial, Grade, GraderVersion).join(Grade, Grade.trial_id == Trial.id)
                               .join(GraderVersion, GraderVersion.id == Grade.grader_id)
                               .where(Trial.run_id == run_id, GraderVersion.name == "memory-contract")).all()
        from eval_triage.db.models import Case

        verdicts = {session.get(Case, t.case_id).external_id: g.verdict for t, g, _ in rows}
        statuses = Counter(t.status for t in session.scalars(select(Trial).where(Trial.run_id == run_id)))
        owned = session.scalars(select(MemoryStoreOwnership).where(MemoryStoreOwnership.run_id == run_id)).all()
    assert statuses == {"success": len(cases)}
    assert verdicts["M01"] == verdicts["M02"] == verdicts["M03"] == verdicts["M05"] == "pass"
    assert verdicts["M08"] == verdicts["M10"] == verdicts["M11"] == verdicts["M15"] == "pass"
    assert verdicts["M04"] == "fail"   # non-Latin fact dropped by the small-talk rule (reproduced quirk)
    assert verdicts["M12"] == "fail"   # facts block not trimmed: used exceeds the 40-token budget
    assert len(owned) == len(cases) + 1 and {o.state for o in owned} == {"retained"}  # M10 has two stores
    detail = client.get(f"/api/v1/trials/{rows[0][0].id}").json()["data"]
    assert detail["output"]["store_close"]["stores"] and detail["steps"]

    from eval_triage.adapters.memoryai.ownership import gc_stores

    plan = gc_stores(ctx.settings, dry_run=True)
    assert plan["dry_run"] and len(plan["stores"]) == len(owned)
    done = gc_stores(ctx.settings, dry_run=False)
    assert all(s["dropped"] for s in done["stores"])
    assert not any(Path(o.data_dir).parent.exists() for o in owned)
    json.dumps(done)
