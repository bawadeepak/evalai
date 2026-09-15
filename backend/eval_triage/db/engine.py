"""SQLite engines and session scopes.

Two engines share one WAL database file:

* the **write** engine starts every transaction with ``BEGIN IMMEDIATE`` so a
  writer takes the reserved lock up front (a deferred transaction that later
  writes fails immediately with SQLITE_BUSY instead of waiting);
* the **read** engine starts deferred transactions for queries and SSE polling.

pysqlite's implicit transaction handling is disabled so these BEGIN statements
are the only ones issued. Never hold a write transaction across an ``await`` or
a provider call.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from eval_triage.domain.canonical import dumps_strict

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
)


def _make_engine(db_path: Path, begin: str) -> Engine:
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 5.0},
        json_serializer=dumps_strict,
        json_deserializer=json.loads,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):  # pragma: no cover - exercised implicitly
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        for pragma in PRAGMAS:
            cursor.execute(pragma)
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(connection):  # pragma: no cover - exercised implicitly
        connection.exec_driver_sql(begin)

    return engine


class Database:
    def __init__(self, db_path: Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.write_engine = _make_engine(self.path, "BEGIN IMMEDIATE")
        self.read_engine = _make_engine(self.path, "BEGIN")
        self._write = sessionmaker(self.write_engine, expire_on_commit=False)
        self._read = sessionmaker(self.read_engine, expire_on_commit=False)

    @contextmanager
    def write(self) -> Iterator[Session]:
        """A short write transaction; commits on success, rolls back on error."""
        session = self._write()
        try:
            with session.begin():
                yield session
        finally:
            session.close()

    @contextmanager
    def read(self) -> Iterator[Session]:
        session = self._read()
        try:
            with session.begin():
                yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.write_engine.dispose()
        self.read_engine.dispose()
