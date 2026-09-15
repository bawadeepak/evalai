"""Bridge protocol (version 1).

Request (one JSON object per line on stdin)::

    {"id": "<request id>", "protocol_version": 1, "command": "<name>", "params": {...}}

Response (one JSON object per line on stdout; stdout carries nothing else)::

    {"id": "<request id>", "ok": true, "result": {...}}
    {"id": "<request id>", "ok": false, "error": {"type": "...", "message": "...", "details": {...}}}

Commands: ``hello``, ``prepare``, ``execute_action``, ``inspect_state``, ``close``,
``shutdown``. Commands are handled strictly one at a time.
"""

from __future__ import annotations

from typing import Any

PROTOCOL_VERSION = 1

ERROR_TYPES = ("protocol_error", "isolation_refused", "unknown_session", "action_failed", "not_supported",
               "prerequisite_missing", "internal_error")


class BridgeError(Exception):
    def __init__(self, type_: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.type = type_ if type_ in ERROR_TYPES else "internal_error"
        self.details = details or {}
