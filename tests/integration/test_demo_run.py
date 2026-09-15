"""The labelled demo seeds, executes and grades end to end; triage counts come from stored grades."""

from collections import Counter

from sqlalchemy import select

from eval_triage.db.models import Grade, Run, Trial
from eval_triage.demo import seed_demo
from tests.integration.helpers import outcomes, run_all


def test_demo_seed_run_and_documented_counts(settings, ctx, client):
    summary = seed_demo(settings, ctx)
    again = seed_demo(settings, ctx)  # idempotent: same project and runs
    assert again["project_id"] == summary["project_id"]
    assert [r["run_id"] for r in again["runs"]] == [r["run_id"] for r in summary["runs"]]
    assert again["probability_records_added"] == 0

    run_all(ctx, seconds=120)
    memory_run, routing_run = (r["run_id"] for r in summary["runs"])

    counts = outcomes(ctx, memory_run)
    passes = {key: Counter(values)["pass"] for key, values in counts.items()}
    assert passes[("M03", "candidate")] == 18
    assert passes[("M06", "candidate")] == 16
    assert passes[("M05", "candidate")] == 0
    for case in ("M03", "M06", "M05"):
        assert passes[(case, "baseline")] == 20
        assert len(counts[(case, "candidate")]) == 20

    body = client.get(f"/api/v1/runs/{memory_run}").json()["data"]
    assert body["is_demo"] and "synthetic" in body["demo_notice"]
    # the scheduled demo judge failure is a grading error, so the run completes with errors
    assert body["status"] == "completed_with_errors"
    with ctx.db.read() as session:
        errors = session.scalars(select(Grade).join(Trial).where(Trial.run_id == memory_run,
                                                                 Grade.verdict == "error")).all()
        assert len(errors) == 1 and errors[0].error["code"] == "invalid_judge_output"
        assert len(errors[0].judge_attempts) == 2

    routing = {key: values for key, values in outcomes(ctx, routing_run).items()}
    assert routing[("R07", "baseline")] == ["fail"] * 5
    assert routing[("R07", "candidate")] == ["pass"] * 5
    assert routing[("R19", "candidate")] == ["fail"] * 5
    assert routing[("R15", "candidate")][2] == "fail"  # malformed output is a model failure
    assert routing[("R20", "candidate")][4] == "unresolved"  # provider error: no output to grade
    with ctx.db.read() as session:
        statuses = Counter(t.status for t in session.scalars(select(Trial).where(Trial.run_id == routing_run)))
        assert statuses["invalid_output"] == 1 and statuses["provider_error"] == 1
        assert session.get(Run, routing_run).status == "completed_with_errors"

    trials = client.get(f"/api/v1/runs/{memory_run}/trials").json()
    assert len(trials["data"]) == 120
    detail = client.get(f"/api/v1/trials/{trials['data'][0]['id']}").json()["data"]
    assert detail["output"]["stores"]["main"]["backend"] == "demo"
    assert detail["attempts"] and detail["grades"]
    # The detail's headline outcome is the latest grading run's outcome, not "unknown".
    assert detail["outcome"] == detail["outcomes"][-1]["outcome"] and detail["outcome"] in ("pass", "fail")
    artifact = client.get(f"/api/v1/artifacts/{detail['output_artifacts'][0]}")
    assert artifact.status_code == 200 and artifact.headers["content-type"].startswith("application/json")
