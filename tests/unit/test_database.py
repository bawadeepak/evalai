"""Migrations, pragmas, immutability triggers and restart persistence."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from eval_triage.db.engine import Database
from eval_triage.db.migrate import ImmutableRecordError, upgrade
from eval_triage.db.models import (
    Artifact,
    Attempt,
    Case,
    DatasetVersion,
    Project,
    Run,
    ScenarioVersion,
    Trial,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.sqlite"
    upgrade(path)
    database = Database(path)
    yield database
    database.dispose()


def _seed(db):
    with db.write() as s:
        p = Project(name="p")
        s.add(p)
        s.flush()
        sc = ScenarioVersion(project_id=p.id, logical_id="L", version=1, name="s", pack="rag", contract="c",
                             definition={}, hash="0" * 64)
        s.add(sc)
        s.flush()
        ds = DatasetVersion(project_id=p.id, logical_id="D", version=1, name="d", scenario_id=sc.id, hash="1" * 64)
        s.add(ds)
        s.flush()
        case = Case(dataset_id=ds.id, ordinal=0, external_id="C1", cluster_id="k", case_hash="2" * 64)
        s.add(case)
        s.flush()
        run = Run(project_id=p.id, scenario_id=sc.id, dataset_id=ds.id, manifest={}, manifest_hash="3" * 64,
                  planned_trial_count=1)
        s.add(run)
        s.flush()
        trial = Trial(run_id=run.id, case_id=case.id, candidate_key="c", repeat_index=0, schedule_order=0)
        s.add(trial)
        s.flush()
        return {"scenario": sc.id, "case": case.id, "run": run.id, "trial": trial.id}


def test_pragmas(db):
    with db.read() as s:
        assert s.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert s.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert s.execute(text("PRAGMA busy_timeout")).scalar() == 5000


def test_foreign_keys_enforced(db):
    with pytest.raises(IntegrityError), db.write() as s:
        s.add(Case(dataset_id="missing", ordinal=0, external_id="x", cluster_id="k", case_hash="0" * 64))


def test_definitions_cannot_be_updated_or_deleted(db):
    ids = _seed(db)
    with pytest.raises(ImmutableRecordError), db.write() as s:
        s.get(ScenarioVersion, ids["scenario"]).name = "changed"
    # The database trigger fires even when the ORM guard is bypassed.
    for sql in ("UPDATE scenario_versions SET name='x'", "DELETE FROM cases"):
        with pytest.raises(IntegrityError), db.write() as s:
            s.execute(text(sql))


def test_terminal_trials_and_attempts_are_frozen(db):
    ids = _seed(db)
    with db.write() as s:
        trial = s.get(Trial, ids["trial"])
        trial.status = "success"
        s.add(Attempt(trial_id=trial.id, attempt_index=0, status="success"))
    with pytest.raises(ImmutableRecordError), db.write() as s:
        s.get(Trial, ids["trial"]).status = "running"
    with pytest.raises(IntegrityError), db.write() as s:
        s.execute(text("UPDATE trials SET status='pending'"))
    with pytest.raises(IntegrityError), db.write() as s:
        s.execute(text("UPDATE attempts SET status='running'"))
    with pytest.raises(IntegrityError), db.write() as s:
        s.execute(text("DELETE FROM runs"))


def test_non_finite_json_rejected_by_column_serializer(db):
    from sqlalchemy.exc import StatementError

    ids = _seed(db)
    with pytest.raises(StatementError, match="not JSON compliant"), db.write() as s:
        s.get(Run, ids["run"]).usage = {"cost": float("nan")}


def test_restart_keeps_data(tmp_path):
    path = tmp_path / "r.sqlite"
    upgrade(path)
    first = Database(path)
    with first.write() as s:
        s.add(Artifact(content_hash="a" * 64, relative_path="aa/aa/x", media_type="text/plain", byte_length=1,
                       kind="raw"))
    first.dispose()
    upgrade(path)  # idempotent
    second = Database(path)
    with second.read() as s:
        assert s.get(Artifact, "a" * 64).media_type == "text/plain"
    second.dispose()
