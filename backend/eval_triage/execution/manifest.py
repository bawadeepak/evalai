"""Immutable run manifests.

The manifest records everything needed to interpret and reproduce a run:
definition hashes, fully resolved target configurations (credential reference
*names* only), prompts and tools, capability snapshots, repeat design and
seeds, SDK and adapter versions, source revisions, dependency lock hashes and
runtime information. Its hash changes whenever any of those change.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from eval_triage import SCHEMA_VERSION, __version__
from eval_triage.config import REPO_ROOT, Settings
from eval_triage.domain.canonical import content_hash

SDK_PACKAGES = ("openai", "anthropic", "fastapi", "pydantic", "sqlalchemy", "numpy", "scipy", "scikit-learn")
LOCK_FILES = ("uv.lock", "frontend/package-lock.json")


def _sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def lock_hashes() -> dict[str, str | None]:
    return {name: _sha256_file(REPO_ROOT / name) for name in LOCK_FILES}


def sdk_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package in SDK_PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def runtime_info() -> dict[str, Any]:
    return {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
            "eval_triage": __version__}


def git_revision(path: Path) -> dict[str, Any] | None:
    """Read-only revision lookup for a source checkout."""
    if not (path / ".git").exists():
        return None
    try:
        sha = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=5, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=5, check=True).stdout.strip() != ""
        return {"sha": sha, "tracked_changes": dirty}
    except (OSError, subprocess.SubprocessError):
        return None


def build_manifest(*, settings: Settings, scenario, dataset, candidates: list[dict[str, Any]],
                   graders: list[dict[str, Any]], execution: dict[str, Any], limits: dict[str, Any],
                   is_demo: bool, warnings: list[str], case_ids: list[str]) -> dict[str, Any]:
    uses_memoryai = any(c["config"]["adapter"] == "memoryai" for c in candidates)
    return {
        "schema_version": SCHEMA_VERSION,
        "demo": is_demo,
        "demo_notice": "Demo run: all outputs are synthetic fixtures, not measurements." if is_demo else None,
        "scenario": {"id": scenario.id, "hash": scenario.hash, "name": scenario.name, "pack": scenario.pack,
                     "version": scenario.version},
        "dataset": {"id": dataset.id, "hash": dataset.hash, "name": dataset.name, "version": dataset.version,
                    "case_count": len(case_ids), "case_ids": case_ids,
                    "pass_rule": dataset.pass_rule},
        "candidates": candidates,
        "graders": graders,
        "execution": execution,
        "limits": limits,
        "warnings": warnings,
        "environment": {
            "sdk_versions": sdk_versions(),
            "lock_hashes": lock_hashes(),
            "runtime": runtime_info(),
            "eval_triage_revision": git_revision(REPO_ROOT),
            "memoryai_revision": git_revision(settings.memoryai_source_path) if uses_memoryai else None,
        },
    }


def manifest_hash(manifest: dict[str, Any]) -> str:
    return content_hash(manifest)
