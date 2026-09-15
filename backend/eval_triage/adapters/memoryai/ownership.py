"""Explicit clean-up of isolated MemoryAI stores created by Eval Triage (``evalai memoryai gc``).

Only stores recorded in Eval Triage's database *and* carrying a matching
ownership manifest under the stores root are dropped; the bridge re-verifies
the nonce and instance name and refuses the store of the real MemoryAI data
directory. Everything else is left untouched.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from eval_triage.adapters.memoryai.bridge_client import BridgeError, BridgeProcess
from eval_triage.api.app import build_context
from eval_triage.config import Settings
from eval_triage.db.models import MemoryStoreOwnership
from eval_triage.db.types import utcnow

OWNERSHIP_FILE = ".evalai-owned.json"


def _plan(rows: list[MemoryStoreOwnership]) -> list[dict[str, Any]]:
    plan = []
    for row in rows:
        manifest_path = Path(row.data_dir).parent / OWNERSHIP_FILE
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            plan.append({"id": row.id, "instance": row.instance, "data_dir": row.data_dir, "action": "skip",
                         "reason": "ownership manifest missing"})
            continue
        plan.append({"id": row.id, "instance": row.instance, "data_dir": row.data_dir, "nonce": row.nonce,
                     "backend": "fake" if manifest.get("backend") == "fake" else "real", "action": "drop"})
    return plan


def _public(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in ("nonce", "id")}


def gc_stores(settings: Settings, dry_run: bool = True) -> dict[str, Any]:
    ctx = build_context(settings)
    with ctx.db.read() as session:
        rows = list(session.scalars(select(MemoryStoreOwnership).where(
            MemoryStoreOwnership.state.in_(["retained", "orphaned"]))))
    plan = _plan(rows)
    if dry_run:
        return {"dry_run": True, "stores": [_public({**p, "action": "would drop" if p["action"] == "drop"
                                                     else p["action"]}) for p in plan]}
    results = asyncio.run(_drop_all(settings, [p for p in plan if p["action"] == "drop"]))
    with ctx.db.write() as session:
        for item in results:
            if item.get("dropped"):
                row = session.get(MemoryStoreOwnership, item["id"])
                row.state, row.dropped_at = "dropped", utcnow()
    skipped = [p for p in plan if p["action"] == "skip"]
    return {"dry_run": False, "stores": [_public(r) for r in results + skipped]}


async def _drop_all(settings: Settings, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    processes: dict[str, BridgeProcess] = {}
    try:
        for item in plan:
            process = processes.get(item["backend"])
            if process is None:
                process = BridgeProcess(settings, item["backend"])
                await process.start()
                processes[item["backend"]] = process
            try:
                result = await process.request("drop_store", {"data_dir": item["data_dir"], "nonce": item["nonce"]},
                                               timeout=120)
                results.append({**item, "dropped": True, "result": result})
            except BridgeError as exc:
                results.append({**item, "dropped": False, "error": str(exc)})
    finally:
        for process in processes.values():
            await process.stop()
    return results
