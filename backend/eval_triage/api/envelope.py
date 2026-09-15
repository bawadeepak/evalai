"""Response envelope ``{data, meta}`` and opaque cursor pagination."""

from __future__ import annotations

import base64
import json
from typing import Any

from sqlalchemy import Select, and_, or_
from sqlalchemy.orm import Session

from eval_triage.api.errors import validation_error

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def envelope(data: Any, **meta: Any) -> dict:
    return {"data": data, "meta": meta}


def encode_cursor(sort_value: Any, row_id: str) -> str:
    raw = json.dumps([sort_value, row_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[Any, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value, row_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return value, str(row_id)
    except Exception as exc:  # noqa: BLE001
        raise validation_error("Invalid pagination cursor") from exc


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1 or limit > MAX_LIMIT:
        raise validation_error(f"limit must be between 1 and {MAX_LIMIT}", {"limit": limit})
    return limit


def paginate(session: Session, stmt: Select, sort_col, id_col, limit: int | None, cursor: str | None,
             descending: bool = True, serialize=lambda row: row):
    """Keyset pagination over ``(sort_col, id_col)``; returns ``(items, meta)``."""
    limit = clamp_limit(limit)
    if cursor:
        value, row_id = decode_cursor(cursor)
        if descending:
            stmt = stmt.where(or_(sort_col < value, and_(sort_col == value, id_col < row_id)))
        else:
            stmt = stmt.where(or_(sort_col > value, and_(sort_col == value, id_col > row_id)))
    order = (sort_col.desc(), id_col.desc()) if descending else (sort_col.asc(), id_col.asc())
    rows = session.scalars(stmt.order_by(*order).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        sort_value = getattr(last, sort_col.key)
        if hasattr(sort_value, "isoformat"):
            from eval_triage.db.types import iso

            sort_value = iso(sort_value)
        next_cursor = encode_cursor(sort_value, getattr(last, id_col.key))
    return [serialize(row) for row in rows], {"limit": limit, "next_cursor": next_cursor}
