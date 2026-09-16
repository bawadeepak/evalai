"""Live MemoryAI suite: M01–M15 through the execution engine and the real runtime.

Runs only with ``-m live_memoryai``. It needs the MemoryAI checkout and its
interpreter, Ollama with the configured local model, the cached embedding and
cross-encoder models, and a cached ``cl100k_base`` tokenizer
(``EVAL_TRIAGE_TIKTOKEN_CACHE_DIR``).

Every episode runs in a brand-new isolated store that Eval Triage owns and drops
afterwards; MemoryAI's own data directory is never touched.

The assertions are structural on purpose. Live MemoryAI outcomes are a
measurement, not a contract: the test proves that every episode executed, was
graded, captured its evidence and was cleaned up, and it prints the measured
per-case outcomes for the validation report. It does not assert that any
particular case passes.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import select

from eval_triage.adapters.memoryai.ownership import gc_stores
from eval_triage.db.models import Case, Grade, GraderVersion, MemoryStoreOwnership, Trial, TrialOutcome
from eval_triage.db.repositories import create_target_config
from eval_triage.execution.runs import RunRequest, create_run
from tests.integration.helpers import import_fixture, make_project, run_all

CASES = [f"M{i:02d}" for i in range(1, 16)]
MEMORYAI_PYTHON = Path("/Users/deepakbawa/Documents/AI/memoryai/.venv/bin/python")
OLLAMA = os.environ.get("EVAL_TRIAGE_LIVE_OLLAMA_URL", "http://127.0.0.1:11434/v1")
LOCAL_MODEL = os.environ.get("EVAL_TRIAGE_LIVE_MODEL", "gemma3:4b")

pytestmark = pytest.mark.live_memoryai


def _ollama_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/models", timeout=10) as response:  # noqa: S310 - fixed loopback URL
            models = json.load(response).get("data", [])
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False
    return any(m.get("id") == LOCAL_MODEL for m in models)


@pytest.mark.skipif(not MEMORYAI_PYTHON.exists(), reason="MemoryAI interpreter not found")
@pytest.mark.skipif(not _ollama_ready(), reason=f"Ollama is not serving {LOCAL_MODEL} at {OLLAMA}")
def test_memoryai_lifecycle_suite_against_the_real_runtime(ctx, client):
    project = make_project(ctx, "live memoryai")
    suite = import_fixture(ctx, project, "memoryai", include=CASES)
    with ctx.db.write() as session:
        generation = create_target_config(
            session, project, name=f"local {LOCAL_MODEL}", adapter="openai_compatible", model=LOCAL_MODEL,
            base_url=OLLAMA, parameters={"max_tokens": 200},
            experimental=True,  # a local runner's capabilities are unknown until probed
        ).id
        memory = create_target_config(
            session, project, name="MemoryAI (real runtime)", adapter="memoryai",
            memory_config={"backend": "real", "llm_model": LOCAL_MODEL,
                           "generation_target_config_id": generation},
        ).id

    request = RunRequest(
        project_id=project, scenario_id=suite["scenario_id"], dataset_id=suite["dataset_id"],
        name="live MemoryAI M01-M15", candidates=[{"key": "memoryai", "target_config_id": memory}],
        execution={"repeats": 1, "max_concurrency": 1},
        limits={"timeout_seconds": 900.0},
    )
    _, response = create_run(ctx.db, ctx.settings, request, "live-memoryai-suite")
    run_id = response["data"]["id"]
    run_all(ctx, seconds=5400)

    with ctx.db.read() as session:
        trials = session.scalars(select(Trial).where(Trial.run_id == run_id)).all()
        external = {c.id: c.external_id for c in session.scalars(select(Case))}
        outcomes = {t.id: o for t, o in session.execute(
            select(Trial, TrialOutcome).join(TrialOutcome, TrialOutcome.trial_id == Trial.id)
            .where(Trial.run_id == run_id)).all()}
        contract = {}
        for trial, grade, grader in session.execute(
                select(Trial, Grade, GraderVersion).join(Grade, Grade.trial_id == Trial.id)
                .join(GraderVersion, GraderVersion.id == Grade.grader_id)
                .where(Trial.run_id == run_id)).all():
            contract.setdefault(external[trial.case_id], {})[grader.name] = grade.verdict
        owned = session.scalars(select(MemoryStoreOwnership).where(MemoryStoreOwnership.run_id == run_id)).all()

    measured = {
        external[t.case_id]: {
            "trial_status": t.status,
            "outcome": outcomes[t.id].outcome if t.id in outcomes else None,
            "reason": (outcomes[t.id].reason if t.id in outcomes else None),
            "graders": contract.get(external[t.case_id], {}),
            "error": (t.error or {}).get("code"),
            "state_artifacts": len(t.state_artifacts or []),
            "latency_ms": t.latency_ms,
        }
        for t in trials
    }
    statuses = Counter(t.status for t in trials)
    resolved = sum(1 for m in measured.values() if m["outcome"] in ("pass", "fail"))
    # Printed for the validation report; live outcomes are measurements, not expectations.
    print("LIVE_MEMORYAI_SUMMARY=" + json.dumps(
        {"statuses": dict(statuses), "resolved": resolved, "isolated_stores": len(owned),
         "outcomes": Counter(m["outcome"] for m in measured.values()), "cases": measured}, default=str))

    assert len(trials) == len(CASES), "every case must produce exactly one trial"
    assert statuses["pending"] == 0 and statuses["running"] == 0, f"trials did not finish: {statuses}"
    # At least one isolated store per episode (M10 uses two). An episode that was
    # interrupted restarts in a *fresh* store rather than replaying a mutation, so
    # there can be more; every store must be owned, retained and dropped below.
    assert owned and len(owned) >= len(CASES) + 1, "each episode needs its own isolated store"
    assert {o.state for o in owned} == {"retained"}
    for name, record in measured.items():
        if record["trial_status"] == "success":
            assert record["state_artifacts"], f"{name}: a successful episode must capture its memory state"
    # Plumbing check (not a behaviour claim): grading must reach a verdict for most episodes.
    assert resolved >= len(CASES) * 0.8, f"too many unresolved outcomes: {measured}"

    plan = gc_stores(ctx.settings, dry_run=True)
    assert len(plan["stores"]) == len(owned)
    dropped = gc_stores(ctx.settings, dry_run=False)
    assert all(store["dropped"] for store in dropped["stores"]), dropped
    assert not any(Path(o.data_dir).parent.exists() for o in owned), "isolated stores must be removed"
