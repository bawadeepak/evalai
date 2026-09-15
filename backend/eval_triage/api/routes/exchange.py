"""Project export (ZIP) and validated import. Uploads are raw request bodies (application/zip)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope
from eval_triage.api.errors import ApiError, not_found, validation_error
from eval_triage.artifacts.exchange import MAX_ARCHIVE_BYTES, ArchiveError, read_archive
from eval_triage.artifacts.records import store_bytes
from eval_triage.db.models import ExportRecord, ImportRecord, Project
from eval_triage.db.types import iso
from eval_triage.domain.enums import JobKind
from eval_triage.execution import jobs

router = APIRouter(tags=["exchange"])


class ExportRequest(BaseModel):
    project_id: str
    redact_text: bool = False


def _export(row: ExportRecord) -> dict:
    return {"id": row.id, "project_id": row.project_id, "status": row.status, "options": row.options,
            "archive_hash": row.archive_hash, "summary": row.summary, "error": row.error,
            "download_url": f"/api/v1/exports/{row.id}/download" if row.archive_hash else None,
            "created_at": iso(row.created_at), "finished_at": iso(row.finished_at)}


@router.post("/exports", status_code=202)
def create_export(body: ExportRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.write() as session:
        if session.get(Project, body.project_id) is None:
            raise not_found("project", body.project_id)
        row = ExportRecord(project_id=body.project_id, options={"redact_text": body.redact_text})
        session.add(row)
        session.flush()
        jobs.enqueue(session, JobKind.EXPORT, {"export_id": row.id}, concurrency_key="exchange",
                     concurrency_limit=1, max_attempts=1)
        return envelope(_export(row))


@router.get("/exports")
def list_exports(project_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    from sqlalchemy import select

    with ctx.db.read() as session:
        rows = session.scalars(select(ExportRecord).where(ExportRecord.project_id == project_id)
                               .order_by(ExportRecord.created_at.desc())).all()
        return envelope([_export(r) for r in rows])


@router.get("/exports/{export_id}")
def get_export(export_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(ExportRecord, export_id)
        if row is None:
            raise not_found("export", export_id)
        return envelope(_export(row))


@router.get("/exports/{export_id}/download")
def download_export(export_id: str, ctx: AppContext = Depends(get_ctx)):
    with ctx.db.read() as session:
        row = session.get(ExportRecord, export_id)
        if row is None or not row.archive_hash:
            raise not_found("export archive", export_id)
    data = ctx.store.read_bytes(row.archive_hash)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="eval-triage-export-{export_id[:8]}.zip"'})


async def _body(request: Request) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ApiError(413, "payload_too_large", "archive exceeds the 200 MB limit")
    return bytes(data)


def _report(parsed: dict) -> dict:
    return {"ok": True, "source": parsed["manifest"]["source"], "counts": parsed["manifest"]["counts"],
            "artifacts": len(parsed["artifacts"]), "redaction": parsed["manifest"].get("redaction"),
            "exported_at": parsed["manifest"].get("exported_at")}


@router.post("/imports/validate")
async def validate_import(request: Request) -> dict:
    data = await _body(request)
    try:
        return envelope(_report(read_archive(data)))
    except ArchiveError as exc:
        raise validation_error(str(exc)) from exc


@router.post("/imports", status_code=202)
async def create_import(request: Request, ctx: AppContext = Depends(get_ctx),
                        name: str | None = Query(default=None, max_length=200)) -> dict:
    data = await _body(request)
    try:
        parsed = read_archive(data)
    except ArchiveError as exc:
        raise validation_error(str(exc)) from exc
    with ctx.db.write() as session:
        archive_hash = store_bytes(session, ctx.store, data, media_type="application/zip", kind="import_archive")
        row = ImportRecord(archive_hash=archive_hash,
                           source_identity={**parsed["manifest"]["source"], "requested_name": name})
        session.add(row)
        session.flush()
        jobs.enqueue(session, JobKind.IMPORT, {"import_id": row.id}, concurrency_key="exchange",
                     concurrency_limit=1, max_attempts=1)
        return envelope({"id": row.id, "status": row.status, "validation": _report(parsed)})


@router.get("/imports/{import_id}")
def get_import(import_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(ImportRecord, import_id)
        if row is None:
            raise not_found("import", import_id)
        return envelope({"id": row.id, "status": row.status, "project_id": row.project_id,
                         "source_identity": row.source_identity, "report": row.report, "error": row.error,
                         "created_at": iso(row.created_at), "finished_at": iso(row.finished_at)})
