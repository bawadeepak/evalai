"""Local settings, pricing table, plugin availability, retention and evidence integrity."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from eval_triage.adapters.pricing import load_pricing, write_user_pricing
from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope
from eval_triage.api.routes.health import worker_status
from eval_triage.db.models import Artifact, MemoryStoreOwnership
from eval_triage.integrations.registry import plugin_status
from eval_triage.security.redaction import REDACTION_VERSION

router = APIRouter(tags=["settings"])


def _dir_bytes(path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


@router.get("/settings")
def settings(ctx: AppContext = Depends(get_ctx)) -> dict:
    s = ctx.settings
    with ctx.db.read() as session:
        referenced = set(session.scalars(select(Artifact.content_hash)))
        stores = dict(session.execute(select(MemoryStoreOwnership.state, func.count())
                                      .group_by(MemoryStoreOwnership.state)).all())
        store_bytes = session.scalar(select(func.sum(MemoryStoreOwnership.disk_bytes))) or 0
    orphans = ctx.store.orphans(referenced)
    return envelope({
        "paths": {"data_dir": str(s.data_dir), "database": str(s.db_path), "artifacts": str(s.artifacts_dir),
                  "memoryai_stores": str(s.memoryai_stores_dir)},
        "api": {"host": s.api_host, "port": s.api_port, "loopback_only": not s.allow_non_loopback},
        "worker": {**worker_status(ctx), "lease_seconds": s.lease_seconds, "heartbeat_seconds": s.heartbeat_seconds,
                   "slots": s.worker_slots},
        "limits": {"default_repeats": 5, "max_transport_retries": 2, "memoryai_concurrency": 1,
                   "stateless_concurrency": 2},
        "plugins": plugin_status(),
        "memoryai": {"source_path": str(s.memoryai_source_path), "python": str(s.resolved_memoryai_python),
                     "source_available": s.memoryai_source_path.is_dir(),
                     "python_available": s.resolved_memoryai_python.exists(),
                     "isolated_stores": stores, "recorded_store_bytes": store_bytes,
                     "stores_dir_bytes": _dir_bytes(s.memoryai_stores_dir),
                     "cleanup": "Stores are retained by default. Run `evalai memoryai gc --yes` to drop stores "
                                "created by Eval Triage (never others)."},
        "redaction": {"version": REDACTION_VERSION,
                      "policy": "Authorization-like keys and server-side secret values are masked before storage."},
        "retention": {"policy": "All evidence is retained. Orphaned files are reported, never deleted.",
                      "orphans": {k: len(v) for k, v in orphans.items()}},
        "pricing": load_pricing(s),
        "reviewer_name": "Stored in this browser only (Settings page).",
    })


class PricingEntry(BaseModel):
    adapter: str
    model: str
    currency: str = Field(min_length=3, max_length=3)
    input_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)
    note: str = ""


class PricingTable(BaseModel):
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: str = ""
    entries: list[PricingEntry]


@router.put("/settings/pricing")
def update_pricing(body: PricingTable, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    write_user_pricing(ctx.settings, body.model_dump())
    return envelope(load_pricing(ctx.settings))
