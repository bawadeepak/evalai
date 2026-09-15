"""Seed the clearly labelled demo project (idempotent).

Every object is marked ``is_demo``; every run manifest carries a demo notice.
Runs are enqueued; a worker executes them (``make dev`` / ``make start``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from eval_triage.api.app import build_context
from eval_triage.api.context import AppContext
from eval_triage.config import Settings
from eval_triage.db.models import ProbabilityRecord, Project
from eval_triage.db.repositories import (
    create_project,
    create_release_policy,
    create_target_config,
    import_document,
)
from eval_triage.domain.fixtures import FIXTURES_DIR, load_source
from eval_triage.domain.importers import parse_file
from eval_triage.execution.runs import RunRequest, create_run

DEMO_DIR = FIXTURES_DIR / "demo"
PREDICTED_AT = datetime(2026, 9, 1, tzinfo=UTC)


def _project(session, spec: dict[str, Any]) -> Project:
    existing = session.scalars(select(Project).where(Project.is_demo.is_(True),
                                                     Project.name == spec["name"])).first()
    return existing or create_project(session, spec["name"], spec.get("description", ""), is_demo=True)


def seed_demo(settings: Settings, ctx: AppContext | None = None) -> dict[str, Any]:
    ctx = ctx or build_context(settings)
    manifest = parse_file(DEMO_DIR / "demo.yaml")
    suites: list[dict[str, Any]] = []
    with ctx.db.write() as session:
        project = _project(session, manifest["project"])
        judge = create_target_config(session, project.id, name="Demo judge", adapter="demo",
                                     model=manifest["judge"]["model"], is_demo=True)
        for suite in manifest["suites"]:
            source = (DEMO_DIR / suite["source"]).resolve()
            document = load_source(source, include_cases=suite.get("include_cases"))
            imported = import_document(session, project.id, document, judges={manifest["judge"]["name"]: judge.id},
                                       provenance={"source": str(source.relative_to(FIXTURES_DIR.parent)),
                                                   "demo": True, "note": manifest["description"]},
                                       dataset_name=suite.get("dataset_name"), is_demo=True)
            configs = []
            for cand in suite["candidates"]:
                row = create_target_config(session, project.id, name=cand["name"], adapter="demo",
                                           model=cand["model"], parameters={"profile": cand["profile"]},
                                           is_demo=True)
                configs.append({"key": cand["key"], "target_config_id": row.id})
            suites.append({"key": suite["key"], "scenario_id": imported["scenario"].id,
                           "dataset_id": imported["dataset"].id, "candidates": configs,
                           "repeats": suite["repeats"]})
        policy = manifest["release_policy"]
        create_release_policy(session, project.id, policy["name"], {k: v for k, v in policy.items() if k != "name"})
        records_added = _seed_probability(session, project.id, manifest["probability"])
        project_id = project.id
    runs = []
    for suite in suites:
        request = RunRequest(project_id=project_id, scenario_id=suite["scenario_id"], dataset_id=suite["dataset_id"],
                             name=f"Demo · {suite['key']}", candidates=suite["candidates"],
                             execution={"repeats": suite["repeats"], "schedule_seed": 42})
        _, response = create_run(ctx.db, settings, request, idempotency_key=f"demo:{project_id}:{suite['key']}")
        runs.append({"suite": suite["key"], "run_id": response["data"]["id"],
                     "planned_trials": response["data"]["plan"]["planned_trials"]})
    return {"project_id": project_id, "runs": runs, "probability_records_added": records_added,
            "note": "Demo data is synthetic. Start a worker (make dev or make start) to execute the demo runs."}


def _seed_probability(session, project_id: str, spec: dict[str, Any]) -> int:
    existing = session.scalars(select(ProbabilityRecord).where(ProbabilityRecord.project_id == project_id,
                                                               ProbabilityRecord.is_demo.is_(True))).first()
    if existing is not None:
        return 0
    data = json.loads((DEMO_DIR / spec["records"]).read_text())
    for index, record in enumerate(data["records"]):
        session.add(ProbabilityRecord(
            project_id=project_id, external_id=record["external_id"], cluster_id=record["cluster_id"],
            split=record["split"], event_definition=spec["event_definition"], score_type=spec["score_type"],
            method=spec["method"], source_version=spec["source_version"],
            predicted_at=PREDICTED_AT + timedelta(minutes=index), probability=record["probability"],
            raw_feature=record["raw_feature"], label=record["label"], label_source="demo fixture label",
            labeled_at=PREDICTED_AT + timedelta(days=1, minutes=index), is_demo=True))
    return len(data["records"])
