import pytest

from eval_triage.domain import importers
from eval_triage.domain.importers import ImportFormatError, detect_format, parse_bytes


@pytest.mark.parametrize("text", [
    "!!python/object/apply:os.system ['echo pwned']",
    "a: !!python/name:os.system",
    "x: !!binary aGVsbG8=",
])
def test_yaml_object_construction_and_non_json_types_rejected(text):
    with pytest.raises(ImportFormatError):
        parse_bytes(text.encode(), "yaml")


def test_yaml_aliases_rejected():
    bomb = "a: &a [1, 2]\nb: [*a, *a]\n"
    with pytest.raises(ImportFormatError, match="anchors and aliases"):
        parse_bytes(bomb.encode(), "yaml")


def test_yaml_duplicate_keys_and_non_string_keys_rejected():
    with pytest.raises(ImportFormatError, match="duplicate key"):
        parse_bytes(b"a: 1\na: 2\n", "yaml")
    with pytest.raises(ImportFormatError):
        parse_bytes(b"on: true\n", "yaml")  # YAML 1.1 turns `on` into a boolean key


def test_yaml_timestamps_must_be_quoted():
    with pytest.raises(ImportFormatError, match="quote dates"):
        parse_bytes(b"when: 2026-09-15\n", "yaml")
    assert parse_bytes(b"when: '2026-09-15'\n", "yaml") == {"when": "2026-09-15"}


def test_json_rejects_nan_and_duplicate_keys():
    with pytest.raises(ImportFormatError):
        parse_bytes(b'{"p": NaN}', "json")
    with pytest.raises(ImportFormatError):
        parse_bytes(b'{"p": Infinity}', "json")
    with pytest.raises(ImportFormatError, match="duplicate key"):
        parse_bytes(b'{"a": 1, "a": 2}', "json")


def test_jsonl_reports_line_numbers():
    data = b'{"a": 1}\n\n{"b": 2\n'
    with pytest.raises(ImportFormatError) as info:
        parse_bytes(data, "jsonl")
    assert info.value.line == 3
    assert parse_bytes(b'{"a": 1}\n{"b": 2}\n', "jsonl") == [{"a": 1}, {"b": 2}]


def test_encoding_bom_and_size_cap(monkeypatch):
    assert parse_bytes("﻿{\"a\": 1}".encode(), "json") == {"a": 1}
    with pytest.raises(ImportFormatError, match="UTF-8"):
        parse_bytes(b"\xff\xfe\x00", "json")
    monkeypatch.setattr(importers, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(ImportFormatError, match="larger than"):
        parse_bytes(b'{"a": "0123456789"}', "json")


def test_detect_format():
    assert detect_format("x.yml") == "yaml"
    assert detect_format("x.JSONL") == "jsonl"
    with pytest.raises(ImportFormatError):
        detect_format("x.py")
