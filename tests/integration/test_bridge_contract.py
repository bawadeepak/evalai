"""One contract suite for every bridge backend.

* ``fake`` — the fake backend in Eval Triage's interpreter (always runs).
* ``fake-memoryai`` — the fake backend in MemoryAI's interpreter, using MemoryAI's
  real event log and small-talk rule (runs when that interpreter exists).
* ``real`` — the real MemoryAI runtime in brand-new isolated stores; needs Ollama
  and runs only with ``-m live_memoryai``.
"""

import asyncio
import json
from pathlib import Path

import pytest

from eval_triage.adapters.memoryai.bridge_client import BridgeError, BridgeProcess

MEMORYAI_PYTHON = Path("/Users/deepakbawa/Documents/AI/memoryai/.venv/bin/python")

BACKENDS = [
    pytest.param(("fake", None), id="fake"),
    pytest.param(("fake", "memoryai"), id="fake-memoryai",
                 marks=pytest.mark.skipif(not MEMORYAI_PYTHON.exists(), reason="MemoryAI interpreter not found")),
    pytest.param(("real", None), id="real", marks=pytest.mark.live_memoryai),
]


class Bridge:
    def __init__(self, settings, backend, python):
        self.settings, self.backend, self.python = settings, backend, python
        self.loop = asyncio.new_event_loop()
        self.process = None

    def start(self):
        import eval_triage.adapters.memoryai.bridge_client as bc

        original = bc.bridge_python
        if self.python == "memoryai":
            bc.bridge_python = lambda settings, backend: str(MEMORYAI_PYTHON)
        try:
            self.process = BridgeProcess(self.settings, self.backend)
            return self.run(self.process.start())
        finally:
            bc.bridge_python = original

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def call(self, command, timeout=600, **params):
        return self.run(self.process.request(command, params, timeout=timeout))

    def stop(self):
        if self.process is not None:
            self.run(self.process.stop())
        self.loop.close()


@pytest.fixture(params=BACKENDS)
def bridge(request, settings):
    backend, python = request.param
    b = Bridge(settings, backend, python)
    b.start()
    try:
        yield b
    finally:
        _drop_retained_stores(b, settings)
        b.stop()


def _drop_retained_stores(bridge, settings) -> None:
    """These tests close with ``retain=True`` on purpose; their database is a temporary
    one, so ``evalai memoryai gc`` would have no record of the stores. Drop them here
    (ownership-checked) so a live run leaves no Postgres instances behind."""
    root = settings.memoryai_stores_dir
    for manifest_path in sorted(root.glob("*/*/.evalai-owned.json")) if root.exists() else []:
        manifest = json.loads(manifest_path.read_text())
        try:
            bridge.call("drop_store", timeout=300, data_dir=str(manifest_path.parent / "data"),
                        nonce=manifest["nonce"])
        except BridgeError as exc:  # reported, never fatal: the test's own assertions matter
            print(f"could not drop {manifest_path.parent}: {exc}")


def _prepare(bridge, episode="ep1", stores=("main",), **extra):
    return bridge.call("prepare", episode_id=episode, stores=list(stores), nonce="n" * 32,
                       settings={"small_talk_filter": True}, **extra)


def _act(bridge, session, action, step_id, store="main", resolved=None, **args):
    return bridge.call("execute_action", session_id=session, resolved=resolved or {},
                       step={"id": step_id, "action": action, "store": store, "args": args})


def test_hello_and_isolation(bridge, settings):
    assert bridge.process.hello["protocol_version"] == 1
    prepared = _prepare(bridge)
    info = prepared["stores"]["main"]
    data_dir = Path(info["data_dir"])
    assert settings.memoryai_stores_dir.resolve() in data_dir.parents
    manifest = json.loads((data_dir.parent / ".evalai-owned.json").read_text())
    assert manifest["nonce"] == "n" * 32 and manifest["instance"] == info["instance"]
    with pytest.raises(BridgeError) as reused:
        _prepare(bridge)
    assert reused.value.type == "isolation_refused"
    with pytest.raises(BridgeError) as escape:
        bridge.call("prepare", episode_id="../escape", stores=["main"])
    assert escape.value.type == "isolation_refused"
    with pytest.raises(BridgeError) as clear:
        bridge.call("clear")
    assert clear.value.type == "protocol_error"
    bridge.call("close", session_id=prepared["session_id"], retain=True)


def test_lifecycle_contract(bridge):
    session = _prepare(bridge, "ep2")["session_id"]
    first = _act(bridge, session, "remember", "e1", text="I live in Sydney and work as a nurse.")
    assert first["new_event_ids"] == [1] and first["message"] == "remembered turn 1"
    assert first["smalltalk"]["outcome"] == "kept"
    thanks = _act(bridge, session, "remember", "e2", text="Thanks!")
    assert thanks["smalltalk"] == {**thanks["smalltalk"], "outcome": "skipped", "method": "rule"}
    non_latin = _act(bridge, session, "remember", "e3", text="我住在悉尼。")
    assert non_latin["smalltalk"]["method"] == "rule"  # MemoryAI's rule: no Latin words -> all([]) -> filler
    candidate = _act(bridge, session, "assert", "c1", text="The user is allergic to peanuts.", status="candidate")
    assert candidate["message"].startswith("asserted") and len(candidate["new_event_ids"]) == 1
    rejected = _act(bridge, session, "reject", "x1", resolved={"target_event_id": candidate["new_event_ids"][0]})
    assert rejected["message"] == "rejected"
    state = bridge.call("inspect_state", session_id=session)
    active = [f for f in state["facts"] if f["state"] == "active"]
    assert active and all(f["source_event_id"] == 1 for f in active)
    assert state["exhaustive"] is True and state["truncated_in_memoryai_state"] is False
    assert not any("peanut" in f["claim"].lower() for f in active)
    recall = _act(bridge, session, "recall", "r1", query="Where do I live?", level="mid", budget=400)
    assert recall["context"].startswith("## What is known about this person")
    assert recall["window_verified"] is True and recall["used"] == recall["token_counts"]["total"]
    assert all(line["hit_id"] for line in recall["facts"])
    assert any(line["source_event_id"] == 1 for line in recall["facts"])
    wrong = _act(bridge, session, "wrong", "w1", resolved={"target_event_id": 1}, step="e1", claim_contains="")
    assert wrong["memory_id"] and wrong["document_id"] == "turn-1"
    rebuilt = _act(bridge, session, "rebuild", "b1")
    assert rebuilt["message"].startswith("rebuilt:") and isinstance(rebuilt["unresolved"], list)
    after = bridge.call("inspect_state", session_id=session)
    before_ids = {f["memory_id"] for f in state["facts"]}
    assert not before_ids & {f["memory_id"] for f in after["facts"]}  # rebuild regenerates fact ids
    forgotten = _act(bridge, session, "forget", "f1", resolved={"target_event_id": 1})
    assert forgotten["message"] == "forgot event 1"
    final = bridge.call("inspect_state", session_id=session)
    assert not [f for f in final["facts"] if f["source_event_id"] == 1]
    closed = bridge.call("close", session_id=session, retain=True)
    assert closed["stores"]["main"]["retained"] is True and closed["stores"]["main"]["events"]


def test_two_stores_are_isolated(bridge):
    session = _prepare(bridge, "ep3", stores=("alex", "alexa"))["session_id"]
    _act(bridge, session, "remember", "e1", store="alex", text="My name is Alex Chen and I live in Hobart.")
    _act(bridge, session, "remember", "e2", store="alexa", text="My name is Alexa Chen and I live in Darwin.")
    recall = _act(bridge, session, "recall", "r1", store="alex", query="Where does Alex Chen live?", budget=400)
    assert "darwin" not in recall["context"].lower()
    alexa = bridge.call("inspect_state", session_id=session, store="alexa")
    assert all(e["text"].startswith("My name is Alexa") for e in alexa["events"])
    bridge.call("close", session_id=session, retain=True)
