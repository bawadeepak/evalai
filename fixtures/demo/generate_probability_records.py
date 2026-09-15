"""Regenerate ``probability_records.json`` deterministically (seed 42).

Synthetic, clearly labelled demo data: a stated-confidence score that is
systematically overconfident (true success probability = score ** 1.8), grouped
into 40 conversation clusters of two records. Clusters 0–19 form the
calibration split and 20–39 the held-out test split, so no cluster spans splits.

Run: ``uv run python fixtures/demo/generate_probability_records.py``
"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).with_name("probability_records.json")


def generate() -> list[dict]:
    rng = random.Random(42)
    records = []
    for cluster in range(40):
        split = "calibration" if cluster < 20 else "test"
        for item in range(2):
            score = round(rng.uniform(0.05, 0.99), 3)
            label = 1 if rng.random() < score ** 1.8 else 0
            records.append({
                "external_id": f"P{cluster:02d}-{item}",
                "cluster_id": f"prob-conversation-{cluster:02d}",
                "split": split,
                "raw_feature": score,
                "probability": score,
                "label": label,
            })
    return records


if __name__ == "__main__":
    data = generate()
    OUT.write_text(json.dumps({"schema_version": 1, "demo": True, "records": data}, indent=1) + "\n")
    for split in ("calibration", "test"):
        rows = [r for r in data if r["split"] == split]
        print(split, len(rows), "records,", sum(r["label"] for r in rows), "positives")
