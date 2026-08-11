#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE = ROOT / "generated/pressure-raw-runs/_program/pressure-raw-v1"
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-exploratory"
EXPECTED_OS_NODE_COUNT_BY_BATCH = {
    "batch-100-gac": 7,
    "batch-110-remote": 3,
    "batch-120-skew": 7,
    "batch-130-repartition": 4,
    "batch-140-regional": 4,
}

IDENTITY_FIELDS = {
    "batch_id",
    "condition_id",
    "database_sweep_id",
    "execution_slot_id",
    "instance_id",
    "pair_id",
    "query_run_id",
    "query_sweep_id",
    "repeat_id",
}
DESIGN_FIELDS = {
    "batch_id",
    "cache_policy",
    "component_match_id",
    "configured_bandwidth_mbit",
    "configured_delay_ms",
    "configured_jitter_ms",
    "configured_latency_ms",
    "configured_loss_percent",
    "coordinator_pressure_kind",
    "coordinator_shape_id",
    "dataset_profile_id",
    "dataset_role",
    "edge_stress_scope",
    "execution_class",
    "execution_scope",
    "execution_strategy",
    "fetch_size",
    "intervention_axis",
    "intervention_role",
    "join_shape_id",
    "mitigation_action",
    "network_subblock",
    "physical_strategy_id",
    "pressure_axis",
    "pressure_level",
    "pressure_pair_key",
    "remote_shape_id",
    "repetition_index",
    "run_order",
    "runtime_config_id",
    "scenario_level",
    "target_metric",
    "target_scope",
    "topology_id",
    "transfer_volume_level",
    "variant",
    "warmup_run_flag",
    "work_mem",
}
OUTCOME_FIELDS = {
    "database_result_rows_stored",
    "elapsed_seconds",
    "execution_status",
    "hard_timeout_seconds",
    "result_multiset_sha256",
    "result_ordered_sha256",
    "result_output_byte_count",
    "result_row_count",
    "result_signature_elapsed_seconds",
    "result_signature_status",
    "timed_out",
    "timeout_phase",
}
LABEL_DEFINING_FIELDS = {
    "citus_repartition_observed_v2",
    "coordinator_spill_present",
    "regional_spill_present",
    "spill_present",
    "worker_scan_rows_skew_applicable",
    "worker_task_active_scan_skew_applicable",
    "worker_task_scan_skew_applicable",
}
MEASUREMENT_PROCESS_FIELDS = {
    "os_clock_calibrated_node_count",
    "os_clock_uncertainty_seconds_max",
    "os_query_aligned_node_count",
    "os_query_alignment_coverage_count",
    "os_query_bracket_duration_seconds_max",
    "os_query_bracket_duration_seconds_mean",
    "os_query_padding_seconds_max",
    "os_raw_sample_count_sum",
    "os_sample_count_sum",
    "os_sampled_node_count",
    "query_finished_at_unix",
    "query_started_at_unix",
    "same_instance_previous_execution_gap_seconds",
}
SIGNAL_FAMILIES = {
    "gac_finalization": (
        "coordinator_",
        "analytics_rx_",
    ),
    "remote_path": (
        "foreign_scan_",
        "remote_",
        "regional_coordinator_tx_",
    ),
    "worker_data_skew": (
        "worker_",
        "worker_task_",
        "worker_scan_",
    ),
    "repartition_join": (
        "citus_",
        "remote_citus_",
    ),
    "regional_finalization": (
        "regional_temp_",
        "regional_spill_",
        "temp_blks_",
        "worker_task_temp_",
        "worker_task_spill_",
        "worker_task_has_aggregate",
        "worker_task_has_sort",
        "worker_task_has_hash",
    ),
    "os_runtime": ("os_",),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explore the consolidated pressure-raw-v1 evidence package."
    )
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.replace(
            {
                "": np.nan,
                "false": 0,
                "False": 0,
                "true": 1,
                "True": 1,
            }
        ),
        errors="coerce",
    )


def quantile(series: pd.Series, value: float) -> float:
    clean = numeric(series).dropna()
    return float(clean.quantile(value)) if not clean.empty else math.nan


def field_role(name: str) -> tuple[str, str]:
    if name in IDENTITY_FIELDS or name.endswith("_id"):
        return "identity", "exclude"
    if name in MEASUREMENT_PROCESS_FIELDS:
        return "measurement_process_artifact", "exclude"
    if name in LABEL_DEFINING_FIELDS:
        return "label_defining_evidence", "exclude_from_same-label-model"
    if name in OUTCOME_FIELDS or name.startswith("result_"):
        return "outcome_or_target", "exclude"
    if name in DESIGN_FIELDS or name.startswith("configured_"):
        return "experimental_design", "review-by-model-purpose"
    if (
        name.endswith(("_file", "_dir", "_path", "_hash", "_sha256", "_json"))
        or "fingerprint" in name
    ):
        return "artifact_or_lineage", "exclude-or-derive"
    if name.endswith("_status") or name.endswith("_source"):
        return "observed_status", "review"
    return "observed_measurement", "candidate-after-leakage-audit"


def build_execution_inventory(executions: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        executions.groupby(
            ["batch_id", "pressure_axis", "intervention_role", "variant"],
            dropna=False,
        )
        .agg(
            execution_count=("query_run_id", "size"),
            condition_count=("condition_id", "nunique"),
            pair_count=("pair_id", "nunique"),
            template_count=("template_id", "nunique"),
            dataset_count=("dataset_profile_id", "nunique"),
        )
        .reset_index()
    )
    return grouped.sort_values(["batch_id", "intervention_role", "variant"])


def build_result_signature_audit(executions: pd.DataFrame) -> pd.DataFrame:
    signatures = executions[
        executions["result_signature_status"].eq("completed")
        & executions["variant"].isin(["stressed", "mitigated"])
    ].copy()
    rows: list[dict[str, Any]] = []
    for pair_id, group in signatures.groupby("pair_id", sort=True):
        stressed = group[group["variant"].eq("stressed")]
        mitigated = group[group["variant"].eq("mitigated")]
        row: dict[str, Any] = {
            "pair_id": pair_id,
            "pressure_axis": group.iloc[0]["pressure_axis"],
            "intervention_role": group.iloc[0]["intervention_role"],
            "template_id": group.iloc[0]["template_id"],
            "stressed_signature_count": len(stressed),
            "mitigated_signature_count": len(mitigated),
        }
        if len(stressed) != 1 or len(mitigated) != 1:
            row.update(
                {
                    "result_equivalence_status": "missing_or_duplicate_signature",
                    "same_row_count": False,
                    "exact_multiset_hash": False,
                    "output_byte_difference": math.nan,
                    "output_byte_relative_difference": math.nan,
                }
            )
            rows.append(row)
            continue
        stressed_row = stressed.iloc[0]
        mitigated_row = mitigated.iloc[0]
        same_rows = stressed_row["result_row_count"] == mitigated_row["result_row_count"]
        exact_hash = (
            bool(stressed_row["result_multiset_sha256"])
            and stressed_row["result_multiset_sha256"] == mitigated_row["result_multiset_sha256"]
        )
        stressed_bytes = float(stressed_row["result_output_byte_count"] or 0)
        mitigated_bytes = float(mitigated_row["result_output_byte_count"] or 0)
        byte_difference = abs(stressed_bytes - mitigated_bytes)
        byte_denominator = max(stressed_bytes, mitigated_bytes)
        if exact_hash and same_rows:
            status = "exact_multiset"
        elif same_rows:
            status = "same_row_count_hash_diff_review"
        else:
            status = "row_count_mismatch"
        row.update(
            {
                "result_equivalence_status": status,
                "same_row_count": same_rows,
                "exact_multiset_hash": exact_hash,
                "stressed_result_row_count": stressed_row["result_row_count"],
                "mitigated_result_row_count": mitigated_row["result_row_count"],
                "output_byte_difference": byte_difference,
                "output_byte_relative_difference": (
                    byte_difference / byte_denominator if byte_denominator else 0.0
                ),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_pair_repeat_targets(
    executions: pd.DataFrame,
    signature_audit: pd.DataFrame,
) -> pd.DataFrame:
    base = executions[executions["variant"].isin(["stressed", "mitigated"])].copy()
    key = ["pair_id", "repetition_index"]
    if base.duplicated([*key, "variant"]).any():
        raise ValueError("Duplicate stressed/mitigated execution for pair repetition")
    stressed = base[base["variant"].eq("stressed")].copy()
    mitigated = base[base["variant"].eq("mitigated")].copy()
    keep = [
        *key,
        "query_run_id",
        "condition_id",
        "elapsed_seconds",
        "dataset_profile_id",
        "runtime_config_id",
        "template_id",
        "physical_strategy_id",
        "pressure_level",
    ]
    pairs = stressed[keep].merge(
        mitigated[keep],
        on=key,
        how="outer",
        suffixes=("_stressed", "_mitigated"),
        validate="one_to_one",
        indicator=True,
    )
    metadata = stressed[
        ["pair_id", "pressure_axis", "intervention_role", "target_metric"]
    ].drop_duplicates("pair_id")
    pairs = pairs.merge(metadata, on="pair_id", validate="many_to_one")
    stressed_elapsed = numeric(pairs["elapsed_seconds_stressed"])
    mitigated_elapsed = numeric(pairs["elapsed_seconds_mitigated"])
    pairs["elapsed_ratio_stressed_to_mitigated"] = stressed_elapsed / mitigated_elapsed
    pairs["target_log2_mitigation_gain"] = np.log2(pairs["elapsed_ratio_stressed_to_mitigated"])
    pairs["pair_complete"] = pairs["_merge"].eq("both")
    pairs = pairs.drop(columns="_merge")
    return pairs.merge(
        signature_audit[
            ["pair_id", "result_equivalence_status", "same_row_count", "exact_multiset_hash"]
        ],
        on="pair_id",
        how="left",
        validate="many_to_one",
    )


def build_pair_summary(pair_repeats: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pair_id, group in pair_repeats.groupby("pair_id", sort=True):
        gain = numeric(group["target_log2_mitigation_gain"]).dropna()
        ratio = numeric(group["elapsed_ratio_stressed_to_mitigated"]).dropna()
        stressed_elapsed = numeric(group["elapsed_seconds_stressed"]).dropna()
        mitigated_elapsed = numeric(group["elapsed_seconds_mitigated"]).dropna()
        stressed_median = (
            float(stressed_elapsed.median()) if not stressed_elapsed.empty else math.nan
        )
        mitigated_median = (
            float(mitigated_elapsed.median()) if not mitigated_elapsed.empty else math.nan
        )
        elapsed_ratio = (
            stressed_median / mitigated_median
            if math.isfinite(stressed_median)
            and math.isfinite(mitigated_median)
            and mitigated_median > 0
            else math.nan
        )
        target_log2_gain = (
            math.log2(elapsed_ratio)
            if math.isfinite(elapsed_ratio) and elapsed_ratio > 0
            else math.nan
        )
        first = group.iloc[0]
        rows.append(
            {
                "pair_id": pair_id,
                "pressure_axis": first["pressure_axis"],
                "intervention_role": first["intervention_role"],
                "target_metric": first["target_metric"],
                "template_id": first["template_id_stressed"],
                "dataset_profile_id": first["dataset_profile_id_stressed"],
                "repeat_count": len(group),
                "complete_repeat_count": int(group["pair_complete"].sum()),
                "stressed_elapsed_median": stressed_median,
                "mitigated_elapsed_median": mitigated_median,
                "elapsed_ratio_median": elapsed_ratio,
                "paired_repeat_ratio_median": (
                    float(ratio.median()) if not ratio.empty else math.nan
                ),
                "elapsed_ratio_min": float(ratio.min()) if not ratio.empty else math.nan,
                "elapsed_ratio_max": float(ratio.max()) if not ratio.empty else math.nan,
                "target_log2_gain_median": target_log2_gain,
                "target_log2_gain_std": float(gain.std(ddof=1)) if len(gain) > 1 else 0.0,
                "positive_repeat_share": float((gain > 0).mean()) if not gain.empty else math.nan,
                "result_equivalence_status": first["result_equivalence_status"],
                "same_row_count": first["same_row_count"],
                "exact_multiset_hash": first["exact_multiset_hash"],
            }
        )
    return pd.DataFrame(rows)


def build_gain_summary(pair_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (axis, role), group in pair_summary.groupby(
        ["pressure_axis", "intervention_role"], sort=True
    ):
        ratio = numeric(group["elapsed_ratio_median"]).dropna()
        gain = numeric(group["target_log2_gain_median"]).dropna()
        rows.append(
            {
                "pressure_axis": axis,
                "intervention_role": role,
                "pair_count": len(group),
                "median_elapsed_ratio": float(ratio.median()),
                "q10_elapsed_ratio": float(ratio.quantile(0.10)),
                "q90_elapsed_ratio": float(ratio.quantile(0.90)),
                "positive_gain_pair_share": float((gain > 0).mean()),
                "median_within_pair_log2_std": float(
                    numeric(group["target_log2_gain_std"]).median()
                ),
                "fully_consistent_direction_pair_share": float(
                    group["positive_repeat_share"].isin([0.0, 1.0]).mean()
                ),
                "exact_signature_pair_count": int(
                    group["result_equivalence_status"].eq("exact_multiset").sum()
                ),
                "signature_review_pair_count": int(
                    (~group["result_equivalence_status"].eq("exact_multiset")).sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def numeric_candidate_fields(field_completeness: pd.DataFrame) -> list[str]:
    eligible_roles = {
        "label_defining_evidence",
        "observed_measurement",
    }
    selected = field_completeness[
        field_completeness["field_role"].isin(eligible_roles)
        & field_completeness["numeric_parse_rate_among_nonempty"].ge(0.95)
        & field_completeness["unique_nonempty_count"].ge(2)
    ]
    return selected["field"].tolist()


def pair_feature_medians(
    executions: pd.DataFrame,
    fields: list[str],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for variant in ("stressed", "mitigated"):
        source = executions[executions["variant"].eq(variant)]
        converted = pd.DataFrame(
            {field: numeric(source[field]) for field in fields}, index=source.index
        )
        converted.insert(0, "intervention_role", source["intervention_role"])
        converted.insert(0, "pressure_axis", source["pressure_axis"])
        converted.insert(0, "pair_id", source["pair_id"])
        aggregated = converted.groupby(
            ["pair_id", "pressure_axis", "intervention_role"]
        )[fields].median()
        aggregated = aggregated.add_suffix(f"__{variant}").reset_index()
        frames.append(aggregated)
    return frames[0].merge(
        frames[1],
        on=["pair_id", "pressure_axis", "intervention_role"],
        how="outer",
        validate="one_to_one",
    )


def build_feature_target_associations(
    pair_features: pd.DataFrame,
    pair_summary: pd.DataFrame,
    field_completeness: pd.DataFrame,
    fields: list[str],
) -> pd.DataFrame:
    metadata = field_completeness.set_index("field")
    target = pair_summary[
        ["pair_id", "pressure_axis", "intervention_role", "target_log2_gain_median"]
    ]
    frame = pair_features.merge(
        target,
        on=["pair_id", "pressure_axis", "intervention_role"],
        validate="one_to_one",
    )
    rows: list[dict[str, Any]] = []
    for (axis, role), group in frame.groupby(
        ["pressure_axis", "intervention_role"], sort=True
    ):
        for field in fields:
            feature = f"{field}__stressed"
            values = group[[feature, "target_log2_gain_median"]].dropna()
            if len(values) < 12 or values[feature].nunique() < 3:
                continue
            rho = values[feature].corr(values["target_log2_gain_median"], method="spearman")
            if pd.isna(rho):
                continue
            rows.append(
                {
                    "pressure_axis": axis,
                    "intervention_role": role,
                    "field": field,
                    "field_role": metadata.at[field, "field_role"],
                    "default_model_policy": metadata.at[field, "default_model_policy"],
                    "pair_count": len(values),
                    "unique_value_count": int(values[feature].nunique()),
                    "spearman_rho": float(rho),
                    "absolute_spearman_rho": abs(float(rho)),
                }
            )
    result = pd.DataFrame(rows)
    return result.sort_values(
        ["pressure_axis", "intervention_role", "absolute_spearman_rho"],
        ascending=[True, True, False],
    )


def build_paired_feature_response(
    pair_features: pd.DataFrame,
    field_completeness: pd.DataFrame,
    fields: list[str],
) -> pd.DataFrame:
    metadata = field_completeness.set_index("field")
    rows: list[dict[str, Any]] = []
    for (axis, role), group in pair_features.groupby(
        ["pressure_axis", "intervention_role"], sort=True
    ):
        for field in fields:
            stressed_name = f"{field}__stressed"
            mitigated_name = f"{field}__mitigated"
            paired = group[[stressed_name, mitigated_name]].dropna()
            if paired.empty:
                continue
            stressed = numeric(paired[stressed_name])
            mitigated = numeric(paired[mitigated_name])
            delta = stressed - mitigated
            nonnegative = stressed.ge(0) & mitigated.ge(0)
            smoothed_log2 = np.log2((stressed[nonnegative] + 1.0) / (mitigated[nonnegative] + 1.0))
            rows.append(
                {
                    "pressure_axis": axis,
                    "intervention_role": role,
                    "field": field,
                    "field_role": metadata.at[field, "field_role"],
                    "default_model_policy": metadata.at[field, "default_model_policy"],
                    "paired_count": len(paired),
                    "stressed_median": float(stressed.median()),
                    "mitigated_median": float(mitigated.median()),
                    "median_delta": float(delta.median()),
                    "median_absolute_delta": float(delta.abs().median()),
                    "positive_delta_share": float(delta.gt(0).mean()),
                    "median_log2_smoothed_ratio": (
                        float(smoothed_log2.median()) if not smoothed_log2.empty else math.nan
                    ),
                }
            )
    result = pd.DataFrame(rows)
    result["absolute_median_log2_smoothed_ratio"] = result["median_log2_smoothed_ratio"].abs()
    return result.sort_values(
        ["pressure_axis", "absolute_median_log2_smoothed_ratio"],
        ascending=[True, False],
    )


def build_child_coverage(index_dir: Path, executions: pd.DataFrame) -> pd.DataFrame:
    query_batch = executions[["query_run_id", "batch_id"]].drop_duplicates()
    rows: list[dict[str, Any]] = []
    for table in (
        "region_fragments",
        "worker_task_fragments",
        "remote_edge_observations",
        "node_artifacts",
        "fdw_remote_plans",
    ):
        child = read_csv(index_dir / f"{table}.csv")
        child = child.merge(query_batch, on="query_run_id", how="left", validate="many_to_one")
        child_counts = child.groupby("query_run_id").size()
        for batch_id, query_group in query_batch.groupby("batch_id", sort=True):
            query_ids = set(query_group["query_run_id"])
            covered_ids = query_ids & set(child_counts.index)
            row_count = int(child["query_run_id"].isin(query_ids).sum())
            rows.append(
                {
                    "batch_id": batch_id,
                    "child_table": table,
                    "execution_count": len(query_ids),
                    "covered_execution_count": len(covered_ids),
                    "execution_coverage": len(covered_ids) / len(query_ids),
                    "child_row_count": row_count,
                    "mean_rows_per_covered_execution": (
                        row_count / len(covered_ids) if covered_ids else 0.0
                    ),
                    "orphan_row_count": int(child["batch_id"].eq("").sum()),
                    "exact_duplicate_row_count": int(
                        child.drop(columns="batch_id").duplicated().sum()
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_field_profile(executions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    coverage_rows: list[dict[str, Any]] = []
    numeric_rows: list[dict[str, Any]] = []
    for field in executions.columns:
        series = executions[field]
        nonempty = series.ne("")
        values = numeric(series)
        numeric_count = int(values.notna().sum())
        role, policy = field_role(field)
        row: dict[str, Any] = {
            "field": field,
            "field_role": role,
            "default_model_policy": policy,
            "nonempty_count": int(nonempty.sum()),
            "coverage": float(nonempty.mean()),
            "unique_nonempty_count": int(series[nonempty].nunique()),
            "numeric_count": numeric_count,
            "numeric_parse_rate_among_nonempty": (
                numeric_count / int(nonempty.sum()) if nonempty.any() else 0.0
            ),
        }
        for batch_id, group in executions.groupby("batch_id", sort=True):
            row[f"coverage__{batch_id}"] = float(group[field].ne("").mean())
        coverage_rows.append(row)
        if numeric_count:
            clean = values.dropna()
            numeric_rows.append(
                {
                    "field": field,
                    "field_role": role,
                    "default_model_policy": policy,
                    "count": numeric_count,
                    "zero_share": float(clean.eq(0).mean()),
                    "min": float(clean.min()),
                    "q01": float(clean.quantile(0.01)),
                    "median": float(clean.median()),
                    "q99": float(clean.quantile(0.99)),
                    "max": float(clean.max()),
                }
            )
    return pd.DataFrame(coverage_rows), pd.DataFrame(numeric_rows)


def build_signal_family_coverage(executions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for family, prefixes in SIGNAL_FAMILIES.items():
        fields = [field for field in executions if field.startswith(prefixes)]
        for batch_id, group in executions.groupby("batch_id", sort=True):
            available = group[fields].ne("") if fields else pd.DataFrame(index=group.index)
            rows.append(
                {
                    "signal_family": family,
                    "batch_id": batch_id,
                    "field_count": len(fields),
                    "execution_count": len(group),
                    "execution_count_with_any_field": int(available.any(axis=1).sum()),
                    "median_available_field_count": (
                        float(available.sum(axis=1).median()) if fields else 0.0
                    ),
                    "mean_field_coverage": (float(available.mean().mean()) if fields else 0.0),
                }
            )
    return pd.DataFrame(rows)


def build_os_node_coverage(executions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for batch_id, group in executions.groupby("batch_id", sort=True):
        sampled = numeric(group["os_sampled_node_count"])
        aligned = numeric(group["os_query_aligned_node_count"])
        expected = EXPECTED_OS_NODE_COUNT_BY_BATCH.get(str(batch_id), math.nan)
        observed_min = int(sampled.min()) if sampled.notna().any() else 0
        rows.append(
            {
                "batch_id": batch_id,
                "execution_count": len(group),
                "expected_os_node_count": expected,
                "observed_os_node_count_min": observed_min,
                "observed_os_node_count_median": float(sampled.median()),
                "observed_os_node_count_max": int(sampled.max()),
                "query_aligned_node_count_min": int(aligned.min()),
                "coverage_status": (
                    "complete"
                    if pd.isna(expected) or observed_min >= expected
                    else "incomplete"
                ),
            }
        )
    return pd.DataFrame(rows)


def os_coverage_report_note(os_gap_batches: list[str]) -> str:
    if os_gap_batches:
        return (
            "  Nepotpuni batch-evi moraju biti ponovo prikupljeni ili eksplicitno "
            "iskljuceni prije modeliranja."
        )
    return (
        "  Svi batch-evi imaju očekivanu node-level OS pokrivenost za svoju "
        "izvršnu traku."
    )


def build_hardware_coverage(index_dir: Path) -> pd.DataFrame:
    hardware = read_csv(index_dir / "program_hardware_nodes.csv")
    return (
        hardware.groupby("batch_id", sort=True)
        .agg(
            snapshot_count=("snapshot_id", "nunique"),
            node_count=("node_name", "nunique"),
            hardware_row_count=("node_name", "size"),
        )
        .reset_index()
    )


def write_gain_figure(pair_summary: pd.DataFrame, path: Path) -> None:
    axes = list(pair_summary["pressure_axis"].drop_duplicates())
    positions: list[float] = []
    values: list[np.ndarray] = []
    labels: list[str] = []
    colors: list[str] = []
    position = 1.0
    role_colors = {
        "positive_case": "#1f6f5f",
        "calibration": "#576574",
        "negative_control": "#9a6b21",
    }
    for axis in axes:
        block = pair_summary[pair_summary["pressure_axis"].eq(axis)]
        for role in ("positive_case", "calibration", "negative_control"):
            subset = numeric(
                block.loc[block["intervention_role"].eq(role), "target_log2_gain_median"]
            ).dropna()
            if subset.empty:
                continue
            positions.append(position)
            values.append(subset.to_numpy())
            labels.append(f"{axis}\n{role}")
            colors.append(role_colors[role])
            position += 1.0
        position += 0.5
    fig, ax = plt.subplots(figsize=(13, 6.5))
    boxes = ax.boxplot(values, positions=positions, widths=0.65, patch_artist=True)
    for patch, color in zip(boxes["boxes"], colors, strict=True):
        patch.set_facecolor(color)
        patch.set_alpha(0.78)
    ax.axhline(0.0, color="#333333", linewidth=1.0)
    ax.set_xticks(positions, labels, rotation=35, ha="right")
    ax.set_ylabel("Medijanski log2(T stressed / T mitigated)")
    ax.set_title("Izmjerena korist mitigacije po osi i ulozi scenarija")
    ax.grid(axis="y", color="#d7dadd", linewidth=0.7)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def markdown_table(frame: pd.DataFrame, columns: list[str], digits: int = 3) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in frame[columns].itertuples(index=False, name=None):
        formatted = []
        for value in row:
            if isinstance(value, float):
                formatted.append(f"{value:.{digits}f}")
            else:
                formatted.append(str(value))
        lines.append("| " + " | ".join(formatted) + " |")
    return "\n".join(lines)


def write_report(
    *,
    out_dir: Path,
    executions: pd.DataFrame,
    signature_audit: pd.DataFrame,
    pair_summary: pd.DataFrame,
    gain_summary: pd.DataFrame,
    child_coverage: pd.DataFrame,
    os_node_coverage: pd.DataFrame,
    hardware_coverage: pd.DataFrame,
    feature_target_associations: pd.DataFrame,
) -> None:
    primary = gain_summary[gain_summary["intervention_role"].isin(["positive_case", "calibration"])]
    negative = gain_summary[gain_summary["intervention_role"].eq("negative_control")]
    medium_alignment = executions["os_query_alignment_worst_status"].eq("medium").sum()
    exact = signature_audit["result_equivalence_status"].eq("exact_multiset").sum()
    reviewed = (
        signature_audit["result_equivalence_status"].eq("same_row_count_hash_diff_review").sum()
    )
    row_count_mismatch = signature_audit["result_equivalence_status"].eq("row_count_mismatch").sum()
    regional_positive = executions[
        executions["pressure_axis"].eq("regional_finalization")
        & executions["intervention_role"].eq("positive_case")
    ]
    regional_stressed = regional_positive[regional_positive["variant"].eq("stressed")]
    regional_mitigated = regional_positive[regional_positive["variant"].eq("mitigated")]
    regional_written_stressed = numeric(
        regional_stressed["regional_temp_written_blocks_sum"]
    ).median()
    regional_written_mitigated = numeric(
        regional_mitigated["regional_temp_written_blocks_sum"]
    ).median()
    regional_spill_stressed = numeric(regional_stressed["regional_spill_present"]).mean()
    regional_spill_mitigated = numeric(regional_mitigated["regional_spill_present"]).mean()
    skew_positive = executions[
        executions["pressure_axis"].eq("worker_data_skew")
        & executions["intervention_role"].eq("positive_case")
    ]
    skew_stressed = skew_positive[skew_positive["variant"].eq("stressed")]
    skew_mitigated = skew_positive[skew_positive["variant"].eq("mitigated")]
    worker_cv_stressed = numeric(skew_stressed["worker_scan_rows_cv"]).median()
    worker_cv_mitigated = numeric(skew_mitigated["worker_scan_rows_cv"]).median()
    region_coverage = child_coverage[child_coverage["child_table"].eq("region_fragments")][
        "covered_execution_count"
    ].sum()
    no_region = len(executions) - int(region_coverage)
    os_gap_batches = os_node_coverage.loc[
        os_node_coverage["coverage_status"].eq("incomplete"), "batch_id"
    ].tolist()
    os_coverage_note = os_coverage_report_note(os_gap_batches)
    primary_table = markdown_table(
        primary,
        [
            "pressure_axis",
            "intervention_role",
            "pair_count",
            "median_elapsed_ratio",
            "q10_elapsed_ratio",
            "q90_elapsed_ratio",
            "positive_gain_pair_share",
        ],
    )
    negative_table = markdown_table(
        negative,
        [
            "pressure_axis",
            "pair_count",
            "median_elapsed_ratio",
            "positive_gain_pair_share",
        ],
    )
    top_associations = (
        feature_target_associations[
            feature_target_associations["field_role"].eq("observed_measurement")
            & feature_target_associations["pair_count"].ge(24)
            & feature_target_associations["intervention_role"].isin(
                ["positive_case", "calibration"]
            )
        ]
        .groupby(["pressure_axis", "intervention_role"], group_keys=False)
        .head(3)
    )
    association_table = markdown_table(
        top_associations,
        [
            "pressure_axis",
            "intervention_role",
            "field",
            "pair_count",
            "spearman_rho",
        ],
    )
    report = f"""# Pressure raw v1 - eksploratorna analiza

## Status skupa

- Primarna execution jedinica: `{len(executions)}` redova.
- Eksperimentalni uslovi: `{executions["condition_id"].nunique()}`.
- Kontrafaktualni parovi: `{pair_summary["pair_id"].nunique()}` sa po tri ponavljanja.
- Sve execution opservacije su zavrsene bez timeouta.
- OS poravnanje je `high` za `{len(executions) - medium_alignment}` redova i `medium`
  za `{medium_alignment}` izvršenja sa većom clock-uncertainty/padding rezervom.
- `{no_region}` ETL negativnih kontrola nema regionalni/worker plan po dizajnu.
- Hardware snapshot postoji za `{len(hardware_coverage)}` primarnih batch-eva,
  svaki sa po jednim snapshotom i sedam cvorova.
- Nepotpuna OS node pokrivenost postoji za: `{', '.join(os_gap_batches) or 'nema'}`.
{os_coverage_note}

## Prvi nalaz o targetima

{primary_table}

Negativne kontrole:

{negative_table}

GAC, remote i repartition pozitivni scenariji pokazuju jasan izmjereni benefit.
Regional-finalization target je slabiji, a worker/data-skew placement promjena u
ukupnom vremenu ima medijanu blisku `1x`. Zato se ne smije unaprijed pretpostaviti
da je `execution_time_seconds` kvalitetan intenzitetski target za svih pet osi.
Skew i regionalni intenzitet treba dodatno vezati za direktne, ali label-odvojene
fizicke ishode kao sto su worker raspodjela, task tail i spill/bytes odgovor.

Direktni fizicki dokazi potvrđuju da su obje intervencije ipak aktivirane:

- Regional-finalization pozitivni scenariji imaju medijanu zapisanih temp blokova
  `{regional_written_stressed:.1f}` u stressed stanju i
  `{regional_written_mitigated:.1f}` nakon mitigacije. Spill je opažen u
  `{regional_spill_stressed:.1%}` stressed i `{regional_spill_mitigated:.1%}`
  mitigated izvršenja.
- Worker/data-skew pozitivni scenariji imaju medijanski worker row CV
  `{worker_cv_stressed:.3f}` u stressed i `{worker_cv_mitigated:.3f}` u mitigated
  stanju.

Prema tome, slab elapsed-time gain nije dokaz da collection scenario nije radio.
On pokazuje da fizicki intenzitet pritiska i korist mitigacije za cijeli globalni
upit moraju ostati dva odvojena targeta.

## Deskriptivne feature-target veze

{association_table}

Ovo su in-sample Spearman veze, ne validirani modelski feature-i. Vremenske
koordinate plana mogu legitimno opisivati stressed izvršenje, ali OS broj uzoraka,
trajanje sampler prozora i slicne measurement-process kolone su eksplicitno
iskljucene. SQL porodica i dataset i dalje mogu biti zajednicki uzrok i feature-a i
targeta, pa se izbor vrsi tek uz grouped holdout.

## Rezultatski potpisi

- Tacno isti multiset potpis: `{exact}/{len(signature_audit)}` parova.
- Isti broj redova uz drugaciji hash: `{reviewed}/{len(signature_audit)}` parova.
- Razlicit broj redova: `{row_count_mismatch}`.

Hash razlike su koncentrisane u floating-point agregacijskim sablonima. Raw redovi
rezultata namjerno nisu pohranjeni, pa se ova grupa zadrzava kao eksplicitni review
status. Ne smije se automatski proglasiti ni semanticki jednakom ni pogresnom.

## Granice prije modeliranja

1. `experimental_design`, identiteti i target/outcome kolone ne ulaze automatski u
   modelski input.
2. Dokaz koji direktno definise confirmed labelu ne smije se koristiti za
   trivijalnu rekonstrukciju iste labele.
3. Skew i regionalni targeti zahtijevaju target audit prije regresije koristi.
4. Child redovi ostaju vezani za `query_run_id`; ne tretiraju se kao nezavisna
   execution opažanja.
5. Ova faza ne bira model niti finalni feature set.

## Izlazi

- `execution_inventory.csv`
- `pair_repeat_targets.csv`
- `counterfactual_pair_summary.csv`
- `mitigation_gain_summary.csv`
- `result_signature_audit.csv`
- `child_evidence_coverage.csv`
- `field_completeness.csv`
- `numeric_field_profile.csv`
- `model_field_policy.csv`
- `signal_family_coverage.csv`
- `os_node_coverage.csv`
- `hardware_snapshot_coverage.csv`
- `feature_target_associations.csv`
- `paired_feature_response_summary.csv`
- `os_alignment_outliers.csv`
- `mitigation_gain_by_axis.png`
- `summary.json`
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")

    child_summary = {
        row.child_table: int(row.covered_execution_count)
        for row in child_coverage.groupby("child_table")
        .agg(covered_execution_count=("covered_execution_count", "sum"))
        .reset_index()
        .itertuples()
    }
    summary = {
        "status": "completed_exploratory_no_model_fit",
        "execution_count": len(executions),
        "condition_count": int(executions["condition_id"].nunique()),
        "pair_count": int(pair_summary["pair_id"].nunique()),
        "pair_repeat_count": int(pair_summary["complete_repeat_count"].sum()),
        "exact_result_signature_pair_count": int(exact),
        "same_row_count_hash_review_pair_count": int(reviewed),
        "os_high_alignment_count": int(
            executions["os_query_alignment_worst_status"].eq("high").sum()
        ),
        "os_medium_alignment_count": int(medium_alignment),
        "os_node_coverage_gap_batches": os_gap_batches,
        "child_covered_execution_count": child_summary,
        "next_gate": (
            "resolve_skew_worker_os_coverage_then_define_label_target_contract"
            if os_gap_batches
            else "define_label_and_target_contract_before_model_fit"
        ),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    package_dir = args.package_dir.resolve()
    out_dir = args.out_dir.resolve()
    index_dir = package_dir / "_index"
    manifest = json.loads((package_dir / "consolidation_manifest.json").read_text())
    if manifest.get("gate") != "GO":
        raise ValueError(f"Consolidation gate is not GO: {manifest.get('gate')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[EDA 1/7] loading consolidated execution evidence", flush=True)
    executions = read_csv(index_dir / "execution_features.csv")
    if len(executions) != int(manifest["resolved_primary_slot_count"]):
        raise ValueError("execution_features row count does not match consolidation manifest")

    print("[EDA 2/7] auditing execution inventory and result signatures", flush=True)
    inventory = build_execution_inventory(executions)
    signature_audit = build_result_signature_audit(executions)

    print("[EDA 3/7] constructing paired exploratory targets", flush=True)
    pair_repeats = build_pair_repeat_targets(executions, signature_audit)
    pair_summary = build_pair_summary(pair_repeats)
    gain_summary = build_gain_summary(pair_summary)

    print("[EDA 4/7] checking child-evidence coverage", flush=True)
    child_coverage = build_child_coverage(index_dir, executions)

    print("[EDA 5/7] profiling field completeness and leakage roles", flush=True)
    field_completeness, numeric_profile = build_field_profile(executions)
    signal_coverage = build_signal_family_coverage(executions)
    os_node_coverage = build_os_node_coverage(executions)
    hardware_coverage = build_hardware_coverage(index_dir)
    model_policy = field_completeness[
        [
            "field",
            "field_role",
            "default_model_policy",
            "coverage",
            "numeric_parse_rate_among_nonempty",
        ]
    ].copy()
    candidate_fields = numeric_candidate_fields(field_completeness)
    pair_features = pair_feature_medians(executions, candidate_fields)
    feature_target_associations = build_feature_target_associations(
        pair_features,
        pair_summary,
        field_completeness,
        candidate_fields,
    )
    paired_feature_response = build_paired_feature_response(
        pair_features,
        field_completeness,
        candidate_fields,
    )

    print("[EDA 6/7] writing tables and figure", flush=True)
    inventory.to_csv(out_dir / "execution_inventory.csv", index=False)
    pair_repeats.to_csv(out_dir / "pair_repeat_targets.csv", index=False)
    pair_summary.to_csv(out_dir / "counterfactual_pair_summary.csv", index=False)
    gain_summary.to_csv(out_dir / "mitigation_gain_summary.csv", index=False)
    signature_audit.to_csv(out_dir / "result_signature_audit.csv", index=False)
    child_coverage.to_csv(out_dir / "child_evidence_coverage.csv", index=False)
    field_completeness.to_csv(out_dir / "field_completeness.csv", index=False)
    numeric_profile.to_csv(out_dir / "numeric_field_profile.csv", index=False)
    model_policy.to_csv(out_dir / "model_field_policy.csv", index=False)
    signal_coverage.to_csv(out_dir / "signal_family_coverage.csv", index=False)
    os_node_coverage.to_csv(out_dir / "os_node_coverage.csv", index=False)
    hardware_coverage.to_csv(out_dir / "hardware_snapshot_coverage.csv", index=False)
    feature_target_associations.to_csv(out_dir / "feature_target_associations.csv", index=False)
    paired_feature_response.to_csv(out_dir / "paired_feature_response_summary.csv", index=False)
    executions[~executions["os_query_alignment_worst_status"].eq("high")].to_csv(
        out_dir / "os_alignment_outliers.csv", index=False
    )
    write_gain_figure(pair_summary, out_dir / "mitigation_gain_by_axis.png")

    print("[EDA 7/7] writing interpretation summary", flush=True)
    write_report(
        out_dir=out_dir,
        executions=executions,
        signature_audit=signature_audit,
        pair_summary=pair_summary,
        gain_summary=gain_summary,
        child_coverage=child_coverage,
        os_node_coverage=os_node_coverage,
        hardware_coverage=hardware_coverage,
        feature_target_associations=feature_target_associations,
    )
    print(out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
