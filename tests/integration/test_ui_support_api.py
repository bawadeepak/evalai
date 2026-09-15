"""API features the UI relies on: loading the labelled demo, and editing a scenario as a new version."""

from tests.integration.helpers import make_project

DOCUMENT = {
    "schema_version": 1, "name": "routing", "pack": "exact_classification",
    "contract": "Route the message to one queue.", "allowed_labels": ["billing", "other"],
    "graders": [{"name": "label", "kind": "deterministic", "checks": ["label_match"]}],
}


def test_load_demo_is_idempotent(client):
    first = client.post("/api/v1/demo")
    assert first.status_code == 201
    body = first.json()["data"]
    assert body["runs"] and "synthetic" in body["note"].lower()
    again = client.post("/api/v1/demo").json()["data"]
    assert again["project_id"] == body["project_id"]
    assert [r["run_id"] for r in again["runs"]] == [r["run_id"] for r in body["runs"]]
    projects = client.get("/api/v1/projects").json()["data"]
    assert [p["is_demo"] for p in projects if p["id"] == body["project_id"]] == [True]


def test_edit_scenario_as_new_version(client, ctx):
    project = make_project(ctx)
    v1 = client.post("/api/v1/scenarios", json={"project_id": project, "document": DOCUMENT}).json()["data"]["scenario"]
    edited = {**DOCUMENT, "contract": "Route the message to exactly one allowed queue."}
    response = client.post("/api/v1/scenarios", json={"project_id": project, "document": edited,
                                                      "parent_id": v1["id"], "reason": "clarify contract"})
    assert response.status_code == 201
    v2 = response.json()["data"]["scenario"]
    assert v2["logical_id"] == v1["logical_id"] and v2["version"] == 2
    assert v2["parent_id"] == v1["id"] and v2["reason"] == "clarify contract"
    detail = client.get(f"/api/v1/scenarios/{v2['id']}").json()["data"]
    assert [v["version"] for v in detail["versions"]] == [1, 2]
    # the original version is unchanged
    original = client.get(f"/api/v1/scenarios/{v1['id']}").json()["data"]
    assert original["contract"] == DOCUMENT["contract"] and original["version"] == 1
    latest = client.get("/api/v1/scenarios", params={"project_id": project}).json()["data"]
    assert [s["id"] for s in latest] == [v2["id"]]
    missing = client.post("/api/v1/scenarios", json={"project_id": project, "document": edited,
                                                     "parent_id": "does-not-exist"})
    assert missing.status_code == 404
