"""Append-only reviews, adjudication, and the demo triage journey:
inspect stable-wrong M05 -> confirm -> promote -> rerun -> compare."""

import uuid

from sqlalchemy import select

from eval_triage.db.models import Case, Trial
from tests.integration.helpers import demo_target, import_fixture, make_project, run_all, start_run


def _memory_run(ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "memoryai", include=["M03", "M05"], judge="judge")
    baseline = demo_target(ctx, project, "baseline", profile="baseline")
    candidate = demo_target(ctx, project, "candidate", profile="candidate")
    run_id = start_run(ctx, project, suite, {"baseline": baseline, "candidate": candidate}, repeats=3)
    run_all(ctx)
    return project, suite, run_id, {"baseline": baseline, "candidate": candidate}


def test_reviews_append_supersede_and_adjudicate(client, ctx):
    project, suite, run_id, _ = _memory_run(ctx)
    queue = client.get(f"/api/v1/runs/{run_id}/triage").json()["data"]
    top = queue["items"][0]
    assert top["external_id"] == "M05" and top["candidate_key"] == "candidate"
    assert top["priority_label"] == "critical failure" and top["flags"]["stable_wrong"]
    trial_id = top["representative_trial_id"]

    missing_reason = client.post("/api/v1/reviews", json={"trial_id": trial_id, "decision": "ambiguous",
                                                           "reviewer": "ana"})
    assert missing_reason.status_code == 422
    first = client.post("/api/v1/reviews", json={"trial_id": trial_id, "decision": "grader_incorrect",
                                                  "reviewer": "ana", "explanation": "check wording"}).json()["data"]
    second = client.post("/api/v1/reviews", json={"trial_id": trial_id, "decision": "confirm_failure",
                                                   "reviewer": "ana", "supersedes_id": first["id"]}).json()["data"]
    again = client.post("/api/v1/reviews", json={"trial_id": trial_id, "decision": "acceptable_variation",
                                                  "reviewer": "bo", "supersedes_id": first["id"]})
    assert again.status_code == 409
    history = client.get("/api/v1/reviews", params={"trial_id": trial_id}).json()["data"]
    assert [r["decision"] for r in history] == ["grader_incorrect", "confirm_failure"]
    assert history[0]["superseded_by"] == second["id"]
    view = client.get(f"/api/v1/trials/{trial_id}/adjudicated").json()["data"]
    assert view["machine_outcome"] == "fail" and view["adjudicated_outcome"] == "fail"
    assert view["human_review"]["id"] == second["id"]
    detail = client.get(f"/api/v1/trials/{trial_id}").json()["data"]
    assert detail["grades"]  # grades are untouched by reviews
    filtered = client.get(f"/api/v1/runs/{run_id}/triage", params={"review": "confirmed"}).json()["data"]
    assert [i["external_id"] for i in filtered["items"]] == ["M05"]


def test_promote_rerun_compare_journey(client, ctx):
    project, suite, run_id, targets = _memory_run(ctx)
    item = next(i for i in client.get(f"/api/v1/runs/{run_id}/triage").json()["data"]["items"]
                if i["external_id"] == "M05")
    trial_id = item["representative_trial_id"]
    review = client.post("/api/v1/reviews", json={"trial_id": trial_id, "decision": "confirm_failure",
                                                   "reviewer": "ana"}).json()["data"]
    with ctx.db.read() as session:
        case = session.get(Case, session.get(Trial, trial_id).case_id)
        expected = case.expected
    bad = client.post("/api/v1/regressions", json={"run_id": run_id, "items": [
        {"trial_id": trial_id, "review_id": review["id"], "expected": {"nonsense": True}}]})
    assert bad.status_code == 422
    promoted = client.post("/api/v1/regressions", json={"run_id": run_id, "name": "memory regressions", "items": [
        {"trial_id": trial_id, "review_id": review["id"], "expected": expected}]})
    assert promoted.status_code == 201
    dataset = promoted.json()["data"]["dataset"]
    assert dataset["case_count"] == 1 and dataset["provenance"]["items"][0]["review_id"] == review["id"]
    with ctx.db.read() as session:
        assert len(session.scalars(select(Trial).where(Trial.run_id == run_id)).all()) == 12  # source unchanged

    rerun = client.post("/api/v1/runs", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
        "project_id": project, "scenario_id": suite["scenario_id"], "dataset_id": dataset["id"],
        "candidates": [{"key": "candidate", "target_config_id": targets["candidate"]}],
        "execution": {"repeats": 3}}).json()["data"]
    run_all(ctx)
    compared = client.post("/api/v1/comparisons", json={
        "project_id": project, "baseline_run_id": run_id, "baseline_key": "baseline",
        "candidate_run_id": rerun["id"], "candidate_key": "candidate"}).json()["data"]
    assert compared["compatibility"]["compatible"] is True
    assert compared["pairing"]["pairs"] == ["M05"]
    assert {e["external_id"]: e["reason"] for e in compared["exclusions"]} == {"M03": "missing_in_candidate"}
    assert compared["decision"]["verdict"] in ("blocked", "inconclusive")
    reasons = " ".join(compared["decision"]["reasons"])
    assert "paired coverage" in reasons and "independent clusters" in reasons

    more = client.post(f"/api/v1/runs/{run_id}/more-trials", json={"case_ids": ["M05"], "repeats": 2})
    assert more.status_code == 201
    linked = client.get(f"/api/v1/runs/{more.json()['data']['id']}").json()["data"]
    assert linked["parent_run_id"] == run_id and linked["planned_trial_count"] == 4
