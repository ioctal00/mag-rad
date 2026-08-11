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

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUDIT_DIR = ROOT / "analysis/reports/feature-semantic-contract-v2"
DEFAULT_CONTRACT = ROOT / "configs/features/feature_semantic_contract_v2.yml"
DEFAULT_OUT_DIR = ROOT / "analysis/reports/semantic-v2-model-freeze"
P99_QUANTILE_METHOD = "linear"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze corrected semantic-v2 FCM centers before second holdout."
    )
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
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
    audit_dir = args.audit_dir.resolve()
    contract_path = args.contract.resolve()
    out_dir = args.out_dir.resolve()
    contract = load_yaml(contract_path)
    gate = pd.read_csv(audit_dir / "feature_semantic_gate.csv")
    if not gate["status"].eq("PASS").all():
        raise ValueError("Feature semantic audit gate must pass before model freeze")

    weighted = pd.read_csv(audit_dir / "semantic_v2_weighted.csv")
    features = [column for column in weighted if column != "query_run_id"]
    expected_features = [
        feature
        for feature, specification in contract["features"].items()
        if not specification.get("drop_as_redundant", False)
    ]
    if features != expected_features:
        raise ValueError(f"Feature order mismatch: {features} != {expected_features}")
    values = weighted[features].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Semantic-v2 matrix contains non-finite values")

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
            metrics = fcm_metrics(values, fit)
            seed_rows.append(
                {
                    "k": k,
                    "seed": fit.seed,
                    "objective": fit.objective,
                    "iterations": fit.iterations,
                    "converged": fit.converged,
                    **metrics,
                }
            )
        metrics = fcm_metrics(values, best)
        stability = seed_stability(fits)
        distances = np.sqrt(squared_distances(values, best.centers))
        nearest = distances.min(axis=1)
        threshold_p99 = float(
            np.quantile(nearest, 0.99, method=P99_QUANTILE_METHOD)
        )
        summary_rows.append(
            {
                "k": k,
                "representative_seed": best.seed,
                "objective": best.objective,
                **metrics,
                **stability,
                "baseline_distance_p95": float(
                    np.quantile(nearest, 0.95, method=P99_QUANTILE_METHOD)
                ),
                "baseline_distance_p99": threshold_p99,
                "baseline_distance_max": float(nearest.max()),
            }
        )
        pd.DataFrame(best.centers, columns=features).assign(
            cluster=range(k)
        ).loc[:, ["cluster", *features]].to_csv(
            out_dir / f"cluster_centers_k{k}.csv",
            index=False,
        )
        membership_rows(
            weighted["query_run_id"],
            best.memberships,
            distances,
            k=k,
        ).to_csv(out_dir / f"baseline_memberships_k{k}.csv", index=False)
        model_entries[f"k{k}"] = {
            "representative_seed": best.seed,
            "objective": best.objective,
            "center_file": f"cluster_centers_k{k}.csv",
            "membership_file": f"baseline_memberships_k{k}.csv",
            "ood_rule": "nearest_center_distance_above_baseline_p99",
            "coverage_rule": "nearest_center_distance_above_training_p99",
            "ood_p99_threshold": threshold_p99,
            "metrics": {**metrics, **stability},
        }

    pd.DataFrame(seed_rows).to_csv(out_dir / "seed_scores.csv", index=False)
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out_dir / "k_summary.csv", index=False)
    contract_sha256 = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    matrix_sha256 = hashlib.sha256(
        (audit_dir / "semantic_v2_weighted.csv").read_bytes()
    ).hexdigest()
    manifest = {
        "model_id": "semantic-v2-transfer-oriented-fcm",
        "status": "corrective_refreeze_before_second_external_holdout",
        "training_scope": "corpus_conditioned_clean_run_v1",
        "normalization_scope": "corpus_independent_semantic_contract",
        "row_count": len(weighted),
        "feature_count": len(features),
        "features": features,
        "feature_contract": str(contract_path.relative_to(ROOT)),
        "feature_contract_sha256": contract_sha256,
        "weighted_matrix": str(
            (audit_dir / "semantic_v2_weighted.csv").relative_to(ROOT)
        ),
        "weighted_matrix_sha256": matrix_sha256,
        "family_weighting": contract["family_weighting"],
        "missing_policy": contract["missing_policy"],
        "fuzzifier": fuzzifier,
        "seeds": seeds,
        "k_candidates": contract["k_values"],
        "primary_resolution": 4,
        "primary_resolution_rationale": (
            "locked operational four-prototype resolution retained for direct "
            "comparison with v1; k=3 remains a macro-resolution sensitivity model"
        ),
        "coverage_reference": {
            "interpretation": "empirical_training_coverage_not_formal_ood_detector",
            "distance": "euclidean_distance_to_nearest_fcm_center",
            "threshold_scope": "one_global_threshold_per_representation",
            "quantile": 0.99,
            "quantile_method": P99_QUANTILE_METHOD,
            "reference_rows": len(weighted),
            "reference_scope": "clean_run_v1_training_corpus",
            "frozen_before_external_projection": True,
        },
        "models": model_entries,
        "confirmatory_holdout": contract["confirmatory_holdout"],
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
    k4 = summary[summary["k"].eq(4)].iloc[0]
    (out_dir / "README.md").write_text(
        f"""# Semantic v2 model freeze

This package freezes the corrected transfer-oriented semantic normalization
and its corpus-conditioned FCM prototypes before the second external holdout
is rendered or executed.

## Primary model

```text
rows: {len(weighted)}
features: {len(features)}
k: 4
fuzzifier: {fuzzifier}
seeds: {seeds[0]}..{seeds[-1]}
representative seed: {int(k4["representative_seed"])}
silhouette: {float(k4["silhouette_hard_labels"]):.4f}
seed ARI mean: {float(k4["seed_ari_mean"]):.4f}
average max membership: {float(k4["avg_max_membership"]):.4f}
empirical P99 coverage threshold: {float(k4["baseline_distance_p99"]):.6f}
```

`k=3` is retained as a macro-resolution sensitivity model. The primary `k=4`
choice is locked for comparison with v1 and is not selected using external
holdout behavior.

The P99 value is one global nearest-center distance threshold computed from
the {len(weighted)} training rows with NumPy's linear quantile method. It is
an empirical coverage reference, not a formal OOD detector or statistical
generalization guarantee.

The first STATS-CEB semantic-v2 holdout is classified as a development audit
because it exposed a pre-existing regional `MapMerge` visibility mismatch.
No rows from the second, confirmatory `stats-ceb-semantic-v2b-holdout` are
present in this package.
""",
        encoding="utf-8",
    )
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
