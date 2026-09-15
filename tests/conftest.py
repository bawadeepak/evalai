from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("EVAL_TRIAGE_TESTING", "true")

from eval_triage.config import Settings, reset_settings  # noqa: E402

#: A fake secret planted in the environment; it must never appear in API
#: responses, exports, artifacts or logs.
SENTINEL_SECRET = "sk-evalai-SENTINEL-7f3c9d2e-never-leak"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir()
    return path


@pytest.fixture
def settings(data_dir: Path, monkeypatch) -> Settings:
    monkeypatch.setenv("EVAL_TRIAGE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EVAL_TRIAGE_TESTING", "true")
    monkeypatch.setenv("EVALAI_TEST_SECRET", SENTINEL_SECRET)
    reset_settings()
    s = Settings(data_dir=data_dir, testing=True, lease_seconds=2.0, heartbeat_seconds=0.5,
                 worker_poll_seconds=0.05, frontend_dist=data_dir / "no-frontend")
    yield s
    reset_settings()


@pytest.fixture
def app(settings):
    from eval_triage.api.app import create_app

    application = create_app(settings)
    yield application
    application.state.ctx.db.dispose()


@pytest.fixture
def ctx(app):
    return app.state.ctx


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
