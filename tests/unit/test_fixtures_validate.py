"""Every shipped fixture validates against the runtime schemas, and the demo
fixtures have the properties the demo journeys depend on."""

import json
from collections import Counter

import pytest

from eval_triage.domain.enums import Pack
from eval_triage.domain.fixtures import FIXTURES_DIR, load_source, pack_sources
from eval_triage.domain.importers import parse_file
from eval_triage.domain.scenario import validate_document
from eval_triage.domain.splits import assign_cluster_splits, split_manifest

SOURCES = pack_sources()


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_fixture_source_validates(name):
    report = validate_document(load_source(SOURCES[name]))
    assert report.ok, [(e.path, e.message) for e in report.errors]
    assert not [w for w in report.warnings if w.code != "check_pack"], report.warnings


def test_every_pack_has_at_least_three_cases_including_negative_or_boundary():
    by_pack = {}
    for name, path in SOURCES.items():
        if name.startswith("demo:"):
            continue
        report = validate_document(load_source(path))
        by_pack[report.scenario.pack] = report.cases
    assert set(by_pack) == set(Pack)
    for pack, cases in by_pack.items():
        assert len(cases) >= 3, pack
        purposes = " ".join(c.purpose.lower() for c in cases)
        assert any(word in purposes for word in ("negative", "boundary", "negat")), pack


def test_memoryai_episodes_m01_to_m15():
    report = validate_document(load_source(FIXTURES_DIR / "memoryai"))
    assert [c.external_id for c in report.cases] == [f"M{i:02d}" for i in range(1, 16)]
    m11 = next(c for c in report.cases if c.external_id == "M11")
    assert m11.fixture_options.fault_injection.smalltalk == "timeout"
    m10 = next(c for c in report.cases if c.external_id == "M10")
    assert {s.store for s in m10.episode} == {"alex", "alexa"}


def _passes(schedule, variants, repeats):
    default = schedule.get("default")
    overrides = schedule.get("repeats", {})
    chosen = [overrides.get(str(i), default) for i in range(repeats)]
    return sum(variants[v]["intended_verdict"] == "pass" for v in chosen), Counter(chosen)


def test_demo_memory_schedule_matches_documented_triage_counts():
    outputs = parse_file(FIXTURES_DIR / "demo" / "memory_outputs.yaml")
    repeats = outputs["repeats"]
    expected = {"M03": 18, "M06": 16, "M05": 0}
    for case, candidate_passes in expected.items():
        spec = outputs["cases"][case]
        passes, chosen = _passes(spec["schedule"]["candidate"], spec["variants"], repeats)
        assert passes == candidate_passes, case
        baseline_passes, _ = _passes(spec["schedule"]["baseline"], spec["variants"], repeats)
        assert baseline_passes == repeats
    _, m05 = _passes(outputs["cases"]["M05"]["schedule"]["candidate"], outputs["cases"]["M05"]["variants"], repeats)
    assert len(m05) == 1  # identical output on every repeat: 100% agreement, 0% correct


def test_demo_routing_suite_supports_automatic_gate():
    report = validate_document(load_source(FIXTURES_DIR / "demo" / "routing.scenario.yaml"))
    clusters = {c.effective_cluster for c in report.cases}
    assert len(clusters) >= 20
    outputs = parse_file(FIXTURES_DIR / "demo" / "routing_outputs.yaml")
    ids = {c.external_id for c in report.cases}
    for profile in outputs["profiles"].values():
        assert set(profile) <= ids


def test_demo_probability_records_are_cluster_split():
    data = json.loads((FIXTURES_DIR / "demo" / "probability_records.json").read_text())
    records = data["records"]
    assert data["demo"] is True
    manifest = split_manifest(records)
    assert manifest["leaking_clusters"] == []
    assert manifest["cluster_count"] >= 30
    for split in ("calibration", "test"):
        labels = {r["label"] for r in records if r["split"] == split}
        assert labels == {0, 1}, split
        assert all(0 <= r["probability"] <= 1 for r in records)


def test_cluster_split_assignment_is_deterministic_and_proportional():
    clusters = [f"c{i}" for i in range(50)]
    a = assign_cluster_splits(clusters, {"calibration": 0.6, "test": 0.4}, seed=7)
    b = assign_cluster_splits(reversed(clusters), {"calibration": 0.6, "test": 0.4}, seed=7)
    assert a == b
    assert Counter(a.values()) == {"calibration": 30, "test": 20}
