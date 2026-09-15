"""Probability Lab API: calibration refuses the test split, fits on the calibration split, and
evaluates raw and calibrated predictions on held-out data with inspectable bins."""

import json

from eval_triage.demo import DEMO_DIR, PREDICTED_AT, _seed_probability
from eval_triage.domain.importers import parse_file
from tests.integration.helpers import make_project, run_all

EVENT = "the generated answer is correct"


def _project_with_records(ctx):
    project = make_project(ctx)
    spec = parse_file(DEMO_DIR / "demo.yaml")["probability"]
    with ctx.db.write() as session:
        _seed_probability(session, project, spec)
    return project


def test_events_quality_and_bin_members(client, ctx):
    project = _project_with_records(ctx)
    events = client.get("/api/v1/probability/events", params={"project_id": project}).json()["data"]
    assert events == [{"event_definition": EVENT, "score_type": "predicted_event_probability",
                       "method": "judge stated confidence (demo)", "predictions": 160, "labels": 160}]
    quality = client.get("/api/v1/probability/quality", params={"project_id": project, "event_definition": EVENT,
                                                                "split": "test"}).json()["data"]
    assert quality["n_records"] == 80 and quality["clusters"] == 40 and quality["is_demo"]
    raw = quality["raw"]
    assert len(raw["bins"]) == 10 and sum(b["count"] for b in raw["bins"]) == 80
    assert 0 <= raw["ece"] <= 1 and raw["selective"]["threshold"] == 0.5
    busiest = max(raw["bins"], key=lambda b: b["count"])
    members = client.get("/api/v1/probability/records", params={
        "project_id": project, "event_definition": EVENT, "external_ids": ",".join(busiest["members"])}).json()
    assert members["meta"]["total"] == busiest["count"]
    empty = client.get("/api/v1/probability/quality", params={"project_id": project, "event_definition": EVENT,
                                                              "split": "nope", "threshold": 1}).json()["data"]
    assert empty["raw"] is None and empty["unavailable_reason"]


def test_calibration_split_rules_and_fit(client, ctx):
    project = _project_with_records(ctx)
    on_test = client.post("/api/v1/calibrations", json={"project_id": project, "event_definition": EVENT,
                                                        "fit_split": "test"})
    assert on_test.status_code == 422
    floor = client.post("/api/v1/calibrations", json={"project_id": project, "event_definition": EVENT,
                                                      "min_clusters": 50}).json()["data"]
    run_all(ctx, seconds=20)
    refused = client.get(f"/api/v1/jobs/{floor['job_id']}").json()["data"]
    assert refused["status"] == "succeeded" and refused["result"]["ok"] is False
    assert "workflow floor" in refused["result"]["error"]  # 40 calibration clusters < requested 50
    started = client.post("/api/v1/calibrations", json={"project_id": project, "event_definition": EVENT,
                                                        "method": "isotonic"}).json()["data"]  # default floor 30
    run_all(ctx, seconds=20)
    job = client.get(f"/api/v1/jobs/{started['job_id']}").json()["data"]
    assert job["result"]["ok"], job
    calibration_id = job["result"]["calibration_id"]
    fitted = client.get(f"/api/v1/calibrations/{calibration_id}").json()["data"]
    assert fitted["validation"]["fit"]["warnings"] and set(fitted["split_hashes"]) == {"calibration", "test"}
    json.dumps(fitted["parameters"])  # plain JSON, no pickle
    both = client.get("/api/v1/probability/quality", params={"project_id": project, "event_definition": EVENT,
                                                             "split": "test", "calibration_id": calibration_id}
                      ).json()["data"]
    assert both["raw"] and both["calibrated"] and both["calibrated"]["brier"] >= 0
    other = client.get("/api/v1/probability/quality", params={"project_id": project, "event_definition": "x",
                                                              "calibration_id": calibration_id})
    assert other.status_code == 422


def test_calibration_import_validates_parameters(client, ctx):
    project = _project_with_records(ctx)
    good = client.post("/api/v1/calibrations/import", json={
        "project_id": project, "event_definition": EVENT, "method": "isotonic",
        "features": {"feature": "raw_feature"},
        "parameters": {"method": "isotonic", "x_thresholds": [0, 1], "y_thresholds": [0.1, 0.9]}})
    assert good.status_code == 201 and good.json()["data"]["source"] == "import"
    bad = client.post("/api/v1/calibrations/import", json={
        "project_id": project, "event_definition": EVENT, "method": "isotonic",
        "features": {"feature": "raw_feature"},
        "parameters": {"method": "isotonic", "x_thresholds": [0, 1], "y_thresholds": [0.9, 0.1]}})
    assert bad.status_code == 422
    assert PREDICTED_AT.year == 2026
