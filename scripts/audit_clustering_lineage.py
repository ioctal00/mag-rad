#!/usr/bin/env python3
"""Audit the three distinct numerical spaces used by the thesis.

The audit intentionally keeps F19, F21-development and P64->6 separate.  It
uses only versioned files from this public package and has no third-party
dependencies.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import tarfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_shape(path: Path) -> tuple[int, int, list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = sum(1 for _ in reader)
    return rows, len(header), header


def yaml_scalar(path: Path, key: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.+?)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).strip("'\"")
    raise AssertionError(f"missing {key!r} in {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def close(actual: float, expected: float, tolerance: float = 1e-12) -> None:
    if not math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance):
        raise AssertionError(f"expected {expected}, got {actual}")


def normalized_mutual_information(left: list[str], right: list[str]) -> float:
    """Match sklearn's arithmetic normalized mutual information for labels."""
    if len(left) != len(right) or not left:
        raise AssertionError("NMI inputs must be non-empty and equally sized")
    total = len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    joint_counts = Counter(zip(left, right, strict=True))
    mutual_information = 0.0
    for (left_value, right_value), count in joint_counts.items():
        probability = count / total
        mutual_information += probability * math.log(
            probability
            / ((left_counts[left_value] / total) * (right_counts[right_value] / total))
        )
    left_entropy = -sum(
        (count / total) * math.log(count / total) for count in left_counts.values()
    )
    right_entropy = -sum(
        (count / total) * math.log(count / total) for count in right_counts.values()
    )
    denominator = (left_entropy + right_entropy) / 2.0
    return mutual_information / denominator if denominator else 1.0


def clean_run_datasets() -> dict[str, str]:
    archive = ROOT / "artifacts/logical-indexes/clean-run-v1.tar.gz"
    with tarfile.open(archive, "r:gz") as bundle:
        name = next(name for name in bundle.getnames() if name.endswith("query_runs.csv"))
        stream = bundle.extractfile(name)
        if stream is None:
            raise FileNotFoundError(name)
        rows = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8"))
        return {row["query_run_id"]: row["dataset_id"] for row in rows}


def f19_audit() -> dict[str, object]:
    base = ROOT / "artifacts/results/semantic-v2-model-freeze"
    manifest = base / "semantic_v2_model_manifest.yml"
    summary = {int(row["k"]): row for row in read_csv(base / "k_summary.csv")}
    memberships = read_csv(base / "baseline_memberships_k4.csv")
    datasets = clean_run_datasets()

    assert int(yaml_scalar(manifest, "row_count")) == 1964
    assert int(yaml_scalar(manifest, "feature_count")) == 19
    assert len(memberships) == 1964

    k3 = summary[3]
    k4 = summary[4]
    close(float(k3["silhouette_hard_labels"]), 0.6069302536880878)
    close(float(k4["silhouette_hard_labels"]), 0.6095309433985778)
    close(float(k4["partition_coefficient"]), 0.8337922200664419)
    close(float(k4["partition_entropy"]), 0.3483120047714823)
    close(float(k4["seed_ari_mean"]), 0.8925959119131807)

    counts = {"clear": 0, "mixed": 0, "weak": 0}
    for row in memberships:
        values = [float(row[f"membership_c{i}"]) for i in range(4)]
        maximum = float(row["max_membership"])
        margin = float(row["top2_membership_margin"])
        entropy = -sum(value * math.log(max(value, 1e-300)) for value in values)
        if maximum >= 0.50 and margin >= 0.15 and entropy < 1.05:
            counts["clear"] += 1
        elif maximum < 0.50 and margin < 0.15 and entropy >= 1.05:
            counts["weak"] += 1
        else:
            counts["mixed"] += 1
    assert counts == {"clear": 1847, "mixed": 69, "weak": 48}
    dataset_nmi = normalized_mutual_information(
        [row["dominant_cluster"] for row in memberships],
        [datasets[row["query_run_id"]] for row in memberships],
    )
    close(dataset_nmi, 0.02564659312499384)

    feature_header = next(
        csv.reader((base / "cluster_centers_k4.csv").open(newline="", encoding="utf-8"))
    )
    features = feature_header[1:]
    assert len(features) == 19

    return {
        "id": "F19",
        "status": "authoritative_fcm_characterization",
        "chronology": "semantic_v2_promoted_after_f21_development_model",
        "rows": 1964,
        "input_features": 19,
        "fit_scope": "clean_run_v1_only",
        "candidate_k": [3, 4],
        "primary_k": 4,
        "silhouette_k4": float(k4["silhouette_hard_labels"]),
        "partition_coefficient_k4": float(k4["partition_coefficient"]),
        "partition_entropy_k4": float(k4["partition_entropy"]),
        "seed_ari_mean_k4": float(k4["seed_ari_mean"]),
        "membership_categories": counts,
        "hard_cluster_vs_dataset_id_nmi": dataset_nmi,
        "features": features,
        "manifest_sha256": sha256(manifest),
    }


def f21_audit() -> dict[str, object]:
    base = ROOT / "releases/fcm-f21-development-v1"
    matrix = base / "source_matrix.csv"
    rows, columns, header = csv_shape(matrix)
    assert rows == 1964
    assert columns == 22
    summary = {int(row["k"]): row for row in read_csv(base / "k_summary.csv")}
    k4 = summary[4]
    k5 = summary[5]
    close(float(k4["silhouette_hard_labels_mean"]), 0.2139600728032148)
    close(float(k5["silhouette_hard_labels_mean"]), 0.22517138943672782)
    close(float(k4["partition_coefficient_mean"]), 0.530221089375764)
    close(float(k4["partition_entropy_mean"]), 0.8855309023176346)
    close(float(k4["ari_mean"]), 1.0)

    return {
        "id": "F21-development",
        "status": "historical_development_ablation_not_final_rq_model",
        "chronology": "precedes_semantic_v2_f19",
        "rows": rows,
        "input_features": columns - 1,
        "fit_scope": "clean_run_v1_only",
        "candidate_k": [4, 5],
        "primary_k": 4,
        "silhouette_k4": float(k4["silhouette_hard_labels_mean"]),
        "partition_coefficient_k4": float(k4["partition_coefficient_mean"]),
        "partition_entropy_k4": float(k4["partition_entropy_mean"]),
        "seed_ari_mean_k4": float(k4["ari_mean"]),
        "features": header[1:],
        "matrix_sha256": sha256(matrix),
    }


def p64_audit() -> dict[str, object]:
    base = ROOT / "releases/representation-ablation-e1-e4-v1"
    manifest = json.loads((base / "fit_manifest.json").read_text(encoding="utf-8"))
    model = manifest["representations"]["R3_full_multilayer"]
    leakage = json.loads((base / "leakage_audit.json").read_text(encoding="utf-8"))
    assert model["candidate_feature_count"] == 93
    assert model["active_feature_count"] == 64
    assert model["output_dimensions"] == 6
    assert model["fit_state_count"] == 26
    assert model["fit_scope"] == "preexisting_development_artifact"
    assert manifest["final_or_n3_outcomes_used_for_fit"] is False
    assert leakage["status"] == "PASS"
    assert all(leakage["checks"].values())

    return {
        "id": "P64->6",
        "status": "secondary_pca_knn_retrieval_space",
        "chronology": "separate_intervention_memory_pipeline",
        "candidate_features": 93,
        "active_features": 64,
        "output_dimensions": 6,
        "fit_states": 26,
        "fit_scope": model["fit_scope"],
        "coverage_threshold": model["coverage_threshold"],
        "final_or_n3_outcomes_used_for_fit": False,
        "leakage_audit_pass": True,
        "features": model["active_features"],
    }


def write_outputs(output_dir: Path, result: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audit_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lineage_fields = [
        "id",
        "status",
        "chronology",
        "rows",
        "input_features",
        "candidate_features",
        "active_features",
        "output_dimensions",
        "fit_states",
        "fit_scope",
        "primary_k",
        "silhouette_k4",
        "hard_cluster_vs_dataset_id_nmi",
    ]
    with (output_dir / "model_lineage.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=lineage_fields, lineterminator="\n")
        writer.writeheader()
        for key in ("f19", "f21_development", "p64_to_6"):
            item = result[key]
            writer.writerow({field: item.get(field, "") for field in lineage_fields})

    f19 = set(result["f19"]["features"])
    f21 = set(result["f21_development"]["features"])
    p64 = set(result["p64_to_6"]["features"])
    all_features = sorted(f19 | f21 | p64)
    with (output_dir / "feature_overlap.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["feature", "in_f19", "in_f21_development", "in_p64_to_6"])
        for feature in all_features:
            writer.writerow([feature, feature in f19, feature in f21, feature in p64])

    checksummed = ["audit_summary.json", "feature_overlap.csv", "model_lineage.csv"]
    with (output_dir / "checksums.sha256").open("w", encoding="utf-8") as handle:
        for name in checksummed:
            handle.write(f"{sha256(output_dir / name)}  {name}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "releases/model-lineage-audit-v1",
    )
    args = parser.parse_args()

    result = {
        "audit_status": "pass",
        "core_finding": (
            "F19 is the authoritative FCM characterization; F21 is an earlier "
            "development ablation; P64->6 is a separate PCA/kNN retrieval space."
        ),
        "f19": f19_audit(),
        "f21_development": f21_audit(),
        "p64_to_6": p64_audit(),
    }
    write_outputs(args.output_dir, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
