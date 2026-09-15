"""Column types shared by the ORM models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("naive datetimes are not allowed; use UTC-aware values")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class UTCDateTime(TypeDecorator):
    """Stores aware datetimes as sortable ISO-8601 UTC strings ending in ``Z``."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return iso(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
