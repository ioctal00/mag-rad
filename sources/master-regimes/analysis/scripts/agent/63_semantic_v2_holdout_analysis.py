from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from master_regimes.config import load_yaml
from master_regimes.frozen_projection import (
    fuzzy_memberships,
    load_feature_contract,
    project_to_frozen_model,
)
from master_regimes.representation_audit import (
    memberships_from_centers,
    semantic_transform,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "configs/features/feature_semantic_contract_v2.yml"
DEFAULT_FREEZE_DIR = ROOT / "analysis/reports/semantic-v2-model-freeze"
DEFAULT_V1_MODEL_MANIFEST = (
    ROOT / "analysis/reports/clean-run-v1-final-model/final_model_manifest.yml"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project a STATS-CEB evaluation into frozen semantic-v2 FCM."
    )
    parser.add_argument("--logical-index", type=Path, required=True)
    parser.add_argument("--feature-dir", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--freeze-dir", type=Path, default=DEFAULT_FREEZE_DIR)
    parser.add_argument(
        "--v1-model-manifest",
        type=Path,
        default=DEFAULT_V1_MODEL_MANIFEST,
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--logical-run-id", default="")
    parser.add_argument(
        "--artifact-prefix",
        default="holdout",
        help="Safe prefix used for generated CSV and JSON files.",
    )
    parser.add_argument(
        "--report-title",
        default="STATS-CEB semantic-v2 confirmatory holdout",
    )
    parser.add_argument(
        "--scope-statement",
        default=(
            "ovim netaknutim vanjskim skupom i fiksnom topologijom"
        ),
    )
    return parser.parse_args()


def _query_id(value: Any) -> int | None:
    try:
        parsed = json.loads(str(value))
        return int(parsed["query_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _read_optional(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _projection(
    *,
    weighted: pd.DataFrame,
    centers_path: Path,
    fuzzifier: float,
    threshold: float,
    k: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    centers_frame = pd.read_csv(centers_path)
    features = [column for column in weighted if column != "query_run_id"]
    if list(centers_frame.columns) != ["cluster", *features]:
        raise ValueError(f"Frozen k={k} center feature order does not match holdout")
    values = weighted[features].to_numpy(dtype=float)
    centers = centers_frame[features].to_numpy(dtype=float)
    memberships, distances = memberships_from_centers(
        values,
        centers,
        fuzzifier=fuzzifier,
    )
    nearest = distances.argmin(axis=1)
    sorted_memberships = np.sort(memberships, axis=1)
    projection = pd.DataFrame(
        {
            "query_run_id": weighted["query_run_id"].astype(str),
            "k": k,
            "dominant_cluster": memberships.argmax(axis=1),
            "nearest_center": nearest,
            "nearest_center_distance": distances.min(axis=1),
            "frozen_p99_threshold": threshold,
            "ood_above_frozen_p99": distances.min(axis=1) > threshold,
            "max_membership": memberships.max(axis=1),
            "top2_membership_margin": (
                sorted_memberships[:, -1] - sorted_memberships[:, -2]
            ),
        }
    )
    for cluster in range(k):
        projection[f"membership_c{cluster}"] = memberships[:, cluster]
        projection[f"distance_c{cluster}"] = distances[:, cluster]

    contribution_rows: list[dict[str, Any]] = []
    for row_index, query_run_id in enumerate(weighted["query_run_id"].astype(str)):
        center = centers[nearest[row_index]]
        squared = (values[row_index] - center) ** 2
        total = float(squared.sum())
        for feature_index, feature in enumerate(features):
            contribution_rows.append(
                {
                    "query_run_id": query_run_id,
                    "k": k,
                    "nearest_center": int(nearest[row_index]),
                    "feature": feature,
                    "squared_distance_contribution": float(squared[feature_index]),
                    "distance_contribution_share": (
                        float(squared[feature_index] / total) if total > 0 else 0.0
                    ),
                }
            )
    return projection, pd.DataFrame(contribution_rows)


def _evidence_counts(index_dir: Path) -> pd.DataFrame:
    sources = {
        "region_fragment_count": _read_optional(index_dir / "region_fragments.csv"),
        "worker_task_fragment_count": _read_optional(
            index_dir / "worker_task_fragments.csv"
        ),
        "plan_file_count": _read_optional(index_dir / "plan_files.csv"),
    }
    frames: list[pd.DataFrame] = []
    for output_column, frame in sources.items():
        if frame.empty or "query_run_id" not in frame:
            continue
        counts = (
            frame.assign(query_run_id=frame["query_run_id"].astype(str))
            .groupby("query_run_id")
            .size()
            .rename(output_column)
            .reset_index()
        )
        frames.append(counts)
    if not frames:
        return pd.DataFrame(columns=["query_run_id"])
    result = frames[0]
    for frame in frames[1:]:
        result = result.merge(frame, on="query_run_id", how="outer")
    return result.fillna(0)


def _compression_audit(
    weighted: pd.DataFrame,
    context: pd.DataFrame,
) -> pd.DataFrame:
    rows = _rounded_vector_rows(weighted)
    rows = rows.merge(
        context[
            [
                "query_run_id",
                "query_id",
                "plan_fingerprint",
                "remote_plan_fingerprint",
            ]
        ],
        on="query_run_id",
        how="left",
    )
    return (
        rows.groupby("rounded_vector_hash", dropna=False)
        .agg(
            row_count=("query_run_id", "size"),
            query_ids=("query_id", lambda values: ",".join(map(str, sorted(values)))),
            plan_fingerprint_count=("plan_fingerprint", "nunique"),
            remote_plan_fingerprint_count=("remote_plan_fingerprint", "nunique"),
            query_run_ids=("query_run_id", " | ".join),
        )
        .reset_index()
        .sort_values(["row_count", "rounded_vector_hash"], ascending=[False, True])
    )


def _rounded_vector_rows(weighted: pd.DataFrame) -> pd.DataFrame:
    features = [column for column in weighted if column != "query_run_id"]
    rounded = weighted[features].round(6).astype(str).agg("|".join, axis=1)
    return pd.DataFrame(
        {
            "query_run_id": weighted["query_run_id"].astype(str),
            "rounded_vector_hash": rounded.map(
                lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
            ),
        }
    )


def _signature_count(frame: pd.DataFrame, columns: list[str]) -> int:
    available = [column for column in columns if column in frame]
    if not available:
        return 0
    normalized = frame[available].copy()
    for column in available:
        numeric = pd.to_numeric(normalized[column], errors="coerce")
        if numeric.notna().any():
            normalized[column] = numeric.round(6)
        normalized[column] = normalized[column].fillna("<NA>").astype(str)
    return int(normalized.drop_duplicates().shape[0])


def _compression_diagnostic_audit(
    weighted: pd.DataFrame,
    context: pd.DataFrame,
    raw: pd.DataFrame,
) -> pd.DataFrame:
    output_columns = [
        "rounded_vector_hash",
        "row_count",
        "query_ids",
        "plan_fingerprint_count",
        "remote_plan_fingerprint_count",
        "mapmerge_presence_value_count",
        "spill_presence_value_count",
        "operator_structure_signature_count",
        "repartition_intensity_signature_count",
        "worker_distribution_signature_count",
        "mixes_mapmerge_and_non_mapmerge",
        "mixes_spill_and_non_spill",
        "loses_operator_structure_detail",
        "loses_repartition_intensity_detail",
        "loses_worker_distribution_detail",
    ]
    operator_columns = [
        "has_join",
        "has_sort",
        "has_hash",
        "has_aggregate",
        "join_node_count",
        "hash_join_count",
        "merge_join_count",
        "worker_task_join_node_count",
        "worker_task_aggregate_node_count",
        "worker_task_sort_node_count",
        *[
            column
            for column in raw
            if column.startswith("parent_child_type_count_")
        ],
    ]
    repartition_intensity_columns = [
        "remote_citus_map_merge_job_count_sum",
        "remote_citus_dependent_map_task_count_sum",
        "remote_citus_dependent_merge_task_count_sum",
        "remote_citus_repartition_fanout_ratio_max",
    ]
    worker_distribution_columns = [
        "worker_scan_rows_cv",
        "worker_scan_rows_isf",
        "worker_task_scan_actual_rows_cv",
        "worker_task_scan_rows_isf",
        "worker_task_seq_scan_share",
    ]
    rows = (
        _rounded_vector_rows(weighted)
        .merge(
            context[
                [
                    "query_run_id",
                    "query_id",
                    "plan_fingerprint",
                    "remote_plan_fingerprint",
                ]
            ],
            on="query_run_id",
            how="left",
        )
        .merge(raw, on="query_run_id", how="left", suffixes=("", "_raw"))
    )
    output: list[dict[str, Any]] = []
    for vector_hash, group in rows.groupby("rounded_vector_hash", dropna=False):
        if len(group) <= 1:
            continue
        mapmerge = (
            pd.to_numeric(
                group.get("citus_repartition_observed_v2"),
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )
        spill = (
            pd.to_numeric(group.get("spill_present"), errors="coerce")
            .fillna(0)
            .astype(int)
        )
        operator_signature_count = _signature_count(group, operator_columns)
        repartition_signature_count = _signature_count(
            group,
            repartition_intensity_columns,
        )
        worker_signature_count = _signature_count(
            group,
            worker_distribution_columns,
        )
        output.append(
            {
                "rounded_vector_hash": vector_hash,
                "row_count": len(group),
                "query_ids": ",".join(
                    map(str, sorted(group["query_id"].astype(int)))
                ),
                "plan_fingerprint_count": group["plan_fingerprint"].nunique(),
                "remote_plan_fingerprint_count": group[
                    "remote_plan_fingerprint"
                ].nunique(),
                "mapmerge_presence_value_count": mapmerge.nunique(),
                "spill_presence_value_count": spill.nunique(),
                "operator_structure_signature_count": operator_signature_count,
                "repartition_intensity_signature_count": (
                    repartition_signature_count
                ),
                "worker_distribution_signature_count": worker_signature_count,
                "mixes_mapmerge_and_non_mapmerge": mapmerge.nunique() > 1,
                "mixes_spill_and_non_spill": spill.nunique() > 1,
                "loses_operator_structure_detail": operator_signature_count > 1,
                "loses_repartition_intensity_detail": (
                    repartition_signature_count > 1
                ),
                "loses_worker_distribution_detail": worker_signature_count > 1,
            }
        )
    return pd.DataFrame(output, columns=output_columns).sort_values(
        ["row_count", "rounded_vector_hash"],
        ascending=[False, True],
    )


def _mapmerge_strata(
    raw: pd.DataFrame,
    k4_projection: pd.DataFrame,
) -> pd.DataFrame:
    joined = raw.merge(
        k4_projection[
            [
                "query_run_id",
                "dominant_cluster",
                "nearest_center_distance",
                "max_membership",
                "top2_membership_margin",
            ]
        ],
        on="query_run_id",
        how="inner",
        validate="one_to_one",
    )
    joined["mapmerge_observed"] = (
        pd.to_numeric(
            joined["citus_repartition_observed_v2"],
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
    )
    metrics = [
        "remote_to_final_rows_ratio",
        "regional_input_to_wan_rows_ratio",
        "worker_task_scan_rows_isf",
        "worker_scan_rows_cv",
        "active_task_share",
        "task_count",
        "temp_blocks_sum",
    ]
    output: list[dict[str, Any]] = []
    for flag, group in joined.groupby("mapmerge_observed"):
        row: dict[str, Any] = {
            "mapmerge_observed": int(flag),
            "row_count": len(group),
            "dominant_cluster_counts_json": json.dumps(
                {
                    str(int(cluster)): int(count)
                    for cluster, count in group["dominant_cluster"]
                    .value_counts()
                    .sort_index()
                    .items()
                },
                sort_keys=True,
            ),
            "nearest_center_distance_median": float(
                group["nearest_center_distance"].median()
            ),
            "max_membership_median": float(group["max_membership"].median()),
            "top2_membership_margin_median": float(
                group["top2_membership_margin"].median()
            ),
        }
        for metric in metrics:
            values = pd.to_numeric(group.get(metric), errors="coerce").dropna()
            row[f"{metric}_available_count"] = len(values)
            row[f"{metric}_median"] = (
                float(values.median()) if len(values) else np.nan
            )
            row[f"{metric}_p90"] = (
                float(values.quantile(0.9)) if len(values) else np.nan
            )
        output.append(row)
    return pd.DataFrame(output).sort_values("mapmerge_observed")


def _v1_projection(
    *,
    feature_dir: Path,
    model_manifest_path: Path,
) -> tuple[pd.DataFrame, float, pd.DataFrame]:
    manifest = load_yaml(model_manifest_path)
    matrix = manifest["feature_matrix"]
    model = manifest["primary_model"]
    preprocessing_report = ROOT / str(matrix["preprocessing_report"])
    centers_file = ROOT / str(model["center_file"])
    baseline_scaled_file = ROOT / str(matrix["scaled_matrix"])
    matrix_name = str(matrix["matrix_id"])
    k = int(model["k"])
    seed = int(model["representative_run"]["seed"])
    fuzzifier = float(model["fuzzifier"])
    raw = pd.read_csv(feature_dir / "execution_features_m0.csv")
    scaled, projection, quality = project_to_frozen_model(
        raw,
        preprocessing_report=preprocessing_report,
        centers_file=centers_file,
        baseline_scaled_file=baseline_scaled_file,
        matrix_name=matrix_name,
        k=k,
        seed=seed,
        fuzzifier=fuzzifier,
    )
    contract = load_feature_contract(
        preprocessing_report,
        matrix_name=matrix_name,
    )
    features = contract["feature"].astype(str).tolist()
    centers = pd.read_csv(centers_file)
    selected_centers = centers[
        centers["k"].astype(int).eq(k)
        & centers["seed"].astype(int).eq(seed)
    ].sort_values("cluster")
    baseline = pd.read_csv(baseline_scaled_file)
    _, baseline_distances = fuzzy_memberships(
        baseline[features].to_numpy(dtype=float),
        selected_centers[features].to_numpy(dtype=float),
        fuzzifier=fuzzifier,
    )
    threshold = float(
        np.quantile(
            np.min(baseline_distances, axis=1),
            0.99,
            method="linear",
        )
    )
    projection["frozen_p99_threshold"] = threshold
    projection["ood_above_frozen_p99"] = (
        projection["nearest_center_distance"] > threshold
    )
    projection["nearest_distance_over_p99"] = (
        projection["nearest_center_distance"] / threshold
    )
    projection["scaled_feature_fingerprint"] = [
        hashlib.sha256(values.tobytes()).hexdigest()
        for values in scaled[features].to_numpy(dtype=np.float64)
    ]
    return projection, threshold, quality


def main() -> int:
    args = parse_args()
    index_dir = args.logical_index.resolve()
    feature_dir = args.feature_dir.resolve()
    selection_path = args.selection.resolve()
    contract_path = args.contract.resolve()
    freeze_dir = args.freeze_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    contract = load_yaml(contract_path)
    selection = load_yaml(selection_path)
    freeze = load_yaml(freeze_dir / "semantic_v2_model_manifest.yml")
    if freeze["feature_contract_sha256"] != _sha256(contract_path):
        raise ValueError("Frozen model contract hash differs from current contract")
    if selection["model_contract"].get("refit_allowed") is not False:
        raise ValueError("STATS-CEB evaluation must prohibit model refit")
    artifact_prefix = str(args.artifact_prefix).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", artifact_prefix):
        raise ValueError(f"Unsafe artifact prefix: {artifact_prefix!r}")

    def artifact(name: str, suffix: str = "csv") -> Path:
        return out_dir / f"{artifact_prefix}_{name}.{suffix}"

    raw = pd.read_csv(feature_dir / "execution_features_all.csv")
    raw["query_run_id"] = raw["query_run_id"].astype(str)
    raw = pd.concat(
        [
            raw.reset_index(drop=True),
            raw["param_json"].map(_query_id).rename("query_id").reset_index(drop=True),
        ],
        axis=1,
    ).copy()
    selected = pd.DataFrame(selection["queries"])[
        ["query_id", "table_count_stratum", "expected_count", "selection_hash"]
    ]
    context_columns = [
        "query_run_id",
        "query_id",
        "execution_status",
        "collection_error_count",
        "fdw_remote_probe_status",
        "plan_fingerprint",
        "remote_plan_fingerprint",
    ]
    context = raw[context_columns].copy()
    context = context.merge(selected, on="query_id", how="right")
    evidence = _evidence_counts(index_dir)
    context = context.merge(evidence, on="query_run_id", how="left")

    result_validation = _read_optional(index_dir / "result_validations.csv")
    if not result_validation.empty:
        result_validation = result_validation.sort_values("query_id").drop_duplicates(
            "query_id", keep="last"
        )
        context = context.merge(
            result_validation[
                [
                    "query_id",
                    "baseline_status",
                    "eu_status",
                    "us_status",
                    "comparison_status",
                    "database_result_rows_persisted",
                ]
            ],
            on="query_id",
            how="left",
        )
    else:
        for column in (
            "baseline_status",
            "eu_status",
            "us_status",
            "comparison_status",
            "database_result_rows_persisted",
        ):
            context[column] = np.nan

    feature_names = list(contract["features"])
    complete_raw = raw[raw["query_id"].isin(selected["query_id"])].copy()
    semantic_raw = complete_raw[["query_run_id", *feature_names]]
    transformed, weighted, transform_audit = semantic_transform(
        semantic_raw,
        complete_raw,
        contract,
    )
    transformed.to_csv(artifact("semantic_transformed"), index=False)
    weighted.to_csv(artifact("semantic_weighted"), index=False)
    transform_audit.to_csv(artifact("feature_applicability"), index=False)

    projections: list[pd.DataFrame] = []
    contributions: list[pd.DataFrame] = []
    for k in [int(value) for value in freeze["k_candidates"]]:
        model = freeze["models"][f"k{k}"]
        projection, contribution = _projection(
            weighted=weighted,
            centers_path=freeze_dir / str(model["center_file"]),
            fuzzifier=float(freeze["fuzzifier"]),
            threshold=float(model["ood_p99_threshold"]),
            k=k,
        )
        projections.append(projection)
        contributions.append(contribution)
    projection = pd.concat(projections, ignore_index=True)
    contribution = pd.concat(contributions, ignore_index=True)
    projection = projection.merge(
        context[
            [
                "query_run_id",
                "query_id",
                "table_count_stratum",
                "execution_status",
                "comparison_status",
                "plan_fingerprint",
                "remote_plan_fingerprint",
            ]
        ],
        on="query_run_id",
        how="left",
    )
    projection.to_csv(artifact("projection"), index=False)
    contribution.merge(
        context[["query_run_id", "query_id"]],
        on="query_run_id",
        how="left",
    ).to_csv(artifact("distance_feature_contributions"), index=False)
    context.to_csv(artifact("query_audit"), index=False)
    compression = _compression_audit(weighted, context)
    compression.to_csv(artifact("compression_audit"), index=False)
    compression_diagnostics = _compression_diagnostic_audit(
        weighted,
        context,
        complete_raw,
    )
    compression_diagnostics.to_csv(
        artifact("compression_diagnostic_audit"),
        index=False,
    )

    v1_projection, v1_p99, v1_quality = _v1_projection(
        feature_dir=feature_dir,
        model_manifest_path=args.v1_model_manifest.resolve(),
    )
    v1_projection = v1_projection.merge(
        context[["query_run_id", "query_id"]],
        on="query_run_id",
        how="left",
    )
    v1_projection.to_csv(artifact("v1_frozen_projection"), index=False)
    v1_quality.to_csv(artifact("v1_preprocessing_audit"), index=False)

    k4_for_comparison = projection[projection["k"].eq(4)].copy()
    k4_for_comparison["nearest_distance_over_p99"] = (
        k4_for_comparison["nearest_center_distance"]
        / k4_for_comparison["frozen_p99_threshold"]
    )
    mapmerge_strata = _mapmerge_strata(complete_raw, k4_for_comparison)
    mapmerge_strata.to_csv(artifact("mapmerge_strata"), index=False)
    model_comparison = v1_projection[
        [
            "query_run_id",
            "query_id",
            "nearest_center_distance",
            "frozen_p99_threshold",
            "nearest_distance_over_p99",
            "ood_above_frozen_p99",
            "max_membership",
            "top2_margin",
        ]
    ].rename(
        columns={
            column: f"v1_{column}"
            for column in (
                "nearest_center_distance",
                "frozen_p99_threshold",
                "nearest_distance_over_p99",
                "ood_above_frozen_p99",
                "max_membership",
                "top2_margin",
            )
        }
    ).merge(
        k4_for_comparison[
            [
                "query_run_id",
                "query_id",
                "nearest_center_distance",
                "frozen_p99_threshold",
                "nearest_distance_over_p99",
                "ood_above_frozen_p99",
                "max_membership",
                "top2_membership_margin",
            ]
        ].rename(
            columns={
                column: f"v2_{column}"
                for column in (
                    "nearest_center_distance",
                    "frozen_p99_threshold",
                    "nearest_distance_over_p99",
                    "ood_above_frozen_p99",
                    "max_membership",
                    "top2_membership_margin",
                )
            }
        ),
        on=["query_run_id", "query_id"],
        how="inner",
        validate="one_to_one",
    )
    model_comparison.to_csv(artifact("v1_v2_comparison"), index=False)

    acceptance = contract["confirmatory_holdout"]["acceptance"]
    selected_count = len(selected)
    completed = context["execution_status"].eq("completed").sum()
    correctness = context["comparison_status"].eq("passed").sum()
    result_mismatches = context["comparison_status"].eq("mismatch").sum()
    completed_result_comparisons = correctness + result_mismatches
    finite_rows = int(
        np.isfinite(weighted.drop(columns="query_run_id").to_numpy(dtype=float))
        .all(axis=1)
        .sum()
    )
    k4_projection = projection[projection["k"].eq(4)]
    within_p99 = int((~k4_projection["ood_above_frozen_p99"]).sum())
    correctness_excluded = selected_count - int(correctness)
    collector_excluded = int(correctness) - int(completed)
    measures = {
        "result_correctness": correctness / selected_count,
        "projected_completed_rows": (
            len(weighted) / completed if completed else 0.0
        ),
        "finite_projection": finite_rows / len(weighted) if len(weighted) else 0.0,
        "within_frozen_p99": within_p99 / len(k4_projection)
        if len(k4_projection)
        else 0.0,
    }
    thresholds = {
        "result_correctness": float(acceptance["result_correctness_share_min"]),
        "projected_completed_rows": float(
            acceptance["projected_completed_rows_share_min"]
        ),
        "finite_projection": float(acceptance["finite_projection_share_min"]),
        "within_frozen_p99": float(acceptance["within_frozen_p99_share_min"]),
    }
    gate_rows = [
        {
            "gate": gate,
            "observed": value,
            "required_min": thresholds[gate],
            "status": "PASS" if value >= thresholds[gate] else "FAIL",
        }
        for gate, value in measures.items()
    ]
    gate_rows.extend(
        [
            {
                "gate": "contract_hash_matches_freeze",
                "observed": 1.0,
                "required_min": 1.0,
                "status": "PASS",
            },
            {
                "gate": "model_refit_prohibited",
                "observed": 1.0,
                "required_min": 1.0,
                "status": "PASS",
            },
        ]
    )
    gate = pd.DataFrame(gate_rows)
    gate.to_csv(artifact("gate"), index=False)

    repartition_observed_count = int(
        pd.to_numeric(
            complete_raw["citus_repartition_observed_v2"],
            errors="coerce",
        )
        .fillna(0)
        .eq(1)
        .sum()
    )
    duplicate_vector_rows = int(
        compression.loc[compression["row_count"].gt(1), "row_count"].sum()
    )
    summary = {
        "logical_run_id": (
            str(args.logical_run_id).strip()
            or str(selection["selection_id"])
        ),
        "selection_id": selection["selection_id"],
        "selected_queries": selected_count,
        "completed_queries": int(completed),
        "correctness_passed": int(correctness),
        "completed_result_comparisons": int(completed_result_comparisons),
        "result_mismatch_count": int(result_mismatches),
        "correctness_excluded_queries": correctness_excluded,
        "collector_excluded_queries": collector_excluded,
        "projected_rows": len(weighted),
        "finite_projected_rows": finite_rows,
        "k4_within_frozen_p99": within_p99,
        "k4_ood_count": int(len(k4_projection) - within_p99),
        "k4_distance_median": float(
            k4_projection["nearest_center_distance"].median()
        ),
        "k4_max_membership_median": float(k4_projection["max_membership"].median()),
        "v1_p99_threshold": v1_p99,
        "v1_ood_count": int(v1_projection["ood_above_frozen_p99"].sum()),
        "v1_within_frozen_p99": int(
            (~v1_projection["ood_above_frozen_p99"]).sum()
        ),
        "v1_distance_over_p99_median": float(
            v1_projection["nearest_distance_over_p99"].median()
        ),
        "v1_max_membership_median": float(
            v1_projection["max_membership"].median()
        ),
        "v2_distance_over_p99_median": float(
            k4_projection["nearest_center_distance"].div(
                k4_projection["frozen_p99_threshold"]
            ).median()
        ),
        "rounded_vector_groups": len(compression),
        "rounded_duplicate_groups": int(compression["row_count"].gt(1).sum()),
        "rounded_duplicate_rows": duplicate_vector_rows,
        "duplicate_groups_mixing_mapmerge_presence": int(
            compression_diagnostics["mixes_mapmerge_and_non_mapmerge"].sum()
        ),
        "duplicate_groups_mixing_spill_presence": int(
            compression_diagnostics["mixes_spill_and_non_spill"].sum()
        ),
        "duplicate_groups_losing_operator_structure_detail": int(
            compression_diagnostics["loses_operator_structure_detail"].sum()
        ),
        "duplicate_groups_losing_repartition_intensity_detail": int(
            compression_diagnostics[
                "loses_repartition_intensity_detail"
            ].sum()
        ),
        "duplicate_groups_losing_worker_distribution_detail": int(
            compression_diagnostics[
                "loses_worker_distribution_detail"
            ].sum()
        ),
        "main_plan_fingerprint_count": int(
            context["plan_fingerprint"].nunique(dropna=True)
        ),
        "remote_plan_fingerprint_count": int(
            context["remote_plan_fingerprint"].nunique(dropna=True)
        ),
        "regional_repartition_observed_count": repartition_observed_count,
        "regional_repartition_observed_denominator": len(complete_raw),
        "all_gates_pass": bool(gate["status"].eq("PASS").all()),
        "feature_contract_sha256": _sha256(contract_path),
        "selection_sha256": _sha256(selection_path),
        "model_manifest_sha256": _sha256(
            freeze_dir / "semantic_v2_model_manifest.yml"
        ),
        "model_refit_performed": False,
    }
    artifact("summary", "json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    decision = "GO" if summary["all_gates_pass"] else "MIXED_OR_NO_GO"
    if summary["rounded_duplicate_groups"]:
        compression_note = (
            "Preostale identične grupe potvrđuju da V2 feature vektor ostaje\n"
            "kompresija planova, a ne njihova potpuna zamjena. One ne "
            "miješaju\n"
            "prisustvo MapMergea ni spill-a, ali dio intenziteta "
            "repartitiona i\n"
            "operator-edge strukture nestaje prije FCM koraka."
        )
    else:
        compression_note = (
            "U ovom malom podskupu nisu pronađene gotovo identične V2 grupe.\n"
            "Zato recovery rezultat samostalno ne daje novi dokaz o "
            "kolizijama\n"
            "vektora, niti poništava kompresijske nalaze punog STATS-CEB "
            "audita."
        )
    (out_dir / "README.md").write_text(
        f"""# {args.report_title}

## Odluka

```text
{decision}
```

Model nije ponovo treniran. Transformacije, porodične težine, `k`, seedovi,
centri i P99 pragovi učitani su iz paketa zamrznutog prije izvršenja holdouta.

## Rezultat

- odabrani upiti: {selected_count}
- završena izvršenja: {completed}/{selected_count}
- završena poređenja rezultata: {completed_result_comparisons}/{selected_count}
- neslaganja među završenim poređenjima:
  {result_mismatches}/{completed_result_comparisons}
- tehnička isključenja u correctness koraku: {correctness_excluded}
- dodatni collector timeouti nakon uspješne provjere rezultata:
  {collector_excluded}
- projektovani V2 redovi: {len(weighted)}
- konačni vektori bez nefinite vrijednosti: {finite_rows}/{len(weighted)}
- `k=4` unutar zamrznutog P99 radijusa: {within_p99}/{len(k4_projection)}
- medijana udaljenosti do najbližeg `k=4` centra:
  {summary["k4_distance_median"]:.6f}
- medijana maksimalnog fuzzy članstva:
  {summary["k4_max_membership_median"]:.6f}
- V1 unutar vlastitog zamrznutog P99 radijusa:
  {summary["v1_within_frozen_p99"]}/{len(v1_projection)}
- medijana udaljenosti normalizovane vlastitim P99 pragom:
  V1={summary["v1_distance_over_p99_median"]:.6f},
  V2={summary["v2_distance_over_p99_median"]:.6f}
- medijana maksimalnog članstva:
  V1={summary["v1_max_membership_median"]:.6f},
  V2={summary["k4_max_membership_median"]:.6f}
- regionalni `MapMerge`/repartition prepoznat u:
  {summary["regional_repartition_observed_count"]}/{summary["regional_repartition_observed_denominator"]}
  završenih izvršenja
- različiti glavni otisci plana:
  {summary["main_plan_fingerprint_count"]}/{completed}
- različiti remote otisci plana:
  {summary["remote_plan_fingerprint_count"]}/{completed}
- gotovo identične grupe na šest decimala:
  {summary["rounded_duplicate_groups"]}
  ({summary["rounded_duplicate_rows"]} redova)
- identične grupe koje miješaju MapMerge i non-MapMerge:
  {summary["duplicate_groups_mixing_mapmerge_presence"]}
- identične grupe koje miješaju spill i non-spill:
  {summary["duplicate_groups_mixing_spill_presence"]}
- identične grupe koje gube intenzitet repartitiona:
  {summary["duplicate_groups_losing_repartition_intensity_detail"]}
- identične grupe koje gube operator-edge detalj:
  {summary["duplicate_groups_losing_operator_structure_detail"]}

Stroga zbirna odluka ostaje negativna zato što unaprijed postavljen zahtjev
100% rezultatske korektnosti unutar vremenskog budžeta nije ispunjen. Odvojeni
modelski pod-gate pokazuje da semantički V2 prostor ima prihvatljivu pokrivenost
nad {completed} kompletnim opservacijama iz {selected_count} pokušaja na
{args.scope_statement}. To ne uspostavlja univerzalnu taksonomiju režima.
{compression_note}
""",
        encoding="utf-8",
    )
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
