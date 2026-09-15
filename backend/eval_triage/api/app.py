"""FastAPI application factory."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from eval_triage import __version__
from eval_triage.api.context import AppContext
from eval_triage.api.errors import install_error_handlers
from eval_triage.api.routes import api_router
from eval_triage.artifacts.store import ArtifactStore
from eval_triage.config import LOOPBACK_HOSTS, Settings, get_settings
from eval_triage.db.engine import Database
from eval_triage.db.migrate import upgrade

# The UI renders model output as text or sanitised Markdown only; the CSP
# makes injected markup inert even if a rendering bug slipped through.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


def build_context(settings: Settings, migrate: bool = True) -> AppContext:
    settings.ensure_dirs()
    if migrate:
        upgrade(settings.db_path)
    return AppContext(settings=settings, db=Database(settings.db_path), store=ArtifactStore(settings.artifacts_dir))


def create_app(settings: Settings | None = None, *, migrate: bool = True) -> FastAPI:
    settings = settings or get_settings()
    ctx = build_context(settings, migrate=migrate)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        ctx.db.dispose()

    app = FastAPI(title="Eval Triage", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None, lifespan=lifespan)
    app.state.ctx = ctx

    allowed = sorted(LOOPBACK_HOSTS | {"testserver"}) if not settings.allow_non_loopback else ["*"]
    # Loopback-only Host check guards the unauthenticated local API against DNS rebinding.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[h for h in allowed if h != "::1"] + ["[::1]"])

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response

    install_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    _mount_frontend(app, settings.frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.is_file():
        @app.get("/", include_in_schema=False)
        async def _no_frontend():
            return JSONResponse({"data": {"message": "Frontend not built. Run `make build` or use `make dev`."},
                                 "meta": {}})
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def _spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "Unknown API route",
                                           "details": None, "request_id": None}}, status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)
