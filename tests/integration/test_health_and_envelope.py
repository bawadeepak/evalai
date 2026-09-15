from datetime import timedelta

from eval_triage.db.models import WorkerHeartbeat
from eval_triage.db.types import utcnow


def test_health_reports_components_without_secrets(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    data = body["data"]
    assert data["api"]["status"] == "ok"
    assert data["database"]["status"] == "ok"
    assert data["database"]["journal_mode"] == "wal"
    assert data["worker"]["status"] == "absent"
    assert "inspect" in data["plugins"]
    assert "sk-" not in response.text
    assert response.headers["x-request-id"]


def test_worker_heartbeat_freshness(client, ctx):
    with ctx.db.write() as s:
        s.add(WorkerHeartbeat(worker_id="w1", pid=1, heartbeat_at=utcnow()))
    assert client.get("/api/v1/health").json()["data"]["worker"]["status"] == "ok"
    with ctx.db.write() as s:
        s.get(WorkerHeartbeat, "w1").heartbeat_at = utcnow() - timedelta(minutes=5)
    assert client.get("/api/v1/health").json()["data"]["worker"]["status"] == "stale"


def test_error_envelope_for_unknown_route(client):
    response = client.get("/api/v1/does-not-exist", headers={"x-request-id": "req-1"})
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found", "details": None,
                                          "request_id": "req-1"}}


def test_non_loopback_host_header_rejected(client):
    response = client.get("/api/v1/health", headers={"host": "evil.example"})
    assert response.status_code == 400


def test_security_headers(client):
    response = client.get("/api/v1/health")
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
