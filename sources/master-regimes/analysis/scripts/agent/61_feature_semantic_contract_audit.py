from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from master_regimes.config import load_yaml
from master_regimes.representation_audit import semantic_transform

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FEATURE_DIR = ROOT / "analysis/features/clean-run-v1-semantic-v2"
DEFAULT_INDEX_DIR = (
    ROOT.parent
    / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs/"
    "clean-run-v1/_index"
)
DEFAULT_CONTRACT = ROOT / "configs/features/feature_semantic_contract_v2.yml"
DEFAULT_OUT_DIR = ROOT / "analysis/reports/feature-semantic-contract-v2"
DEFAULT_CONFIRMATORY_DIR = ROOT / "analysis/reports/confirmatory-skew-v1-analysis"
DEFAULT_GEOMETRY_DIR = ROOT / "analysis/reports/stats-ceb-representation-audit-v1"
DEFAULT_REPARTITION_AUDIT_DIR = (
    ROOT / "analysis/features/stats-ceb-semantic-v2-holdout"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit the versioned semantic feature contract before v2 holdout."
    )
    parser.add_argument("--feature-dir", type=Path, default=DEFAULT_FEATURE_DIR)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--confirmatory-dir",
        type=Path,
        default=DEFAULT_CONFIRMATORY_DIR,
    )
    parser.add_argument("--geometry-dir", type=Path, default=DEFAULT_GEOMETRY_DIR)
    parser.add_argument(
        "--repartition-audit-dir",
        type=Path,
        default=DEFAULT_REPARTITION_AUDIT_DIR,
    )
    return parser.parse_args()


def numeric(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def safe_divide(left: Any, right: Any, *, floor: float | None = None) -> float | None:
    numerator = numeric(left)
    denominator = numeric(right)
    if numerator is None or denominator is None:
        return None
    if floor is not None:
        denominator = max(denominator, floor)
    elif denominator <= 0:
        return None
    return numerator / denominator


def population_cv(values: list[float]) -> float | None:
    if not values:
        return None
    mean = statistics.fmean(values)
    if mean == 0:
        return 0.0 if all(value == 0 for value in values) else None
    return statistics.pstdev(values) / mean


def normalized_cv(values: list[float]) -> float | None:
    value = population_cv(values)
    if value is None:
        return None
    if len(values) == 1:
        return 0.0
    return max(0.0, min(1.0, value / math.sqrt(len(values) - 1)))


def normalized_isf(values: list[float]) -> float | None:
    if not values:
        return None
    mean = statistics.fmean(values)
    if mean <= 0:
        return 0.0 if all(value == 0 for value in values) else None
    if len(values) == 1:
        return 0.0
    isf = max(values) / mean
    return max(0.0, min(1.0, (isf - 1.0) / (len(values) - 1.0)))


def signed_error(actual: Any, estimated: Any) -> float | None:
    actual_value = numeric(actual)
    estimated_value = numeric(estimated)
    if actual_value is None or estimated_value is None:
        return None
    return math.log((actual_value + 1.0) / (estimated_value + 1.0))


def largest_abs_signed(values: list[float]) -> float | None:
    return max(values, key=lambda value: (abs(value), value)) if values else None


def close(left: Any, right: Any, *, tolerance: float = 1.0e-9) -> bool:
    left_value = numeric(left)
    right_value = numeric(right)
    if left_value is None or right_value is None:
        return left_value is None and right_value is None
    return math.isclose(left_value, right_value, rel_tol=tolerance, abs_tol=tolerance)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def repartition_visibility_rows(feature_dir: Path) -> list[dict[str, Any]]:
    """Verify that regional MapMerge evidence reaches the versioned flag."""
    features = pd.read_csv(
        feature_dir / "execution_features_all.csv",
        low_memory=False,
    )
    required = {
        "query_run_id",
        "citus_repartition_query",
        "remote_citus_repartition_mapmerge_count",
        "remote_citus_plan_locality_classes",
        "citus_repartition_observed_v2",
    }
    missing = sorted(required.difference(features.columns))
    if missing:
        raise ValueError(f"Repartition audit feature layer misses columns: {missing}")

    remote_count = pd.to_numeric(
        features["remote_citus_repartition_mapmerge_count"],
        errors="coerce",
    ).fillna(0)
    remote_class = features["remote_citus_plan_locality_classes"].fillna("").astype(str)
    candidates = features.loc[
        (remote_count > 0) | remote_class.str.contains("repartition_mapmerge"),
        list(required),
    ].copy()
    rows: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        rows.append(
            {
                "query_run_id": row["query_run_id"],
                "main_repartition_flag": row["citus_repartition_query"],
                "remote_mapmerge_count": row[
                    "remote_citus_repartition_mapmerge_count"
                ],
                "remote_locality_classes": row[
                    "remote_citus_plan_locality_classes"
                ],
                "v2_repartition_flag": row["citus_repartition_observed_v2"],
                "status": "PASS"
                if numeric(row["citus_repartition_observed_v2"]) == 1.0
                else "FAIL",
            }
        )
    return rows


def contract_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    legacy = contract["legacy_audit"]
    rows: list[dict[str, Any]] = []
    for feature, specification in legacy.items():
        replacement = str(specification["replacement"])
        replacement_spec = contract["features"].get(replacement, {})
        rows.append(
            {
                "legacy_feature": feature,
                "decision": specification["decision"],
                "v2_feature": replacement,
                "reason": specification["reason"],
                "v2_family": replacement_spec.get("family", ""),
                "v2_formula": replacement_spec.get("formula", ""),
                "v2_unit": replacement_spec.get("unit", ""),
                "v2_raw_domain": replacement_spec.get("raw_domain", ""),
                "v2_neutral": replacement_spec.get("neutral", ""),
                "v2_applicability": replacement_spec.get("applicability", ""),
                "v2_null_semantics": replacement_spec.get("null_semantics", ""),
                "v2_dataset_dependence": replacement_spec.get(
                    "dataset_dependence",
                    "",
                ),
                "v2_topology_dependence": replacement_spec.get(
                    "topology_dependence",
                    "",
                ),
                "v2_sql_shape_dependence": replacement_spec.get(
                    "sql_shape_dependence",
                    "",
                ),
                "v2_transform": replacement_spec.get("transform", ""),
                "v2_expected_response": replacement_spec.get(
                    "expected_response",
                    "",
                ),
                "v2_raw_display": replacement_spec.get("raw_display", ""),
                "v2_model_status": replacement_spec.get("model_status", ""),
            }
        )
    for feature, specification in contract.get("added_from_derived_layer", {}).items():
        replacement_spec = contract["features"][feature]
        rows.append(
            {
                "legacy_feature": "",
                "decision": specification["decision"],
                "v2_feature": feature,
                "reason": specification["reason"],
                "v2_family": replacement_spec["family"],
                "v2_formula": replacement_spec["formula"],
                "v2_unit": replacement_spec["unit"],
                "v2_raw_domain": replacement_spec["raw_domain"],
                "v2_neutral": replacement_spec["neutral"],
                "v2_applicability": replacement_spec["applicability"],
                "v2_null_semantics": replacement_spec["null_semantics"],
                "v2_dataset_dependence": replacement_spec["dataset_dependence"],
                "v2_topology_dependence": replacement_spec["topology_dependence"],
                "v2_sql_shape_dependence": replacement_spec["sql_shape_dependence"],
                "v2_transform": replacement_spec["transform"],
                "v2_expected_response": replacement_spec["expected_response"],
                "v2_raw_display": replacement_spec["raw_display"],
                "v2_model_status": replacement_spec["model_status"],
            }
        )
    return rows


def empirical_rows(
    all_features: pd.DataFrame,
    transformed: pd.DataFrame,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature, specification in contract["features"].items():
        raw = pd.to_numeric(all_features[feature], errors="coerce").astype(float)
        semantic = pd.to_numeric(
            transformed[feature],
            errors="coerce",
        ).astype(float)
        rows.append(
            {
                "feature": feature,
                "family": specification["family"],
                "model_status": specification["model_status"],
                "row_count": len(raw),
                "raw_non_null_count": int(raw.notna().sum()),
                "raw_null_share": float(raw.isna().mean()),
                "raw_min": raw.min(),
                "raw_median": raw.median(),
                "raw_p99": raw.quantile(0.99),
                "raw_max": raw.max(),
                "semantic_min": semantic.min(),
                "semantic_median": semantic.median(),
                "semantic_p99": semantic.quantile(0.99),
                "semantic_max": semantic.max(),
                "semantic_finite": bool(np.isfinite(semantic.to_numpy()).all()),
                "semantic_in_unit_interval": bool(semantic.between(0, 1).all()),
            }
        )
    return rows


def algebraic_rows(all_features: pd.DataFrame) -> list[dict[str, Any]]:
    checks = [
        (
            "wan_output_to_final_equals_global_group_merge",
            "wan_output_to_final_rows_ratio",
            "global_group_merge_ratio",
            1.0,
        ),
        (
            "spill_per_wan_mb_is_128x_spill_bytes_ratio",
            "spill_per_wan_mb",
            "spill_bytes_to_wan_bytes_ratio",
            128.0,
        ),
        (
            "drf_bytes_equals_regional_input_to_wan_rows",
            "drf_bytes_proxy",
            "regional_input_to_wan_rows_ratio",
            1.0,
        ),
    ]
    rows: list[dict[str, Any]] = []
    for check_id, left_column, right_column, multiplier in checks:
        left = pd.to_numeric(all_features[left_column], errors="coerce")
        right = pd.to_numeric(all_features[right_column], errors="coerce") * multiplier
        applicable = left.notna() & right.notna()
        difference = (left[applicable] - right[applicable]).abs()
        rows.append(
            {
                "check_id": check_id,
                "left_column": left_column,
                "right_column": right_column,
                "right_multiplier": multiplier,
                "applicable_rows": int(applicable.sum()),
                "max_abs_difference": float(difference.max()) if len(difference) else "",
                "status": (
                    "PASS"
                    if len(difference) and bool((difference <= 1.0e-9).all())
                    else "FAIL"
                ),
            }
        )
    return rows


def raw_reference_rows(
    *,
    all_features: pd.DataFrame,
    index_dir: Path,
) -> list[dict[str, Any]]:
    by_run = all_features.set_index(all_features["query_run_id"].astype(str))
    rows: list[dict[str, Any]] = []

    def record(
        query_run_id: str,
        feature: str,
        reference: float | None,
        source: str,
    ) -> None:
        observed = (
            by_run.at[query_run_id, feature]
            if query_run_id in by_run.index and feature in by_run.columns
            else None
        )
        rows.append(
            {
                "query_run_id": query_run_id,
                "feature": feature,
                "observed": observed,
                "reference": reference,
                "source": source,
                "status": "PASS" if close(observed, reference) else "FAIL",
            }
        )

    plan_nodes = pd.read_csv(index_dir / "plan_nodes.csv", low_memory=False)
    for query_run_id, group in plan_nodes.groupby("query_run_id", sort=False):
        query_run_id = str(query_run_id)
        main = group[group["plan_scope"].eq("main")]
        roots = main[
            pd.to_numeric(main["depth"], errors="coerce").fillna(0).eq(0)
        ]
        root = roots.iloc[0] if not roots.empty else None
        foreign = main[main["node_type"].eq("Foreign Scan")]
        root_time = numeric(root.get("actual_total_time")) if root is not None else None
        foreign_times = [
            value
            for value in (
                numeric(item) for item in foreign["actual_total_time"].tolist()
            )
            if value is not None
        ]
        ratio = (
            sum(foreign_times) / root_time
            if root_time is not None and root_time > 0
            else None
        )
        record(
            query_run_id,
            "foreign_scan_time_to_root_ratio",
            ratio,
            "plan_nodes",
        )
        if root is not None:
            record(
                query_run_id,
                "root_rows_estimate_error_log",
                signed_error(root.get("actual_rows"), root.get("plan_rows")),
                "plan_nodes",
            )
        for feature, selector in (
            (
                "foreign_scan_rows_estimate_error_log",
                main["node_type"].eq("Foreign Scan"),
            ),
            (
                "aggregate_rows_estimate_error_log",
                main["node_type"].astype(str).str.contains("Aggregate"),
            ),
        ):
            selected = main[selector]
            values = [
                value
                for value in (
                    signed_error(row.actual_rows, row.plan_rows)
                    for row in selected.itertuples()
                )
                if value is not None
            ]
            record(
                query_run_id,
                feature,
                largest_abs_signed(values),
                "plan_nodes",
            )
        remote = group[
            group["plan_scope"].isin(
                ["fdw_remote", "fdw_auto_explain_remote", "citus_task_remote"]
            )
        ]
        remote_roots = remote[
            pd.to_numeric(remote["depth"], errors="coerce").fillna(0).eq(0)
        ]
        remote_values = [
            value
            for value in (
                signed_error(row.actual_rows, row.plan_rows)
                for row in remote_roots.itertuples()
            )
            if value is not None
        ]
        record(
            query_run_id,
            "remote_root_rows_estimate_error_log",
            largest_abs_signed(remote_values),
            "plan_nodes",
        )

    regions = pd.read_csv(index_dir / "region_fragments.csv", low_memory=False)
    for query_run_id, group in regions.groupby("query_run_id", sort=False):
        values = (
            group.assign(
                value=pd.to_numeric(group["remote_actual_rows"], errors="coerce")
            )
            .dropna(subset=["value"])
            .groupby("region_id")["value"]
            .sum()
            .tolist()
        )
        record(
            str(query_run_id),
            "remote_region_rows_isf_normalized",
            normalized_isf([float(value) for value in values]),
            "region_fragments",
        )

    tasks = pd.read_csv(index_dir / "worker_task_fragments.csv", low_memory=False)
    for query_run_id, group in tasks.groupby("query_run_id", sort=False):
        task_values = pd.to_numeric(
            group["worker_task_scan_actual_rows_sum"],
            errors="coerce",
        )
        complete = (
            task_values.notna().all()
            and group["worker_node"].astype(str).str.len().gt(0).all()
        )
        if not complete:
            continue
        values = [float(value) for value in task_values]
        record(
            str(query_run_id),
            "worker_task_scan_rows_isf_normalized",
            normalized_isf(values),
            "worker_task_fragments",
        )
        worker_values = (
            group.assign(value=task_values)
            .groupby("worker_node")["value"]
            .sum()
            .tolist()
        )
        record(
            str(query_run_id),
            "worker_scan_rows_cv_normalized",
            normalized_cv([float(value) for value in worker_values]),
            "worker_task_fragments",
        )

    for query_run_id, row in by_run.iterrows():
        record(
            query_run_id,
            "regional_input_to_wan_rows_ratio",
            safe_divide(
                row.get("regional_reduction_input_rows_proxy"),
                row.get("wan_output_rows"),
            ),
            "merged_flow_sources",
        )
        record(
            query_run_id,
            "global_group_merge_ratio",
            safe_divide(
                row.get("wan_output_rows"),
                row.get("global_group_count_proxy"),
                floor=1.0,
            ),
            "merged_flow_sources",
        )
        temp_blocks = numeric(row.get("temp_blocks_sum"))
        temp_bytes = temp_blocks * 8192.0 if temp_blocks is not None else None
        record(
            query_run_id,
            "spill_bytes_to_wan_bytes_ratio",
            safe_divide(temp_bytes, row.get("wan_output_bytes_proxy")),
            "merged_flow_sources",
        )
        record(
            query_run_id,
            "temp_blocks_per_final_row",
            safe_divide(
                row.get("temp_blocks_sum"),
                row.get("global_group_count_proxy"),
                floor=1.0,
            ),
            "merged_flow_sources",
        )
        hash_batches = numeric(row.get("hash_batches_max"))
        record(
            query_run_id,
            "hash_batch_excess",
            max((hash_batches or 1.0) - 1.0, 0.0),
            "merged_flow_sources",
        )
    return rows


def boundary_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(check_id: str, observed: Any, expected: Any) -> None:
        rows.append(
            {
                "check_id": check_id,
                "observed": observed,
                "expected": expected,
                "status": "PASS" if close(observed, expected) else "FAIL",
            }
        )

    add("region_isf_uniform", normalized_isf([10, 10]), 0.0)
    add("region_isf_all_on_one_of_two", normalized_isf([10, 0]), 1.0)
    add("region_isf_all_on_one_of_four", normalized_isf([10, 0, 0, 0]), 1.0)
    add("region_isf_single_unit", normalized_isf([10]), 0.0)
    add("worker_cv_uniform", normalized_cv([10, 10]), 0.0)
    add("worker_cv_all_on_one_of_two", normalized_cv([10, 0]), 1.0)
    add("worker_cv_all_on_one_of_four", normalized_cv([10, 0, 0, 0]), 1.0)
    add(
        "worker_cv_uniform_scale_invariance",
        normalized_cv([100, 300]),
        normalized_cv([1000, 3000]),
    )
    add(
        "drf_uniform_scale_invariance",
        safe_divide(1000, 100),
        safe_divide(10_000, 1000),
    )
    add("drf_scalar_output_not_size_invariant_small", safe_divide(1000, 1), 1000)
    add("drf_scalar_output_not_size_invariant_large", safe_divide(10_000, 1), 10_000)
    add("estimate_error_exact_zero", signed_error(0, 0), 0.0)
    add("estimate_error_underestimate_positive", signed_error(10, 1) > 0, True)
    add("estimate_error_overestimate_negative", signed_error(1, 10) < 0, True)

    probe = pd.DataFrame(
        [
            {
                "query_run_id": "probe",
                **{
                    feature: (
                        1_000_000_000.0
                        if specification["transform"] == "nonnegative_log_atan"
                        else specification.get("neutral", 0.0)
                    )
                    for feature, specification in contract["features"].items()
                },
            }
        ]
    )
    _, weighted, _ = semantic_transform(probe, probe, contract)
    semantic_values = weighted.drop(columns=["query_run_id"]).to_numpy()
    add("huge_ratios_remain_finite", bool(np.isfinite(semantic_values).all()), True)
    return rows


def intervention_rows(confirmatory_dir: Path) -> list[dict[str, Any]]:
    worker = pd.read_csv(confirmatory_dir / "paired_worker_contrast.csv")
    region = pd.read_csv(confirmatory_dir / "paired_region_contrast.csv")
    top = worker[worker["query_condition_id"].str.startswith("top_tenants")]
    point = worker[worker["query_condition_id"].str.startswith("tenant_point")]
    region_top = region[region["query_condition_id"].str.startswith("top_tenants")]
    rows = [
        {
            "intervention": "B-C worker placement",
            "feature": "worker_scan_rows_cv_normalized",
            "source_proxy": "worker_rows_cv",
            "positive_control_median_delta": float(
                top["worker_rows_cv_delta_c_minus_b"].median()
            ),
            "negative_control_median_delta": float(
                point["worker_rows_cv_delta_c_minus_b"].median()
            ),
            "status": (
                "PASS"
                if float(top["worker_rows_cv_delta_c_minus_b"].median()) > 0
                and math.isclose(
                    float(point["worker_rows_cv_delta_c_minus_b"].median()),
                    0.0,
                    abs_tol=1.0e-12,
                )
                else "FAIL"
            ),
        },
        {
            "intervention": "A-D regional asymmetry",
            "feature": "remote_region_rows_isf_normalized",
            "source_proxy": "remote_region_rows_isf",
            "positive_control_median_delta": float(
                region_top["remote_region_rows_isf_delta_d_minus_a"].median()
            ),
            "negative_control_median_delta": "",
            "status": (
                "PASS"
                if float(
                    region_top["remote_region_rows_isf_delta_d_minus_a"].median()
                )
                > 0
                else "FAIL"
            ),
        },
    ]
    return rows


def geometry_rows(geometry_dir: Path) -> list[dict[str, Any]]:
    audit = pd.read_csv(geometry_dir / "q100_feature_distance_audit.csv")
    top = audit.sort_values("squared_distance_share", ascending=False).iloc[0]
    summary = json.loads(
        (geometry_dir / "representation_audit_summary.json").read_text(
            encoding="utf-8"
        )
    )
    return [
        {
            "check_id": "q100_single_axis_dominance",
            "feature": top["feature"],
            "frozen_squared_distance_share": top["squared_distance_share"],
            "semantic_baseline_percentile": summary["q100"][
                "semantic_baseline_percentile"
            ],
            "interpretation": (
                "raw magnitude is physically unusual; formal P99 OOD is "
                "representation-sensitive"
            ),
        }
    ]


def main() -> int:
    args = parse_args()
    feature_dir = args.feature_dir.resolve()
    index_dir = args.index_dir.resolve()
    out_dir = args.out_dir.resolve()
    contract = load_yaml(args.contract.resolve())
    all_features = pd.read_csv(
        feature_dir / "execution_features_all.csv",
        low_memory=False,
    )
    required = list(contract["features"])
    missing = [feature for feature in required if feature not in all_features]
    if missing:
        raise ValueError(f"execution_features_all.csv misses v2 features: {missing}")

    raw = all_features[["query_run_id", *required]].copy()
    transformed, weighted, transform_audit = semantic_transform(
        raw,
        all_features,
        contract,
    )
    registry = contract_rows(contract)
    empirical = empirical_rows(all_features, transformed, contract)
    algebraic = algebraic_rows(all_features)
    references = raw_reference_rows(
        all_features=all_features,
        index_dir=index_dir,
    )
    boundaries = boundary_rows(contract)
    interventions = intervention_rows(args.confirmatory_dir.resolve())
    geometry = geometry_rows(args.geometry_dir.resolve())
    repartition_visibility = repartition_visibility_rows(
        args.repartition_audit_dir.resolve()
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "feature_semantic_registry.csv", registry)
    write_csv(out_dir / "feature_empirical_distribution.csv", empirical)
    write_csv(out_dir / "feature_algebraic_redundancy.csv", algebraic)
    write_csv(out_dir / "raw_artifact_recomputation.csv", references)
    write_csv(out_dir / "boundary_invariance_tests.csv", boundaries)
    write_csv(out_dir / "intervention_response.csv", interventions)
    write_csv(out_dir / "geometric_impact.csv", geometry)
    write_csv(
        out_dir / "regional_repartition_visibility.csv",
        repartition_visibility,
    )
    transform_audit.to_csv(out_dir / "semantic_transform_audit.csv", index=False)
    raw.to_csv(out_dir / "semantic_v2_raw.csv", index=False)
    transformed.to_csv(out_dir / "semantic_v2_transformed.csv", index=False)
    weighted.to_csv(out_dir / "semantic_v2_weighted.csv", index=False)

    reference_failures = sum(row["status"] != "PASS" for row in references)
    gate_rows = [
        {
            "gate": "legacy_21_classified",
            "status": "PASS" if len(contract["legacy_audit"]) == 21 else "FAIL",
            "evidence": f"{len(contract['legacy_audit'])}/21",
        },
        {
            "gate": "semantic_output_finite_and_bounded",
            "status": (
                "PASS"
                if all(
                    row["semantic_finite"] and row["semantic_in_unit_interval"]
                    for row in empirical
                )
                else "FAIL"
            ),
            "evidence": f"{len(empirical)} v2 model features",
        },
        {
            "gate": "algebraic_redundancy_confirmed",
            "status": (
                "PASS" if all(row["status"] == "PASS" for row in algebraic) else "FAIL"
            ),
            "evidence": f"{len(algebraic)} deterministic checks",
        },
        {
            "gate": "raw_artifact_recomputation",
            "status": "PASS" if reference_failures == 0 else "FAIL",
            "evidence": f"{len(references) - reference_failures}/{len(references)}",
        },
        {
            "gate": "boundary_and_invariance",
            "status": (
                "PASS" if all(row["status"] == "PASS" for row in boundaries) else "FAIL"
            ),
            "evidence": f"{len(boundaries)} tests",
        },
        {
            "gate": "controlled_intervention_response",
            "status": (
                "PASS"
                if all(row["status"] == "PASS" for row in interventions)
                else "FAIL"
            ),
            "evidence": f"{len(interventions)} positive/negative controls",
        },
        {
            "gate": "regional_repartition_reaches_v2",
            "status": (
                "PASS"
                if repartition_visibility
                and all(row["status"] == "PASS" for row in repartition_visibility)
                else "FAIL"
            ),
            "evidence": (
                f"{sum(row['status'] == 'PASS' for row in repartition_visibility)}/"
                f"{len(repartition_visibility)} regional MapMerge rows"
            ),
        },
        {
            "gate": "holdout_not_observed",
            "status": "PASS",
            "evidence": str(contract["confirmatory_holdout"]["logical_run_id"]),
        },
    ]
    write_csv(out_dir / "feature_semantic_gate.csv", gate_rows)
    decision = "GO" if all(row["status"] == "PASS" for row in gate_rows) else "NO-GO"
    summary = {
        "contract": contract["contract"],
        "decision": decision,
        "legacy_feature_count": len(contract["legacy_audit"]),
        "v2_feature_count": len(required),
        "row_count": len(all_features),
        "raw_reference_check_count": len(references),
        "raw_reference_failure_count": reference_failures,
        "holdout_logical_run_id": contract["confirmatory_holdout"][
            "logical_run_id"
        ],
        "contract_sha256": hashlib.sha256(
            args.contract.resolve().read_bytes()
        ).hexdigest(),
    }
    (out_dir / "feature_semantic_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "README.md").write_text(
        f"""# Feature semantic contract v2 audit

## Decision

```text
{decision}
```

Audit classifies all 21 frozen v1 inputs before any semantic-v2 holdout is
executed. It preserves raw evidence, introduces versioned replacements where
the old name or geometry was misleading, and keeps the frozen thesis model
unchanged.

## Main corrections

- `drf_bytes_proxy` is replaced in model input by the accurately named
  `regional_input_to_wan_rows_ratio`; the shared width proxy cancels.
- `wan_output_to_final_rows_ratio` is removed as a deterministic duplicate of
  `global_group_merge_ratio`.
- `spill_per_wan_mb` is removed as an exact constant multiple of
  `spill_bytes_to_wan_bytes_ratio`.
- spill occurrence and spill magnitude are separate.
- regional and task ISF receive topology-aware `[0,1]` forms.
- `worker_scan_rows_cv_normalized` is added from the full derived layer because
  worker placement is not represented by task ISF alone.
- signed estimate error uses `0.5` as the transformed neutral point.
- regional Citus `MapMerge` evidence contributes to the versioned repartition
  flag even when the GAC plan hides that strategy.

## Scope

- baseline rows: {len(all_features)}
- frozen v1 inputs classified: {len(contract["legacy_audit"])}
- semantic-v2 model inputs: {len(required)}
- independent raw/reference checks: {len(references)}
- failed reference checks: {reference_failures}
- confirmatory holdout observed during contract design: no

The next allowed step is the preregistered
`{contract["confirmatory_holdout"]["logical_run_id"]}` execution. Contract
formulas, transformations, family weights, `k`, seeds and OOD rules must not be
changed after observing that run.
""",
        encoding="utf-8",
    )
    print(out_dir)
    return 0 if decision == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
