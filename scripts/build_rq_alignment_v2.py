#!/usr/bin/env python3
"""Build the public RQ1-RQ4 summary from the frozen F19 artifacts."""

from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "releases/rq-alignment-v2"
MODEL = ROOT / "artifacts/results/semantic-v2-model-freeze"
CONSISTENCY = ROOT / "artifacts/results/semantic-v2-final-consistency"
MATRIX = ROOT / "artifacts/results/feature-semantic-contract-v2/semantic_v2_weighted.csv"

MIXED_CASE_ID = (
    "20260626T213739Z-clean-run-eu-us-gac-v1__pilot-skew-h--de5330b210fd--"
    "__limit_k-100__payload_repeat-16__payload_width-512"
)

PROTOTYPES = {
    0: (
        "selective distributed path without spill",
        "low spill and a smaller sequential worker-scan share",
    ),
    1: (
        "remote fan-in, global finalization and spill",
        "remote flow, temporary I/O and bounded final output",
    ),
    2: (
        "distributed sequential path without strong spill",
        "worker sequential access and remote work with less spill than P1",
    ),
    3: (
        "local or materialized path with low remote flow",
        "low global merge ratio and mostly materialized or local execution",
    ),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise AssertionError(f"refusing to write empty output: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    summaries = {int(row["k"]): row for row in read_csv(MODEL / "k_summary.csv")}
    model_rows = []
    for k in (3, 4):
        row = summaries[k]
        model_rows.append(
            {
                "representation": "F19",
                "k": k,
                "primary_resolution": k == 4,
                "representative_seed": row["representative_seed"],
                "silhouette": row["silhouette_hard_labels"],
                "partition_coefficient": row["partition_coefficient"],
                "partition_entropy": row["partition_entropy"],
                "average_max_membership": row["avg_max_membership"],
                "average_top2_margin": row["avg_top2_margin"],
                "seed_ari_mean": row["seed_ari_mean"],
                "training_p99_distance": row["baseline_distance_p99"],
            }
        )
    write_csv(OUT / "model_summary.csv", model_rows)

    memberships = read_csv(MODEL / "baseline_memberships_k4.csv")
    category_counts = {"clear": 0, "mixed": 0, "weak": 0}
    selected: dict[str, str] | None = None
    for row in memberships:
        values = [float(row[f"membership_c{i}"]) for i in range(4)]
        maximum = float(row["max_membership"])
        margin = float(row["top2_membership_margin"])
        entropy = -sum(value * math.log(max(value, 1e-300)) for value in values)
        if maximum >= 0.50 and margin >= 0.15 and entropy < 1.05:
            category = "clear"
        elif maximum < 0.50 and margin < 0.15 and entropy >= 1.05:
            category = "weak"
        else:
            category = "mixed"
        category_counts[category] += 1
        if row["query_run_id"] == MIXED_CASE_ID:
            selected = row | {"entropy": str(entropy), "category": category}
    assert category_counts == {"clear": 1847, "mixed": 69, "weak": 48}
    assert selected is not None and selected["category"] == "mixed"

    quality_rows = [
        {
            "category": category,
            "count": count,
            "share": count / len(memberships),
            "rule": {
                "clear": "max>=0.50 and margin>=0.15 and entropy<1.05",
                "weak": "max<0.50 and margin<0.15 and entropy>=1.05",
                "mixed": "all remaining combinations",
            }[category],
        }
        for category, count in category_counts.items()
    ]
    write_csv(OUT / "membership_quality.csv", quality_rows)

    prototype_rows = [
        {
            "prototype": f"P{cluster}",
            "descriptive_name": name,
            "dominant_signature": signature,
            "interpretation": "descriptive center, not a cause or intervention",
        }
        for cluster, (name, signature) in PROTOTYPES.items()
    ]
    write_csv(OUT / "prototype_summary.csv", prototype_rows)

    mixed_rows = []
    for cluster in range(4):
        mixed_rows.append(
            {
                "query_run_id": MIXED_CASE_ID,
                "logical_question_id": "event_raw_wide_sample",
                "dataset_id": "pilot-skew-heavy-v1",
                "runtime_config_id": "fetch_small",
                "prototype": f"P{cluster}",
                "distance": selected[f"distance_c{cluster}"],
                "membership": selected[f"membership_c{cluster}"],
                "case_category": selected["category"],
                "membership_entropy": selected["entropy"],
            }
        )
    write_csv(OUT / "mixed_case_memberships.csv", mixed_rows)

    weighted = {row["query_run_id"]: row for row in read_csv(MATRIX)}[MIXED_CASE_ID]
    centers = {int(row["cluster"]): row for row in read_csv(MODEL / "cluster_centers_k4.csv")}
    leading = int(selected["dominant_cluster"])
    competitor = max(
        (cluster for cluster in range(4) if cluster != leading),
        key=lambda cluster: float(selected[f"membership_c{cluster}"]),
    )
    features = [key for key in weighted if key != "query_run_id"]
    supports = []
    for feature in features:
        value = float(weighted[feature])
        support = (value - float(centers[competitor][feature])) ** 2 - (
            value - float(centers[leading][feature])
        ) ** 2
        supports.append(
            {
                "query_run_id": MIXED_CASE_ID,
                "leading_prototype": f"P{leading}",
                "competing_prototype": f"P{competitor}",
                "feature": feature,
                "local_support": support,
                "direction": f"P{leading}" if support >= 0 else f"P{competitor}",
            }
        )
    supports.sort(key=lambda row: abs(float(row["local_support"])), reverse=True)
    write_csv(OUT / "mixed_case_feature_support.csv", supports)

    promotion_rows = read_csv(CONSISTENCY / "promotion_gate.csv")
    write_csv(OUT / "promotion_gates.csv", promotion_rows)

    names = [
        "membership_quality.csv",
        "mixed_case_feature_support.csv",
        "mixed_case_memberships.csv",
        "model_summary.csv",
        "promotion_gates.csv",
        "prototype_summary.csv",
    ]
    with (OUT / "checksums.sha256").open("w", encoding="utf-8") as handle:
        for name in names:
            handle.write(f"{sha256(OUT / name)}  {name}\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
