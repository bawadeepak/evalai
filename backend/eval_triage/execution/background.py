"""Handlers for non-trial jobs: connection tests, calibration fits, exports and imports."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from eval_triage.adapters.base import RunContext, TargetConfig, TargetRequest
from eval_triage.adapters.registry import get_adapter
from eval_triage.api.context import AppContext
from eval_triage.artifacts.exchange import build_export, import_archive, read_archive
from eval_triage.artifacts.records import store_bytes
from eval_triage.db.models import ConnectionTest, ExportRecord, ImportRecord, TargetConfigVersion
from eval_triage.db.types import iso, utcnow
from eval_triage.domain.enums import JobKind
from eval_triage.execution.executors import request_parameters
from eval_triage.security.redaction import redact
from eval_triage.statistics.calibration import CalibrationError

CONNECTION_PROMPT = "Reply with the single word: ok"


async def run_connection_test(app: AppContext, job, worker_id: str) -> dict[str, Any]:
    test_id = job.payload["connection_test_id"]

    def load():
        with app.db.write() as session:
            test = session.get(ConnectionTest, test_id)
            test.status = "running"
            return TargetConfig.from_row(session.get(TargetConfigVersion, test.target_config_id))

    config = await asyncio.to_thread(load)
    adapter = get_adapter(config.adapter)
    context = RunContext(run_id="connection-test", trial_id=test_id, candidate_key="connection", repeat_index=0,
                         case_external_id="connection-test", attempt_index=0, data_dir=app.settings.data_dir)
    started = time.monotonic()
    try:
        session = await adapter.prepare(config, context)
        try:
            request = TargetRequest(messages=[{"role": "user", "content": CONNECTION_PROMPT}],
                                    parameters=request_parameters(config), stage="connection_test",
                                    metadata={"pack": "connection_test", "external_id": "connection-test",
                                              "repeat_index": 0})
            result = await asyncio.wait_for(adapter.execute(request, session), timeout=45)
        finally:
            await adapter.close(session)
        outcome = {"status": "success" if result.status == "success" else "failed",
                   "target_status": result.status, "actual_model": result.actual_model,
                   "request_id": result.request_id, "text": (result.text or "")[:200], "usage": result.usage,
                   "error": result.error}
    except TimeoutError:
        outcome = {"status": "failed", "target_status": "timeout", "error": {"message": "no response within 45 s"}}
    except Exception as exc:  # noqa: BLE001 - reported to the user, never raised
        outcome = {"status": "failed", "target_status": "error", "error": {"message": f"{type(exc).__name__}: {exc}"}}
    outcome["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
    outcome["verified_at"] = iso(utcnow())
    outcome = redact(outcome)[0]

    def save():
        with app.db.write() as session:
            test = session.get(ConnectionTest, test_id)
            test.status = outcome["status"]
            test.result = outcome
            test.finished_at = utcnow()

    await asyncio.to_thread(save)
    return {"connection_test_id": test_id, "status": outcome["status"]}


async def run_calibration_fit(app: AppContext, job, worker_id: str) -> dict[str, Any]:
    from eval_triage.analysis.probability import fit_calibration

    payload = dict(job.payload)
    project_id = payload.pop("project_id")

    def fit():
        with app.db.write() as session:
            row = fit_calibration(session, project_id, **payload)
            return {"ok": True, "calibration_id": row.id, "validation": row.validation}

    try:
        return await asyncio.to_thread(fit)
    except CalibrationError as exc:
        # A deterministic refusal is a result to show, not a job to retry.
        return {"ok": False, "error": str(exc)}


def _mark_failed(app: AppContext, model, record_id: str, message: str) -> None:
    with app.db.write() as session:
        record = session.get(model, record_id)
        record.status = "failed"
        record.error = {"message": redact(message)[0]}
        record.finished_at = utcnow()


async def run_export(app: AppContext, job, worker_id: str) -> dict[str, Any]:
    export_id = job.payload["export_id"]

    def work():
        with app.db.read() as session:
            record = session.get(ExportRecord, export_id)
            data, summary = build_export(session, app.store, record.project_id,
                                         redact_text=bool(record.options.get("redact_text")))
        with app.db.write() as session:
            record = session.get(ExportRecord, export_id)
            record.archive_hash = store_bytes(session, app.store, data, media_type="application/zip",
                                              kind="export_archive", entity_type="export", entity_id=export_id,
                                              role="archive")
            record.summary = {**summary, "bytes": len(data)}
            record.status = "completed"
            record.finished_at = utcnow()
            return {"export_id": export_id, "bytes": len(data)}

    try:
        return await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001 - recorded on the export for the user
        message = f"{type(exc).__name__}: {exc}"
        await asyncio.to_thread(_mark_failed, app, ExportRecord, export_id, message)
        return {"export_id": export_id, "error": message}


async def run_import(app: AppContext, job, worker_id: str) -> dict[str, Any]:
    import_id = job.payload["import_id"]

    def work():
        with app.db.read() as session:
            record = session.get(ImportRecord, import_id)
            data = app.store.read_bytes(record.archive_hash)
            name = (record.source_identity or {}).get("requested_name")
        parsed = read_archive(data)
        with app.db.write() as session:
            report = import_archive(session, app.store, parsed, name=name)
            record = session.get(ImportRecord, import_id)
            record.project_id = report["project_id"]
            record.report = report
            record.source_identity = {**(record.source_identity or {}), **parsed["manifest"]["source"]}
            record.status = "completed"
            record.finished_at = utcnow()
            return report

    try:
        return await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001 - archive and import errors are recorded on the import
        message = f"{type(exc).__name__}: {exc}"
        await asyncio.to_thread(_mark_failed, app, ImportRecord, import_id, message)
        return {"import_id": import_id, "error": message}


def register_background_handlers(register) -> None:
    from eval_triage.integrations.jobs import register_integration_handlers

    register(JobKind.CONNECTION_TEST, run_connection_test)
    register(JobKind.CALIBRATION_FIT, run_calibration_fit)
    register(JobKind.EXPORT, run_export)
    register(JobKind.IMPORT, run_import)
    register_integration_handlers(register)
