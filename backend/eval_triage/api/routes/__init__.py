from fastapi import APIRouter

from eval_triage.api.routes import (
    analysis,
    definitions,
    exchange,
    health,
    probability,
    projects,
    reviews,
    runs,
    settings,
)

api_router = APIRouter()
for module in (health, projects, definitions, runs, analysis, reviews, probability, exchange, settings):
    api_router.include_router(module.router)
