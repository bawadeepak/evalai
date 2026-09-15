"""Cluster-aware splitting, split manifests and duplicate detection.

Splits are assigned per ``cluster_id`` (conversation, person, document) so that
related cases cannot leak between calibration/validation and held-out test data.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from typing import Any


def _rank(cluster: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{cluster}".encode()).hexdigest()


def assign_cluster_splits(clusters: Iterable[str], fractions: dict[str, float], seed: int = 42) -> dict[str, str]:
    """Deterministically map each cluster to a split in proportion to ``fractions``."""
    if not fractions or any(f <= 0 for f in fractions.values()):
        raise ValueError("fractions must be positive")
    total = sum(fractions.values())
    ordered = sorted(set(clusters), key=lambda c: _rank(c, seed))
    n = len(ordered)
    names = list(fractions)
    targets, cumulative = [], 0.0
    for name in names:
        cumulative += fractions[name] / total
        targets.append(round(cumulative * n))
    mapping: dict[str, str] = {}
    start = 0
    for name, end in zip(names, targets, strict=True):
        for cluster in ordered[start:end]:
            mapping[cluster] = name
        start = end
    return mapping


def apply_cluster_split(cases: list[dict[str, Any]], fractions: dict[str, float], seed: int = 42):
    mapping = assign_cluster_splits((c.get("cluster_id") or c["external_id"] for c in cases), fractions, seed)
    updated = [{**c, "split": mapping[c.get("cluster_id") or c["external_id"]]} for c in cases]
    return updated, split_manifest(updated) | {"method": "cluster_hash", "seed": seed, "fractions": fractions}


def split_manifest(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_split: dict[str, dict[str, set]] = defaultdict(lambda: {"cases": set(), "clusters": set()})
    cluster_splits: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        cluster = case.get("cluster_id") or case["external_id"]
        split = case.get("split", "test")
        by_split[split]["cases"].add(case["external_id"])
        by_split[split]["clusters"].add(cluster)
        cluster_splits[cluster].add(split)
    return {
        "splits": {s: {"cases": len(v["cases"]), "clusters": len(v["clusters"])} for s, v in sorted(by_split.items())},
        "case_count": len(cases),
        "cluster_count": len(cluster_splits),
        "leaking_clusters": sorted(c for c, s in cluster_splits.items() if len(s) > 1),
    }


def find_duplicates(cases: list[dict[str, Any]]) -> list[list[str]]:
    """Groups of external ids whose task content hashes are identical."""
    groups: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        groups[case["case_hash"]].append(case["external_id"])
    return [ids for ids in groups.values() if len(ids) > 1]
