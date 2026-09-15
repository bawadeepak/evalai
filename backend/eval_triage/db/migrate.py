"""Programmatic migrations and the database immutability guards."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from eval_triage.config import REPO_ROOT
from eval_triage.db.models import IMMUTABLE_TABLES
from eval_triage.domain.enums import ATTEMPT_TERMINAL, TRIAL_TERMINAL


class ImmutableRecordError(RuntimeError):
    pass


def alembic_config(db_path: Path) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "eval_triage" / "db" / "migrations"))
    cfg.attributes["db_path"] = str(db_path)
    return cfg


def upgrade(db_path: Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(db_path), "head")


def _quoted(values) -> str:
    return ", ".join(f"'{v}'" for v in sorted(values))


#: Tables made immutable by the initial migration (0001). Frozen: a later
#: migration creates the triggers for the tables it adds (immutable_trigger_ddl),
#: so replaying 0001 on an empty database never references a missing table.
INITIAL_IMMUTABLE_TABLES = (
    "scenario_versions", "dataset_versions", "cases", "target_config_versions", "grader_versions",
    "release_policies", "calibration_versions", "probability_records", "grades", "trial_outcomes", "reviews",
    "comparisons", "artifacts", "artifact_refs", "events",
)


def immutable_trigger_ddl(tables) -> list[str]:
    """UPDATE/DELETE-aborting triggers for the given tables."""
    return [
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
        f"BEGIN SELECT RAISE(ABORT, 'immutable record: {table}'); END"
        for table in tables for operation in ("UPDATE", "DELETE")
    ]


def drop_immutable_trigger_ddl(tables) -> list[str]:
    return [f"DROP TRIGGER IF EXISTS {table}_no_{op}" for table in tables for op in ("update", "delete")]


def trigger_ddl() -> list[str]:
    """SQL for the triggers created in the initial migration."""
    ddl = immutable_trigger_ddl(INITIAL_IMMUTABLE_TABLES)
    for table, terminal in (("trials", TRIAL_TERMINAL), ("attempts", ATTEMPT_TERMINAL)):
        ddl.append(
            f"CREATE TRIGGER IF NOT EXISTS {table}_terminal_guard BEFORE UPDATE ON {table} "
            f"WHEN OLD.status IN ({_quoted(terminal)}) "
            f"BEGIN SELECT RAISE(ABORT, 'terminal {table[:-1]} is immutable'); END"
        )
        ddl.append(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'evidence rows cannot be deleted: {table}'); END"
        )
    ddl.append(
        "CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON runs "
        "BEGIN SELECT RAISE(ABORT, 'runs cannot be deleted'); END"
    )
    return ddl


def drop_trigger_ddl() -> list[str]:
    names = ["trials_terminal_guard", "trials_no_delete", "attempts_terminal_guard", "attempts_no_delete",
             "runs_no_delete"]
    return drop_immutable_trigger_ddl(INITIAL_IMMUTABLE_TABLES) + [f"DROP TRIGGER IF EXISTS {n}" for n in names]


@event.listens_for(Session, "before_flush")
def _guard_immutable(session: Session, _context, _instances) -> None:
    """Friendlier ORM-level error before the database trigger fires."""
    for obj in list(session.dirty) + list(session.deleted):
        table = obj.__table__.name
        if table in IMMUTABLE_TABLES:
            state = inspect(obj)
            if obj in session.deleted or state.modified:
                raise ImmutableRecordError(f"{table} rows are immutable; create a new version instead")
        if table in ("trials", "attempts") and obj in session.dirty:
            history = inspect(obj).attrs.status.history
            previous = history.deleted[0] if history.deleted else obj.status
            terminal = TRIAL_TERMINAL if table == "trials" else ATTEMPT_TERMINAL
            if previous in terminal and inspect(obj).modified:
                raise ImmutableRecordError(f"{table[:-1]} is terminal and can no longer change")
