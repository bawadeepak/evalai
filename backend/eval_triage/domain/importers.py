"""Safe parsing of user-supplied JSON, JSONL and YAML.

* YAML uses the C safe loader only (no object construction), rejects anchors/
  aliases (entity-expansion attacks) and duplicate keys.
* JSON rejects NaN/Infinity and duplicate keys.
* Results must be plain JSON types with string keys; YAML timestamps, sets and
  binary values are rejected rather than coerced.
* Inputs are size-capped and must be UTF-8.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml

from eval_triage.domain.canonical import CanonicalJSONError, _check

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
Format = Literal["yaml", "json", "jsonl"]


class ImportFormatError(ValueError):
    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message if line is None else f"line {line}: {message}")
        self.line = line


class _SafeLoader(yaml.CSafeLoader if hasattr(yaml, "CSafeLoader") else yaml.SafeLoader):  # type: ignore[misc]
    pass


def _construct_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    keys = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hashable = key in keys
        except TypeError as exc:
            raise ImportFormatError("mapping keys must be scalars", key_node.start_mark.line + 1) from exc
        if hashable:
            raise ImportFormatError(f"duplicate key {key!r}", key_node.start_mark.line + 1)
        keys.add(key)
    return loader.construct_mapping(node, deep=deep)


_SafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def detect_format(filename: str) -> Format:
    suffix = Path(filename).suffix.lower()
    if suffix in (".yaml", ".yml"):
        return "yaml"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".json":
        return "json"
    raise ImportFormatError(f"unsupported file type {suffix or '(none)'}; use .yaml, .yml, .json or .jsonl")


def _decode(data: bytes) -> str:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ImportFormatError(f"document is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ImportFormatError("document must be UTF-8 encoded") from exc
    return text.removeprefix("﻿")


def _plain(value: Any) -> Any:
    try:
        return _check(value)
    except CanonicalJSONError as exc:
        raise ImportFormatError(f"{exc} (quote dates and times as strings)") from exc


def _reject_constant(name: str):
    raise ImportFormatError(f"{name} is not valid JSON; use null or a finite number")


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ImportFormatError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _json(text: str, line: int | None = None) -> Any:
    try:
        return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_no_duplicates)
    except ImportFormatError as exc:
        raise ImportFormatError(str(exc), line) from exc
    except json.JSONDecodeError as exc:
        raise ImportFormatError(f"invalid JSON: {exc.msg} (column {exc.colno})", line or exc.lineno) from exc


def _yaml(text: str) -> Any:
    try:
        for event in yaml.parse(text, Loader=_SafeLoader):
            if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
                line = event.start_mark.line + 1 if event.start_mark else None
                raise ImportFormatError("YAML anchors and aliases are not allowed", line)
        return yaml.load(text, Loader=_SafeLoader)  # noqa: S506 - _SafeLoader is a safe loader subclass
    except ImportFormatError:
        raise
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise ImportFormatError(f"invalid YAML: {getattr(exc, 'problem', None) or exc}",
                                mark.line + 1 if mark else None) from exc


def parse_bytes(data: bytes, fmt: Format) -> Any:
    text = _decode(data)
    if fmt == "json":
        return _plain(_json(text))
    if fmt == "yaml":
        return _plain(_yaml(text))
    if fmt == "jsonl":
        rows = []
        for number, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                rows.append(_plain(_json(line, number)))
        return rows
    raise ImportFormatError(f"unknown format {fmt!r}")


def parse_file(path: Path) -> Any:
    path = Path(path)
    return parse_bytes(path.read_bytes(), detect_format(path.name))
