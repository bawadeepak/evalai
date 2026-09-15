"""Portable export and safe import round-trip; unsafe archives are rejected."""

import io
import json
import zipfile
from datetime import UTC, datetime

from sqlalchemy import select

from eval_triage.artifacts import exchange
from eval_triage.db.models import Grade, ProbabilityRecord, Review, Trial
from tests.integration.helpers import demo_target, import_fixture, make_project, run_all, start_run


def _seeded_project(ctx, client):
    project = make_project(ctx, "Exportable")
    suite = import_fixture(ctx, project, "packs/exact_classification/scenario.yaml")
    target = demo_target(ctx, project, "router")
    run_id = start_run(ctx, project, suite, {"baseline": target}, repeats=2)
    run_all(ctx)
    trial = client.get(f"/api/v1/runs/{run_id}/trials").json()["data"][0]
    client.post("/api/v1/reviews", json={"trial_id": trial["id"], "decision": "acceptable_variation",
                                         "reviewer": "ana"})
    with ctx.db.write() as session:
        session.add(ProbabilityRecord(project_id=project, external_id="p1", cluster_id="c1", split="test",
                                      event_definition="answer is correct", score_type="predicted_event_probability",
                                      method="none", source_version="v0", predicted_at=datetime(2026, 1, 1, tzinfo=UTC),
                                      probability=None, unavailable_reason="target returned no probability"))
    return project, run_id


def _export(client, ctx, project, **options):
    started = client.post("/api/v1/exports", json={"project_id": project, **options})
    assert started.status_code == 202
    run_all(ctx, seconds=30)
    record = client.get(f"/api/v1/exports/{started.json()['data']['id']}").json()["data"]
    assert record["status"] == "completed", record
    return client.get(record["download_url"]).content, record


def test_round_trip_into_new_project_preserves_evidence(client, ctx):
    project, run_id = _seeded_project(ctx, client)
    data, record = _export(client, ctx, project)
    assert record["summary"]["counts"]["trials"] == 8 and record["summary"]["artifacts"] > 0
    validated = client.post("/api/v1/imports/validate", content=data,
                            headers={"content-type": "application/zip"}).json()["data"]
    assert validated["ok"] and validated["source"]["project_id"] == project
    started = client.post("/api/v1/imports", content=data, params={"name": "Copy"},
                          headers={"content-type": "application/zip"})
    assert started.status_code == 202
    run_all(ctx, seconds=30)
    result = client.get(f"/api/v1/imports/{started.json()['data']['id']}").json()["data"]
    assert result["status"] == "completed", result
    new_project = result["project_id"]
    assert new_project != project
    detail = client.get(f"/api/v1/projects/{new_project}").json()["data"]
    assert detail["name"] == "Copy" and detail["source_identity"]["project_id"] == project
    runs = client.get("/api/v1/runs", params={"project_id": new_project}).json()["data"]
    assert len(runs) == 1 and runs[0]["id"] != run_id and runs[0]["status"] == "completed"
    with ctx.db.read() as session:
        new_trials = session.scalars(select(Trial).where(Trial.run_id == runs[0]["id"])).all()
        assert len(new_trials) == 8 and all(t.output_artifacts for t in new_trials)
        assert session.scalars(select(Grade).where(Grade.trial_id.in_([t.id for t in new_trials]))).all()
        assert session.scalars(select(Review).where(Review.trial_id.in_([t.id for t in new_trials]))).all()
        copied = session.scalars(select(ProbabilityRecord).where(ProbabilityRecord.project_id == new_project)).one()
        assert copied.probability is None and copied.unavailable_reason == "target returned no probability"
    summary = client.get(f"/api/v1/runs/{runs[0]['id']}/summary").json()["data"]
    assert summary["slot_rates"]["baseline"]["passed"] == 8
    # importing twice never overwrites: a second namespace is created
    second = client.post("/api/v1/imports", content=data, headers={"content-type": "application/zip"})
    run_all(ctx, seconds=30)
    assert client.get(f"/api/v1/imports/{second.json()['data']['id']}").json()["data"]["project_id"] not in (
        project, new_project)


def test_redacted_export_excludes_text(client, ctx):
    project, _ = _seeded_project(ctx, client)
    data, record = _export(client, ctx, project, redact_text=True)
    assert record["summary"]["redaction"]["text_excluded"] is True
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert not [n for n in archive.namelist() if n.startswith("artifacts/")]
    cases = json.loads(archive.read("records/cases.json"))
    assert all(c["input"] == exchange.REDACTED for c in cases)
    assert "charged twice" not in data.decode("latin-1")


def _zip(members: dict[str, bytes], manifest: dict | None = None, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        checksums = {name: __import__("hashlib").sha256(data).hexdigest() for name, data in members.items()}
        base = {"schema_version": 1, "app": "eval-triage", "exported_at": "2026-01-01T00:00:00Z",
                "source": {"project_id": "p", "name": "n"}, "counts": {}, "checksums": checksums}
        archive.writestr("manifest.json", json.dumps(manifest or base))
        for name, data in members.items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


def test_unsafe_archives_rejected(client, monkeypatch):
    def rejected(data: bytes, fragment: str):
        response = client.post("/api/v1/imports/validate", content=data, headers={"content-type": "application/zip"})
        assert response.status_code == 422, response.text
        assert fragment in response.json()["error"]["message"]

    rejected(b"not a zip", "not a valid ZIP")
    rejected(_zip({"../evil.json": b"[]"}), "unsafe path")
    rejected(_zip({}, symlink="records/link.json"), "symlinks")
    rejected(_zip({"records/payload.py": b"print(1)"}), "executable")
    rejected(_zip({"records/cases.json": b"[NaN]"}), "invalid JSON")
    tampered = _zip({"records/cases.json": b"[]"}, manifest={"schema_version": 1, "app": "eval-triage",
                                                             "source": {"project_id": "p", "name": "n"},
                                                             "checksums": {"records/cases.json": "0" * 64}})
    rejected(tampered, "checksum")
    rejected(_zip({"artifacts/" + "a" * 64: b"x"}), "does not match its address")
    monkeypatch.setattr(exchange, "MAX_MEMBER_BYTES", 5)
    rejected(_zip({"records/cases.json": b"[1, 2, 3, 4]"}), "size limit")
