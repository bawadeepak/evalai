from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from eval_triage.artifacts.store import ArtifactStore
from eval_triage.config import Settings
from eval_triage.db.engine import Database


@dataclass
class AppContext:
    settings: Settings
    db: Database
    store: ArtifactStore


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx
