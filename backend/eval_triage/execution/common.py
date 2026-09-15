from __future__ import annotations


class Defer(Exception):
    """Put the job back in the queue without counting a failed attempt."""

    def __init__(self, seconds: float, note: str) -> None:
        super().__init__(note)
        self.seconds = seconds
        self.note = note
