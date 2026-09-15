"""Projects."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from eval_triage.api import serializers as ser
from eval_triage.api.context import AppContext, get_ctx
from eval_triage.api.envelope import envelope
from eval_triage.api.errors import not_found
from eval_triage.db.models import DatasetVersion, Project, Run, ScenarioVersion, TargetConfigVersion
from eval_triage.db.repositories import create_project

router = APIRouter(tags=["projects"])


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


@router.get("/projects")
def list_projects(ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        rows = session.scalars(select(Project).order_by(Project.created_at.desc())).all()
        return envelope([ser.project(p) for p in rows])


@router.post("/projects", status_code=201)
def new_project(body: ProjectRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.write() as session:
        return envelope(ser.project(create_project(session, body.name, body.description)))


@router.get("/projects/{project_id}")
def get_project(project_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    with ctx.db.read() as session:
        row = session.get(Project, project_id)
        if row is None:
            raise not_found("project", project_id)

        def count(model) -> int:
            return session.scalar(select(func.count()).select_from(model).where(model.project_id == project_id))

        return envelope({**ser.project(row), "counts": {
            "scenarios": count(ScenarioVersion), "datasets": count(DatasetVersion), "runs": count(Run),
            "target_configs": count(TargetConfigVersion)}})
