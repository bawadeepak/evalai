"""Events are persisted before emission and the SSE stream resumes from Last-Event-ID."""

import json

from tests.integration.helpers import demo_target, import_fixture, make_project, run_all, start_run


def _read_stream(client, url, headers=None):
    events = []
    with client.stream("GET", url, headers=headers or {}) as response:
        assert response.status_code == 200
        current = {}
        for line in response.iter_lines():
            if not line:
                if current:
                    events.append(current)
                    current = {}
                continue
            field, _, value = line.partition(":")
            current[field] = value.strip()
            if current.get("event") == "stream.end" and "data" in current:
                events.append(current)
                break
    return events


def test_stream_replays_and_resumes(client, ctx):
    project = make_project(ctx)
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml", include=["C01", "C02"])
    target = demo_target(ctx, project, "router")
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=1)
    run_all(ctx)
    # The stream only ends once the run is terminal; assert that first so a regression fails fast.
    assert client.get(f"/api/v1/runs/{run_id}").json()["data"]["status"] == "completed"
    events = _read_stream(client, f"/api/v1/runs/{run_id}/events")
    typed = [e for e in events if e.get("event") != "stream.end"]
    names = [e["event"] for e in typed]
    assert names[0] == "run.queued" and "run.started" in names and names[-1] == "run.finished"
    assert "grade.created" in names and "attempt.finished" in names
    ids = [int(e["id"]) for e in typed]
    assert ids == sorted(ids)
    payload = json.loads(typed[-1]["data"])
    assert payload["run_id"] == run_id and payload["payload"]["status"] == "completed"
    middle = ids[len(ids) // 2]
    resumed = [e for e in _read_stream(client, f"/api/v1/runs/{run_id}/events", {"Last-Event-ID": str(middle)})
               if e.get("event") != "stream.end"]
    assert [int(e["id"]) for e in resumed] == [i for i in ids if i > middle]
