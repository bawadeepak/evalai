"""Restarting the API process preserves results, grades, reviews and supersession history."""

from fastapi.testclient import TestClient

from eval_triage.api.app import create_app
from tests.integration.helpers import demo_target, import_fixture, make_project, run_all, start_run


def test_restart_preserves_results_and_reviews(settings):
    first = create_app(settings)
    ctx = first.state.ctx
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "memoryai", include=["M05"])
    target = demo_target(ctx, project, "candidate", profile="candidate")
    run_id = start_run(ctx, project, suite, {"candidate": target}, repeats=2)
    run_all(ctx)
    with TestClient(first) as client:
        trial_id = client.get(f"/api/v1/runs/{run_id}/trials").json()["data"][0]["id"]
        original = client.post("/api/v1/reviews", json={"trial_id": trial_id, "decision": "ambiguous",
                                                        "reviewer": "ana", "explanation": "unclear"}).json()["data"]
        client.post("/api/v1/reviews", json={"trial_id": trial_id, "decision": "confirm_failure", "reviewer": "ana",
                                             "supersedes_id": original["id"]})
        before = {
            "run": client.get(f"/api/v1/runs/{run_id}").json()["data"],
            "summary": client.get(f"/api/v1/runs/{run_id}/summary").json()["data"],
            "trial": client.get(f"/api/v1/trials/{trial_id}").json()["data"],
            "reviews": client.get("/api/v1/reviews", params={"trial_id": trial_id}).json()["data"],
        }
    ctx.db.dispose()

    second = create_app(settings)
    with TestClient(second) as client:
        after = {
            "run": client.get(f"/api/v1/runs/{run_id}").json()["data"],
            "summary": client.get(f"/api/v1/runs/{run_id}/summary").json()["data"],
            "trial": client.get(f"/api/v1/trials/{trial_id}").json()["data"],
            "reviews": client.get("/api/v1/reviews", params={"trial_id": trial_id}).json()["data"],
        }
    second.state.ctx.db.dispose()
    assert after == before
    assert before["run"]["status"] == "completed"
    assert [r["decision"] for r in after["reviews"]] == ["ambiguous", "confirm_failure"]
    assert after["reviews"][0]["superseded_by"] == after["reviews"][1]["id"]
    assert after["trial"]["grades"] and after["summary"]["slot_rates"]["candidate"]["failed"] == 2
