"""Definition routes, envelopes, versioning and validation errors."""

import uuid

from eval_triage.domain.fixtures import FIXTURES_DIR, load_source


def _project(client, name="API project"):
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["data"]["id"]


def test_projects_and_reference_vocabularies(client):
    project = _project(client)
    assert client.get("/api/v1/projects").json()["data"][0]["id"] == project
    detail = client.get(f"/api/v1/projects/{project}").json()["data"]
    assert detail["counts"] == {"scenarios": 0, "datasets": 0, "runs": 0, "target_configs": 0}
    packs = client.get("/api/v1/packs").json()["data"]
    assert len(packs["packs"]) == 9 and any(c["name"] == "recall_budget" for c in packs["checks"])
    assert any(m["name"] == "wilson_interval" for m in client.get("/api/v1/metrics").json()["data"])
    adapters = {a["name"]: a for a in client.get("/api/v1/adapters").json()["data"]}
    assert adapters["demo"]["credential_default_status"] == "not_required"
    assert client.get("/api/v1/projects/missing").json()["error"]["code"] == "not_found"
    assert client.post("/api/v1/projects", json={"name": ""}).status_code == 422


def test_scenario_validate_create_and_identical_content_reuse(client):
    project = _project(client)
    document = load_source(FIXTURES_DIR / "packs" / "exact_classification" / "scenario.yaml")
    report = client.post("/api/v1/scenarios/validate", json={"document": document}).json()["data"]
    assert report["ok"] and report["case_count"] == 4
    bad = client.post("/api/v1/scenarios/validate", json={"document": {**document, "pack": "nope"}}).json()["data"]
    assert not bad["ok"] and bad["errors"]
    first = client.post("/api/v1/scenarios", json={"project_id": project, "document": document})
    assert first.status_code == 201
    created = first.json()["data"]
    again = client.post("/api/v1/scenarios", json={"project_id": project, "document": document}).json()["data"]
    assert again["scenario"]["id"] == created["scenario"]["id"]
    assert again["dataset"]["id"] == created["dataset"]["id"]
    rejected = client.post("/api/v1/scenarios", json={"project_id": project, "document": {**document, "graders": []}})
    assert rejected.status_code == 422 and rejected.json()["error"]["details"]["errors"]
    listed = client.get("/api/v1/scenarios", params={"project_id": project}).json()["data"]
    assert len(listed) == 1 and listed[0]["case_count"] == 4
    detail = client.get(f"/api/v1/scenarios/{created['scenario']['id']}").json()["data"]
    assert detail["graders"][0]["name"] == "label" and detail["definition"]["allowed_labels"]


def test_datasets_versions_cases_split_and_export(client):
    project = _project(client)
    document = load_source(FIXTURES_DIR / "packs" / "probability_calibration" / "scenario.yaml")
    created = client.post("/api/v1/scenarios", json={"project_id": project, "document": document}).json()["data"]
    scenario_id, dataset = created["scenario"]["id"], created["dataset"]
    cases = client.get(f"/api/v1/datasets/{dataset['id']}/cases", params={"limit": 2}).json()
    assert len(cases["data"]) == 2 and cases["meta"]["total"] == 4 and cases["meta"]["next_cursor"] == "2"
    exported = client.get(f"/api/v1/datasets/{dataset['id']}/export").json()["data"]
    edited = [dict(c) for c in exported] + [{"external_id": "K05", "cluster_id": "refund-conv-05", "split": "test",
                                             "input": {"question": "My order never arrived."},
                                             "expected": {"label": 1}, "tags": {"channel": "email"}}]
    invalid = client.post("/api/v1/datasets/validate", json={"scenario_id": scenario_id,
                                                              "cases": edited + [{"external_id": "K06"}]}).json()["data"]
    assert not invalid["ok"] and {e["row"] for e in invalid["errors"]} == {5}
    version = client.post("/api/v1/datasets", json={"project_id": project, "scenario_id": scenario_id,
                                                     "name": dataset["name"], "cases": edited,
                                                     "parent_id": dataset["id"], "reason": "add K05"})
    assert version.status_code == 201
    v2 = version.json()["data"]
    assert v2["version"] == 2 and v2["logical_id"] == dataset["logical_id"] and v2["parent_id"] == dataset["id"]
    assert client.get(f"/api/v1/datasets/{dataset['id']}").json()["data"]["case_count"] == 4  # v1 unchanged
    preview = client.post(f"/api/v1/datasets/{v2['id']}/split", json={"fractions": {"calibration": 0.6, "test": 0.4}})
    assert preview.json()["data"]["dry_run"] and preview.json()["data"]["split_manifest"]["leaking_clusters"] == []
    jsonl = client.get(f"/api/v1/datasets/{v2['id']}/export", params={"format": "jsonl"})
    assert jsonl.status_code == 200 and len(jsonl.text.strip().splitlines()) == 5


def test_text_import_formats_and_errors(client):
    project = _project(client)
    yaml_text = (FIXTURES_DIR / "packs" / "reference_answer" / "scenario.yaml").read_text()
    imported = client.post("/api/v1/imports/documents", json={"project_id": project, "filename": "qa.yaml",
                                                              "content": yaml_text})
    assert imported.status_code == 201
    scenario_id = imported.json()["data"]["scenario"]["id"]
    jsonl = '{"external_id": "X1", "input": {"question": "q?"}, "expected": {"reference": "a"}}\n'
    cases = client.post("/api/v1/imports/documents", json={"project_id": project, "filename": "extra.jsonl",
                                                           "content": jsonl, "scenario_id": scenario_id})
    assert cases.status_code == 201 and cases.json()["data"]["dataset"]["case_count"] == 1
    broken = client.post("/api/v1/imports/documents", json={"project_id": project, "filename": "b.jsonl",
                                                            "content": '{"a": 1}\n{bad', "scenario_id": scenario_id})
    assert broken.status_code == 422 and broken.json()["error"]["details"]["line"] == 2
    unsafe = client.post("/api/v1/imports/documents", json={"project_id": project, "filename": "x.yaml",
                                                            "content": "!!python/object/apply:os.system ['id']"})
    assert unsafe.status_code == 422


def test_target_configs_graders_policies(client):
    project = _project(client)
    target = client.post("/api/v1/target-configs", json={"project_id": project, "name": "router", "adapter": "demo",
                                                         "model": "demo-router", "credential_ref": "EVALAI_TEST_SECRET"})
    assert target.status_code == 201
    body = target.json()["data"]
    assert body["credential_status"] == "set" and body["capabilities"]["seed"]["state"] == "unsupported"
    edited = client.post("/api/v1/target-configs", json={"project_id": project, "name": "router", "adapter": "demo",
                                                          "model": "demo-router-2", "parent_id": body["id"]}).json()
    assert edited["data"]["version"] == 2 and edited["data"]["logical_id"] == body["logical_id"]
    for bad in ({"credential_ref": "sk-live-abcdefghijklmnopqrstuvwxyz0123456789"}, {"adapter": "unknown"}):
        response = client.post("/api/v1/target-configs", json={"project_id": project, "name": "x", "adapter": "demo",
                                                               **bad})
        assert response.status_code == 422
    caps = client.get(f"/api/v1/target-configs/{body['id']}/capabilities").json()["data"]
    assert caps["parameter_capabilities"]["seed"] == "seed"
    grader = client.post("/api/v1/graders", json={"project_id": project, "spec": {
        "name": "judge-x", "kind": "model", "rubric": "Is it correct?"}, "judge_config_id": body["id"]})
    assert grader.status_code == 201 and grader.json()["data"]["output_schema"]["required"] == ["verdict",
                                                                                                "explanation"]
    assert client.post("/api/v1/graders", json={"project_id": project, "spec": {"name": "x", "kind": "model"}}
                       ).status_code == 422
    policy = client.post("/api/v1/release-policies", json={"project_id": project, "name": "p", "policy": {
        "metrics": [{"name": "case_pass_rate", "direction": "higher_is_better", "margin": 0.02}]}})
    assert policy.status_code == 201
    assert client.post("/api/v1/release-policies", json={"project_id": project, "name": "p", "policy": {
        "metrics": [{"name": "x", "direction": "sideways"}]}}).status_code == 422


def test_connection_test_job_and_settings(client, ctx):
    from tests.integration.helpers import run_all

    project = _project(client)
    target = client.post("/api/v1/target-configs", json={"project_id": project, "name": "t", "adapter": "demo",
                                                         "model": "demo"}).json()["data"]
    test = client.post(f"/api/v1/target-configs/{target['id']}/connection-tests")
    assert test.status_code == 202
    run_all(ctx, seconds=20)
    result = client.get(f"/api/v1/connection-tests/{test.json()['data']['id']}").json()["data"]
    assert result["status"] == "success" and result["result"]["latency_ms"] >= 0
    settings = client.get("/api/v1/settings").json()["data"]
    assert settings["retention"]["orphans"] == {"files_without_rows": 0, "rows_without_files": 0}
    assert settings["pricing"]["entries"][0]["adapter"] == "demo"
    updated = client.put("/api/v1/settings/pricing", json={"as_of": "2026-09-15", "entries": [
        {"adapter": "openai", "model": "example-*", "currency": "USD", "input_per_million": 1,
         "output_per_million": 2}]}).json()["data"]
    assert any(e["adapter"] == "openai" for e in updated["entries"])


def test_runs_list_pagination(client, ctx):
    from tests.integration.helpers import demo_target, import_fixture, start_run

    project = _project(client)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    target = demo_target(ctx, project, "router")
    ids = [start_run(ctx, project, suite, {"baseline": target}, repeats=1, key=str(uuid.uuid4())) for _ in range(3)]
    first = client.get("/api/v1/runs", params={"project_id": project, "limit": 2}).json()
    assert len(first["data"]) == 2 and first["meta"]["next_cursor"]
    second = client.get("/api/v1/runs", params={"project_id": project, "limit": 2,
                                                "cursor": first["meta"]["next_cursor"]}).json()
    assert {r["id"] for r in first["data"] + second["data"]} == set(ids) and second["meta"]["next_cursor"] is None
    assert client.get("/api/v1/runs", params={"limit": 500}).status_code == 422
