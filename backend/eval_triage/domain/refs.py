"""Safe references to earlier step outputs.

Grammar: ``<step_id>`` followed by one or more ``.name`` or ``[index]`` segments,
for example ``r1.context`` or ``r1.sections.facts[0].hit_id``. Resolution walks
plain dicts and lists only: no attribute access, evaluation, templating or
shell interpolation is ever performed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

STEP_ID_PATTERN = r"[A-Za-z][A-Za-z0-9_-]{0,63}"
_STEP = re.compile(STEP_ID_PATTERN)
_SEGMENT = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]{0,63})|\[(\d{1,6})\]")
MAX_REF_LENGTH = 300
MAX_SEGMENTS = 16


class RefError(ValueError):
    pass


def parse_ref(ref: str) -> tuple[str, tuple[str | int, ...]]:
    if not isinstance(ref, str) or not ref or len(ref) > MAX_REF_LENGTH:
        raise RefError("a reference must be a non-empty string of at most 300 characters")
    match = _STEP.match(ref)
    if not match:
        raise RefError(f"{ref!r}: a reference must start with a step id")
    position = match.end()
    segments: list[str | int] = []
    while position < len(ref):
        segment = _SEGMENT.match(ref, position)
        if not segment:
            raise RefError(f"{ref!r}: invalid reference syntax at character {position + 1}; "
                           "use .field or [index] segments only")
        segments.append(segment.group(1) if segment.group(1) is not None else int(segment.group(2)))
        position = segment.end()
    if not segments:
        raise RefError(f"{ref!r}: select a field of the step output, for example {match.group(0)}.context")
    if len(segments) > MAX_SEGMENTS:
        raise RefError(f"{ref!r}: at most {MAX_SEGMENTS} path segments are allowed")
    return match.group(0), tuple(segments)


def ref_step(ref: str) -> str:
    return parse_ref(ref)[0]


def resolve_ref(ref: str, outputs: Mapping[str, Any]) -> Any:
    step, segments = parse_ref(ref)
    if step not in outputs:
        raise RefError(f"{ref!r}: step {step!r} has no recorded output")
    value = outputs[step]
    walked = step
    for segment in segments:
        if isinstance(segment, int):
            if not isinstance(value, list) or segment >= len(value):
                raise RefError(f"{ref!r}: {walked} has no index [{segment}]")
            value = value[segment]
            walked += f"[{segment}]"
        else:
            if not isinstance(value, dict) or segment not in value:
                raise RefError(f"{ref!r}: {walked} has no field {segment!r}")
            value = value[segment]
            walked += f".{segment}"
    return value
