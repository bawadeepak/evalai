from __future__ import annotations

from pathlib import Path

from alembic import context

from eval_triage.config import get_settings
from eval_triage.db.engine import Database
from eval_triage.db.models import Base

config = context.config
target_metadata = Base.metadata


def _db_path() -> Path:
    override = config.attributes.get("db_path")
    return Path(override) if override else get_settings().db_path


def run_migrations_offline() -> None:
    context.configure(url=f"sqlite:///{_db_path()}", target_metadata=target_metadata, render_as_batch=True,
                      literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database = Database(_db_path())
    try:
        with database.write_engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        database.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
