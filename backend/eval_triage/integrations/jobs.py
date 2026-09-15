"""Worker handlers for integration jobs: configured Promptfoo suites and Inspect tasks.

Both are explicit, user-triggered jobs. A refusal (plugin unavailable, invalid
config, tool failure) is a result to show, not a job to retry.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from eval_triage.api.context import AppContext
from eval_triage.domain.enums import JobKind
from eval_triage.integrations import inspect_logs, promptfoo
from eval_triage.integrations.base import PluginInputError, PluginUnavailable
from eval_triage.integrations.service import save_import
from eval_triage.security.redaction import redact

REFUSALS = (PluginUnavailable, PluginInputError, subprocess.TimeoutExpired, FileNotFoundError, PermissionError)


async def run_promptfoo_job(app: AppContext, job, worker_id: str) -> dict[str, Any]:
    payload = job.payload

    def work():
        raw, info = promptfoo.run_suite(app.settings, payload["config"])
        normalized = promptfoo.parse(raw)
        with app.db.write() as session:
            row = save_import(session, app.store, payload["project_id"], normalized, raw,
                              filename=info["config"], run_info=info)
            return {"ok": True, "import_id": row.id, "summary": row.summary}

    try:
        return await asyncio.to_thread(work)
    except REFUSALS as exc:
        return {"ok": False, "error": redact(f"{type(exc).__name__}: {exc}")[0]}


async def run_inspect_job(app: AppContext, job, worker_id: str) -> dict[str, Any]:
    payload = job.payload

    def work():
        log_dir = app.settings.data_dir / "inspect-logs" / job.id
        raw = inspect_logs.run_task(payload["task"], payload["model"], log_dir, payload.get("limit"))
        normalized = inspect_logs.parse(raw)
        with app.db.write() as session:
            row = save_import(session, app.store, payload["project_id"], normalized, raw,
                              filename=f"{payload['task']} ({payload['model']})",
                              run_info={"task": payload["task"], "model": payload["model"],
                                        "limit": payload.get("limit")})
            return {"ok": True, "import_id": row.id, "summary": row.summary}

    try:
        return await asyncio.to_thread(work)
    except REFUSALS as exc:
        return {"ok": False, "error": redact(f"{type(exc).__name__}: {exc}")[0]}


def register_integration_handlers(register) -> None:
    register(JobKind.PROMPTFOO, run_promptfoo_job)
    register(JobKind.INSPECT_RUN, run_inspect_job)
