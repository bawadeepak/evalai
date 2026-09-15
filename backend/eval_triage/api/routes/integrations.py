"""Optional integrations: plugin descriptions, result-file imports (Inspect, Promptfoo),
imported results, and explicitly configured runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope
from eval_triage.api.errors import ApiError, not_found, validation_error
from eval_triage.db.models import ExternalImport, Project
from eval_triage.domain.enums import JobKind
from eval_triage.execution import jobs
from eval_triage.integrations import inspect_logs, promptfoo, registry
from eval_triage.integrations.base import PluginInputError, PluginUnavailable
from eval_triage.integrations.service import import_results, list_imports, save_import, serialize_import

router = APIRouter(tags=["integrations"])
IMPORTERS = {"promptfoo": promptfoo, "inspect": inspect_logs}
MAX_IMPORT_CHARS = 50 * 1024 * 1024


class ResultFileImport(BaseModel):
    project_id: str
    filename: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=MAX_IMPORT_CHARS)


class PromptfooRun(BaseModel):
    project_id: str
    config: str = Field(min_length=1, max_length=500)


class InspectRun(BaseModel):
    project_id: str
    task: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    limit: int | None = Field(default=None, ge=1, le=100_000)


def _unavailable(message: str, install: str) -> ApiError:
    return ApiError(409, "plugin_unavailable", message, {"install": install})


def _project(session, project_id: str) -> None:
    if session.get(Project, project_id) is None:
        raise not_found("project", project_id)


@router.get("/integrations")
def list_integrations(ctx: AppContext = Depends(get_ctx)) -> dict:
    return envelope(registry.plugins(ctx.settings))


@router.post("/integrations/{plugin}/imports", status_code=201)
def import_file(plugin: str, body: ResultFileImport, ctx: AppContext = Depends(get_ctx)) -> dict:
    module = IMPORTERS.get(plugin)
    if module is None:
        raise not_found("importer", plugin)
    raw = body.content.encode("utf-8")
    try:
        normalized = module.parse(raw)
    except PluginInputError as exc:
        raise validation_error(f"{module.INFO.title} file is invalid: {exc}",
                               [{"loc": [exc.path or "content"], "msg": str(exc)}]) from exc
    with ctx.db.write() as session:
        _project(session, body.project_id)
        row = save_import(session, ctx.store, body.project_id, normalized, raw, filename=body.filename)
        return envelope(serialize_import(row, len(normalized.results)))


@router.get("/external-imports")
def external_imports(project_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        return envelope(list_imports(session, project_id))


@router.get("/external-imports/{import_id}")
def external_import(import_id: str, ctx: AppContext = Depends(get_ctx), status: str | None = None,
                    limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0)) -> dict:
    with ctx.db.read() as session:
        row = session.get(ExternalImport, import_id)
        if row is None:
            raise not_found("external import", import_id)
        results, total = import_results(session, import_id, status, limit, offset)
        return envelope({**serialize_import(row), "results": results}, total=total, limit=limit, offset=offset)


@router.post("/integrations/promptfoo/runs", status_code=202)
def run_promptfoo(body: PromptfooRun, ctx: AppContext = Depends(get_ctx)) -> dict:
    try:
        promptfoo.resolve_config(ctx.settings, body.config)
    except PluginUnavailable as exc:
        raise _unavailable(str(exc), promptfoo.INFO.install) from exc
    except PluginInputError as exc:
        raise validation_error(str(exc), [{"loc": ["config"], "msg": str(exc)}]) from exc
    with ctx.db.write() as session:
        _project(session, body.project_id)
        job = jobs.enqueue(session, JobKind.PROMPTFOO, body.model_dump(), concurrency_key="promptfoo",
                           concurrency_limit=1, max_attempts=1)
        return envelope({"job_id": job.id, "status": job.status,
                         "note": "runs the configured Promptfoo command once; results are imported when it finishes"})


@router.post("/integrations/inspect/runs", status_code=202)
def run_inspect(body: InspectRun, ctx: AppContext = Depends(get_ctx)) -> dict:
    capability = inspect_logs.capabilities(ctx.settings)["run"]
    if not capability["available"]:
        raise _unavailable(capability["reason"], inspect_logs.INSTALL)
    with ctx.db.write() as session:
        _project(session, body.project_id)
        job = jobs.enqueue(session, JobKind.INSPECT_RUN, body.model_dump(), concurrency_key="inspect",
                           concurrency_limit=1, max_attempts=1)
        return envelope({"job_id": job.id, "status": job.status,
                         "note": "runs the Inspect task (this makes model calls); the log is imported when it finishes"})
