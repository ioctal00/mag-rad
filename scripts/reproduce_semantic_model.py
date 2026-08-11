#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from master_regimes.config import load_yaml, write_yaml
from master_regimes.representation_audit import (
    fcm_metrics,
    fit_best_fcm,
    seed_stability,
    squared_distances,
)

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild frozen semantic-V2 FCM outputs without Markdown."
    )
    parser.add_argument(
        "--weighted-matrix",
        type=Path,
        default=ROOT / "build/semantic-v2/semantic_v2_weighted.csv",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT
        / "sources/master-regimes/configs/features/"
        "feature_semantic_contract_v2.yml",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "build/semantic-v2-model",
    )
    return parser.parse_args()


def membership_rows(
    run_ids: pd.Series,
    memberships: np.ndarray,
    distances: np.ndarray,
    *,
    k: int,
) -> pd.DataFrame:
    rows: dict[str, Any] = {
        "query_run_id": run_ids.astype(str),
        "k": k,
        "dominant_cluster": memberships.argmax(axis=1),
        "max_membership": memberships.max(axis=1),
        "nearest_center_distance": distances.min(axis=1),
    }
    sorted_memberships = np.sort(memberships, axis=1)
    rows["top2_membership_margin"] = (
        sorted_memberships[:, -1] - sorted_memberships[:, -2]
    )
    for cluster in range(k):
        rows[f"membership_c{cluster}"] = memberships[:, cluster]
        rows[f"distance_c{cluster}"] = distances[:, cluster]
    return pd.DataFrame(rows)


def main() -> int:
    args = parse_args()
    matrix_path = args.weighted_matrix.resolve()
    contract_path = args.contract.resolve()
    out_dir = args.out_dir.resolve()
    contract = load_yaml(contract_path)
    weighted = pd.read_csv(matrix_path)
    features = [column for column in weighted if column != "query_run_id"]
    expected = [
        feature
        for feature, specification in contract["features"].items()
        if not specification.get("drop_as_redundant", False)
    ]
    if features != expected:
        raise ValueError(f"Feature order mismatch: {features} != {expected}")

    values = weighted[features].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Semantic matrix contains non-finite values")

    fuzzifier = float(contract["fuzzifier"])
    seeds = [int(seed) for seed in contract["seeds"]]
    seed_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    model_entries: dict[str, Any] = {}
    out_dir.mkdir(parents=True, exist_ok=True)

    for k in [int(value) for value in contract["k_values"]]:
        best, fits = fit_best_fcm(
            values,
            k=k,
            seeds=seeds,
            fuzzifier=fuzzifier,
        )
        for fit in fits:
            seed_rows.append(
                {
                    "k": k,
                    "seed": fit.seed,
                    "objective": fit.objective,
                    "iterations": fit.iterations,
                    "converged": fit.converged,
                    **fcm_metrics(values, fit),
                }
            )
        metrics = fcm_metrics(values, best)
        stability = seed_stability(fits)
        distances = np.sqrt(squared_distances(values, best.centers))
        nearest = distances.min(axis=1)
        threshold_p99 = float(np.quantile(nearest, 0.99))
        summary_rows.append(
            {
                "k": k,
                "representative_seed": best.seed,
                "objective": best.objective,
                **metrics,
                **stability,
                "baseline_distance_p95": float(np.quantile(nearest, 0.95)),
                "baseline_distance_p99": threshold_p99,
                "baseline_distance_max": float(nearest.max()),
            }
        )
        center_file = f"cluster_centers_k{k}.csv"
        membership_file = f"baseline_memberships_k{k}.csv"
        pd.DataFrame(best.centers, columns=features).assign(
            cluster=range(k)
        ).loc[:, ["cluster", *features]].to_csv(out_dir / center_file, index=False)
        membership_rows(
            weighted["query_run_id"],
            best.memberships,
            distances,
            k=k,
        ).to_csv(out_dir / membership_file, index=False)
        model_entries[f"k{k}"] = {
            "representative_seed": best.seed,
            "objective": best.objective,
            "center_file": center_file,
            "membership_file": membership_file,
            "ood_rule": "nearest_center_distance_above_baseline_p99",
            "ood_p99_threshold": threshold_p99,
            "metrics": {**metrics, **stability},
        }

    pd.DataFrame(seed_rows).to_csv(out_dir / "seed_scores.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(out_dir / "k_summary.csv", index=False)
    contract_sha256 = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    matrix_sha256 = hashlib.sha256(matrix_path.read_bytes()).hexdigest()
    manifest = {
        "model_id": "semantic-v2-transfer-oriented-fcm",
        "status": "reproduced_from_release_package",
        "training_scope": "corpus_conditioned_clean_run_v1",
        "normalization_scope": "corpus_independent_semantic_contract",
        "row_count": len(weighted),
        "feature_count": len(features),
        "features": features,
        "feature_contract": str(contract_path.relative_to(ROOT)),
        "feature_contract_sha256": contract_sha256,
        "weighted_matrix": str(matrix_path.relative_to(ROOT)),
        "weighted_matrix_sha256": matrix_sha256,
        "family_weighting": contract["family_weighting"],
        "missing_policy": contract["missing_policy"],
        "fuzzifier": fuzzifier,
        "seeds": seeds,
        "k_candidates": contract["k_values"],
        "primary_resolution": 4,
        "models": model_entries,
        "post_holdout_changes_allowed": False,
    }
    write_yaml(out_dir / "semantic_v2_model_manifest.yml", manifest)
    (out_dir / "freeze_sha256.json").write_text(
        json.dumps(
            {
                "feature_contract_sha256": contract_sha256,
                "weighted_matrix_sha256": matrix_sha256,
                "manifest_sha256": hashlib.sha256(
                    (out_dir / "semantic_v2_model_manifest.yml").read_bytes()
                ).hexdigest(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"[semantic-model] rows={len(weighted)} features={len(features)} "
        f"out={out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
