"""Service health: API, database, worker and optional plugins. Never includes secrets."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, text

from eval_triage import SCHEMA_VERSION, __version__
from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope
from eval_triage.db.models import WorkerHeartbeat
from eval_triage.db.types import iso, utcnow
from eval_triage.integrations.registry import plugin_status

router = APIRouter(tags=["health"])


def worker_status(ctx: AppContext) -> dict:
    stale_after = timedelta(seconds=max(3 * ctx.settings.heartbeat_seconds, 5))
    with ctx.db.read() as session:
        beats = session.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.heartbeat_at.desc())).all()
    now = utcnow()
    live = [b for b in beats if now - b.heartbeat_at <= stale_after]
    if live:
        status = "ok"
    elif beats:
        status = "stale"
    else:
        status = "absent"
    return {
        "status": status,
        "live_workers": len(live),
        "last_heartbeat": iso(beats[0].heartbeat_at) if beats else None,
    }


@router.get("/health")
def health(ctx: AppContext = Depends(get_ctx)) -> dict:
    database = {"status": "ok"}
    try:
        with ctx.db.read() as session:
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            journal = session.execute(text("PRAGMA journal_mode")).scalar()
        database.update({"revision": revision, "journal_mode": journal})
    except Exception as exc:  # noqa: BLE001
        database = {"status": "error", "message": type(exc).__name__}
    settings = ctx.settings
    memoryai_python = settings.resolved_memoryai_python
    return envelope({
        "api": {"status": "ok", "version": __version__, "schema_version": SCHEMA_VERSION},
        "database": database,
        "worker": worker_status(ctx),
        "plugins": plugin_status(),
        "memoryai": {
            "source_path": str(settings.memoryai_source_path),
            "source_available": settings.memoryai_source_path.is_dir(),
            "python_available": memoryai_python.exists(),
        },
        "data_dir": str(settings.data_dir),
        "testing": settings.testing,
    })
