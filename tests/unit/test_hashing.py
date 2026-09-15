import math

import pytest

from eval_triage.domain.canonical import (
    CanonicalJSONError,
    canonical_json,
    content_hash,
    hash_payload,
)


def test_keys_sorted_recursively_arrays_keep_order():
    a = {"b": 1, "a": {"y": [3, 1, 2], "x": "é"}}
    b = {"a": {"x": "é", "y": [3, 1, 2]}, "b": 1}
    assert canonical_json(a) == canonical_json(b) == '{"a":{"x":"é","y":[3,1,2]},"b":1}'
    assert content_hash(a) == content_hash(b)
    assert content_hash({"y": [1, 2, 3]}) != content_hash({"y": [3, 2, 1]})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -math.inf])
def test_non_finite_numbers_rejected(bad):
    with pytest.raises(CanonicalJSONError):
        canonical_json({"value": bad})


def test_non_string_keys_and_non_json_types_rejected():
    with pytest.raises(CanonicalJSONError):
        canonical_json({1: "a"})
    with pytest.raises(CanonicalJSONError):
        canonical_json({"when": object()})


def test_no_lossy_numeric_coercion():
    assert content_hash({"v": 1}) != content_hash({"v": 1.0})
    assert content_hash({"v": "1"}) != content_hash({"v": 1})


def test_operational_keys_excluded_but_credential_ref_names_included():
    base = {"name": "t", "credential_ref": "OPENAI_API_KEY", "parameters": {"temperature": 0}}
    with_ops = {**base, "id": "x", "created_at": "2026-01-01", "project_id": "p1", "version": 3}
    assert hash_payload(base) == hash_payload(with_ops)
    assert hash_payload(base) != hash_payload({**base, "credential_ref": "OTHER_KEY"})
