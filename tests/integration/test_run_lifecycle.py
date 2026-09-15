"""Validation, idempotency, cancellation, manifest hashing and secret exclusion."""

import uuid

from sqlalchemy import select

from eval_triage.db.models import Run, Trial
from eval_triage.db.repositories import create_target_config
from tests.conftest import SENTINEL_SECRET
from tests.integration.helpers import demo_target, import_fixture, make_project, run_all, start_run


def _body(project, suite, candidates, repeats=2, **extra):
    return {"project_id": project, "scenario_id": suite["scenario_id"], "dataset_id": suite["dataset_id"],
            "candidates": [{"key": k, "target_config_id": v} for k, v in candidates.items()],
            "execution": {"repeats": repeats}, **extra}


def test_idempotency_same_key_one_run_changed_body_409(client, ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    target = demo_target(ctx, project, "router")
    body = _body(project, suite, {"baseline": target})
    key = str(uuid.uuid4())
    first = client.post("/api/v1/runs", json=body, headers={"Idempotency-Key": key})
    second = client.post("/api/v1/runs", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    changed = client.post("/api/v1/runs", json={**body, "execution": {"repeats": 3}}, headers={"Idempotency-Key": key})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "conflict"
    with ctx.db.read() as session:
        assert len(session.scalars(select(Run)).all()) == 1
    missing = client.post("/api/v1/runs", json=body)
    assert missing.status_code == 422


def test_all_trial_slots_created_up_front(client, ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    a, b = demo_target(ctx, project, "a"), demo_target(ctx, project, "b", profile="candidate")
    run_id = start_run(ctx, project, suite, {"baseline": a, "candidate": b}, repeats=3)
    with ctx.db.read() as session:
        trials = session.scalars(select(Trial).where(Trial.run_id == run_id)).all()
        assert len(trials) == 4 * 2 * 3 == session.get(Run, run_id).planned_trial_count
        assert sorted(t.schedule_order for t in trials) == list(range(24))


def test_unsupported_parameter_fails_before_enqueue(client, ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    seeded = demo_target(ctx, project, "seeded", seed=7)  # the demo adapter declares seed unsupported
    response = client.post("/api/v1/runs/validate", json=_body(project, suite, {"baseline": seeded}))
    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert errors[0]["code"] == "capability_conflict" and errors[0]["field"] == "candidates[0].parameters.seed"
    created = client.post("/api/v1/runs", json=_body(project, suite, {"baseline": seeded}),
                          headers={"Idempotency-Key": str(uuid.uuid4())})
    assert created.status_code == 422
    with ctx.db.read() as session:
        assert session.scalars(select(Run)).first() is None


def test_other_validation_rules(client, ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    memory = import_fixture(ctx, project, "memoryai", include=["M01"])
    target = demo_target(ctx, project, "router")
    cached = client.post("/api/v1/runs/validate", json={**_body(project, suite, {"baseline": target}),
                                                        "execution": {"repeats": 1, "cache_outputs": True}})
    assert cached.status_code == 422
    mismatch = client.post("/api/v1/runs/validate", json={**_body(project, suite, {"baseline": target}),
                                                          "dataset_id": memory["dataset_id"]})
    assert mismatch.status_code == 422
    # Missing provider credentials are covered with the real adapters in test_adapters_*.
    ok = client.post("/api/v1/runs/validate", json=_body(project, suite, {"baseline": target}, repeats=4))
    plan = ok.json()["data"]["plan"]
    assert plan["planned_trials"] == 16 and plan["cost_estimates"]["baseline"]["amount"] == 0.0


def test_cancellation_preserves_partial_results_and_is_never_ready(client, ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    target = demo_target(ctx, project, "router")
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=2)
    response = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert response.status_code == 200
    run_all(ctx, seconds=20)
    body = client.get(f"/api/v1/runs/{run_id}").json()["data"]
    assert body["status"] == "cancelled"
    assert body["trial_counts"] == {"cancelled": 8}
    assert client.post(f"/api/v1/runs/{run_id}/cancel").json()["data"]["status"] == "cancelled"


def test_manifest_hash_tracks_definitions_and_excludes_secrets(client, ctx, monkeypatch):
    monkeypatch.setenv("EVALAI_MANIFEST_KEY", SENTINEL_SECRET)
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    a = demo_target(ctx, project, "router")
    with ctx.db.write() as session:
        b = create_target_config(session, project, name="router", adapter="demo", model="demo-router",
                                 prompt_template="Classify: {input.text}").id
    first = client.post("/api/v1/runs/validate", json=_body(project, suite, {"baseline": a})).json()["data"]
    again = client.post("/api/v1/runs/validate", json=_body(project, suite, {"baseline": a})).json()["data"]
    prompt = client.post("/api/v1/runs/validate", json=_body(project, suite, {"baseline": b})).json()["data"]
    repeats = client.post("/api/v1/runs/validate", json=_body(project, suite, {"baseline": a},
                                                               repeats=3)).json()["data"]
    assert first["manifest_hash"] == again["manifest_hash"]
    assert len({first["manifest_hash"], prompt["manifest_hash"], repeats["manifest_hash"]}) == 3
    subset = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    assert subset["dataset_id"] == suite["dataset_id"]  # identical content reuses the version
    assert SENTINEL_SECRET not in str(first["manifest"])
