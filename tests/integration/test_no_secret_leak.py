"""A secret value from the server environment never reaches responses, artifacts, exports or logs."""

import logging

from eval_triage.adapters import demo as demo_module
from tests.conftest import SENTINEL_SECRET
from tests.integration.helpers import demo_target, import_fixture, make_project, run_all, start_run


def test_sentinel_secret_is_redacted_everywhere(client, ctx, monkeypatch, caplog):
    original = demo_module.DemoAdapter.execute

    async def leaky(self, request, session):
        result = await original(self, request, session)
        result.raw_request = {**(result.raw_request or {}), "headers": {"Authorization": f"Bearer {SENTINEL_SECRET}"}}
        result.raw_response = {**(result.raw_response or {}), "echo": f"key={SENTINEL_SECRET}"}
        return result

    monkeypatch.setattr(demo_module.DemoAdapter, "execute", leaky)
    caplog.set_level(logging.DEBUG)
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml", include=["C01"])
    target = demo_target(ctx, project, "router")
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=1)
    run_all(ctx)

    responses = [client.get(f"/api/v1/runs/{run_id}"), client.get(f"/api/v1/runs/{run_id}/trials"),
                 client.get("/api/v1/health"), client.get("/api/v1/settings"),
                 client.get("/api/v1/target-configs", params={"project_id": project})]
    trial_id = responses[1].json()["data"][0]["id"]
    detail = client.get(f"/api/v1/trials/{trial_id}")
    responses.append(detail)
    for attempt in detail.json()["data"]["attempts"]:
        for key in ("request_artifact", "response_artifact"):
            if attempt[key]:
                artifact = client.get(f"/api/v1/artifacts/{attempt[key]}")
                assert artifact.status_code == 200
                assert "[REDACTED]" in artifact.text
                responses.append(artifact)
    started = client.post("/api/v1/exports", json={"project_id": project}).json()["data"]
    run_all(ctx, seconds=30)
    record = client.get(f"/api/v1/exports/{started['id']}").json()["data"]
    export_bytes = client.get(record["download_url"]).content
    for response in responses:
        assert SENTINEL_SECRET not in response.text
    assert SENTINEL_SECRET.encode() not in export_bytes
    for path in ctx.store.root.rglob("*"):
        if path.is_file():
            assert SENTINEL_SECRET.encode() not in path.read_bytes(), path
    assert SENTINEL_SECRET not in caplog.text
