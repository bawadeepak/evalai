"""Loading of versioned synthetic fixture packs shipped under ``fixtures/``.

A source is either a single scenario document (``scenario.yaml`` with inline
``dataset.cases``) or a directory holding ``scenario.yaml`` plus one case per
file in ``cases/`` (used for the MemoryAI episodes M01–M15).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eval_triage.config import REPO_ROOT
from eval_triage.domain.importers import parse_file

FIXTURES_DIR = REPO_ROOT / "fixtures"


def load_source(path: Path, include_cases: list[str] | None = None) -> dict[str, Any]:
    path = Path(path)
    if path.is_dir():
        document = parse_file(path / "scenario.yaml")
        cases: list[Any] = list(document.get("dataset", {}).get("cases", []))
        for case_file in sorted((path / "cases").glob("*.y*ml")):
            loaded = parse_file(case_file)
            cases.extend(loaded if isinstance(loaded, list) else [loaded])
        document.setdefault("dataset", {})["cases"] = cases
    else:
        document = parse_file(path)
    if include_cases is not None:
        wanted = list(include_cases)
        by_id = {c.get("external_id"): c for c in document.get("dataset", {}).get("cases", [])}
        missing = [w for w in wanted if w not in by_id]
        if missing:
            raise KeyError(f"cases {missing} not found in {path}")
        document["dataset"]["cases"] = [by_id[w] for w in wanted]
    return document


def pack_sources() -> dict[str, Path]:
    """Every shipped scenario source keyed by a short name."""
    sources = {"memoryai": FIXTURES_DIR / "memoryai"}
    for scenario in sorted((FIXTURES_DIR / "packs").glob("*/scenario.yaml")):
        sources[scenario.parent.name] = scenario
    for scenario in sorted((FIXTURES_DIR / "demo").glob("*.scenario.yaml")):
        sources["demo:" + scenario.name.removesuffix(".scenario.yaml")] = scenario
    return sources
