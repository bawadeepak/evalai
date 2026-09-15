"""Regrading reuses immutable outputs and makes exactly zero target calls."""

from sqlalchemy import select

from eval_triage.adapters import demo as demo_module
from eval_triage.db.models import Grade, GradingRun, Trial
from tests.integration.helpers import demo_target, import_fixture, make_project, outcomes, run_all, start_run


def test_regrade_makes_no_target_calls(client, ctx, monkeypatch):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    target = demo_target(ctx, project, "router")
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=2)
    calls = {"n": 0}
    original = demo_module.DemoAdapter.execute

    async def spy(self, request, session):
        calls["n"] += 1
        return await original(self, request, session)

    monkeypatch.setattr(demo_module.DemoAdapter, "execute", spy)
    run_all(ctx)
    assert calls["n"] == 8
    with ctx.db.read() as session:
        outputs_before = {t.id: t.output for t in session.scalars(select(Trial).where(Trial.run_id == run_id))}

    calls["n"] = 0
    response = client.post("/api/v1/grading-runs", json={"run_id": run_id, "grader_ids": suite["grader_ids"]})
    assert response.status_code == 201
    grading_id = response.json()["data"]["id"]
    run_all(ctx)
    assert calls["n"] == 0
    with ctx.db.read() as session:
        assert session.get(GradingRun, grading_id).status == "completed"
        regraded = session.scalars(select(Grade).where(Grade.grading_run_id == grading_id)).all()
        assert len(regraded) == 8
        assert {t.id: t.output for t in session.scalars(select(Trial).where(Trial.run_id == run_id))} == outputs_before
    assert outcomes(ctx, run_id, grading_id) == outcomes(ctx, run_id)
