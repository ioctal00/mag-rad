#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import pandas as pd
import yaml
from scipy.optimize import minimize

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE = ROOT / "generated/pressure-raw-runs/_program/pressure-raw-v1"
DEFAULT_AUDIT = ROOT / "analysis/reports/pressure-raw-v1-mitigation-action-audit"
DEFAULT_CONTRACT = ROOT / "configs/models/pressure_profile_scorers_v1.yml"
DEFAULT_OUT = ROOT / "analysis/reports/pressure-raw-v1-pressure-profile-scorers"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train five independent intervention-ordered pressure scorers."
    )
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--action-audit-dir", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path, low_memory=False)


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


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    top = numeric(numerator)
    bottom = numeric(denominator)
    return top / bottom.where(bottom.abs().gt(0), 1.0)


def harmonic_mean(values: pd.Series) -> float:
    clean = numeric(values).dropna().astype(float)
    clean = clean[clean.gt(0)]
    if clean.empty:
        return math.nan
    return float(len(clean) / np.reciprocal(clean).sum())


def aggregate_edge_evidence(edges: pd.DataFrame) -> pd.DataFrame:
    if edges.empty:
        return pd.DataFrame(columns=["query_run_id"])
    numeric_fields = [
        "remote_bytes_proxy",
        "estimated_fetch_cycles",
        "rtt_context_median_ms",
        "query_window_source_tx_bps",
        "foreign_scan_time_ms_sum",
        "regional_plan_time_ms_sum",
        "foreign_scan_minus_regional_time_ms_proxy",
        "packet_loss_context_percent_max",
        "query_window_qdisc_overlimits",
        "tcp_retrans_delta_node_global",
    ]
    frame = edges[["query_run_id", *numeric_fields]].copy()
    for field in numeric_fields:
        frame[field] = numeric(frame[field])
    rows: list[dict[str, Any]] = []
    for query_run_id, group in frame.groupby("query_run_id", sort=False):
        foreign_time = group["foreign_scan_time_ms_sum"].sum(min_count=1)
        boundary = group["foreign_scan_minus_regional_time_ms_proxy"].clip(lower=0).sum(
            min_count=1
        )
        rows.append(
            {
                "query_run_id": query_run_id,
                "edge_remote_bytes_sum": group["remote_bytes_proxy"].sum(min_count=1),
                "edge_estimated_fetch_cycles_sum": group["estimated_fetch_cycles"].sum(
                    min_count=1
                ),
                "edge_rtt_context_median_ms_max": group["rtt_context_median_ms"].max(),
                "edge_source_tx_bps_hmean": harmonic_mean(
                    group["query_window_source_tx_bps"]
                ),
                "edge_boundary_wait_ms_sum": boundary,
                "edge_boundary_wait_share": (
                    boundary / foreign_time
                    if pd.notna(boundary) and pd.notna(foreign_time) and foreign_time > 0
                    else math.nan
                ),
                "edge_packet_loss_percent_max": group[
                    "packet_loss_context_percent_max"
                ].max(),
                "edge_qdisc_overlimits_sum": group[
                    "query_window_qdisc_overlimits"
                ].sum(min_count=1),
                "edge_tcp_retrans_sum": group[
                    "tcp_retrans_delta_node_global"
                ].sum(min_count=1),
            }
        )
    return pd.DataFrame(rows)


def derive_pressure_features(executions: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    frame = executions.copy()
    edge_features = aggregate_edge_evidence(edges)
    frame = frame.merge(edge_features, on="query_run_id", how="left", validate="one_to_one")

    final_rows = numeric(frame["coordinator_final_rows"])
    remote_rows = numeric(frame["remote_region_actual_rows_sum"])
    main_time = numeric(frame["coordinator_main_plan_total_time_ms"])
    task_count = numeric(frame["worker_task_plan_count"])

    frame["gac_fanin_to_final_rows_ratio"] = safe_ratio(
        frame["coordinator_fanin_rows"], final_rows
    )
    frame["gac_blocking_input_to_final_rows_ratio"] = safe_ratio(
        frame["coordinator_blocking_input_rows_sum"], final_rows
    )
    frame["gac_temp_written_per_final_row"] = safe_ratio(
        frame["coordinator_temp_written_blocks"], final_rows
    )
    frame["gac_sort_time_share"] = safe_ratio(
        frame["coordinator_sort_time_ms_max"], main_time
    ).clip(lower=0, upper=1)
    frame["gac_aggregate_time_share"] = safe_ratio(
        frame["coordinator_aggregate_time_ms_max"], main_time
    ).clip(lower=0, upper=1)
    frame["gac_hash_batch_excess"] = (
        numeric(frame["coordinator_hash_batches_max"]) - 1
    ).clip(lower=0)
    frame["analytics_rx_bytes_per_final_row"] = safe_ratio(
        frame["analytics_rx_bytes_sum"], final_rows
    )
    frame["foreign_scan_time_share"] = safe_ratio(
        frame["coordinator_foreign_scan_time_ms_sum"], main_time
    ).clip(lower=0, upper=1)

    frame["repartition_remote_tuple_bytes_per_final_row"] = safe_ratio(
        frame["remote_region_tuple_bytes_sum"], final_rows
    )
    frame["repartition_worker_rx_bytes_per_final_row"] = safe_ratio(
        frame["worker_rx_bytes_sum"], final_rows
    )

    frame["regional_temp_written_per_remote_row"] = safe_ratio(
        frame["regional_temp_written_blocks_sum"], remote_rows
    )
    frame["regional_temp_read_per_remote_row"] = safe_ratio(
        frame["regional_temp_read_blocks_sum"], remote_rows
    )
    frame["regional_spill_region_share"] = safe_ratio(
        frame["regional_spill_region_count"], frame["remote_region_count"]
    ).clip(lower=0, upper=1)
    frame["regional_worker_to_remote_rows_ratio"] = safe_ratio(
        frame["worker_task_actual_rows_sum"], remote_rows
    )
    frame["regional_actual_time_per_remote_row"] = safe_ratio(
        frame["remote_region_actual_time_sum"], remote_rows
    )
    frame["regional_worker_blocking_nodes_per_task"] = safe_ratio(
        frame["worker_task_blocking_node_count"], task_count
    )
    frame["regional_worker_sort_nodes_per_task"] = safe_ratio(
        frame["worker_task_sort_node_count"], task_count
    )
    return frame


def feature_names(domain_contract: dict[str, Any]) -> list[str]:
    return [str(item["name"]) for item in domain_contract["features"]]


def validate_contract_inputs(frame: pd.DataFrame, contract: dict[str, Any]) -> None:
    names: list[str] = []
    for domain in contract["domains"].values():
        names.extend(feature_names(domain))
    missing = sorted(set(names) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing pressure feature columns: {missing}")
    forbidden = set(contract["forbidden_model_inputs"])
    overlap = sorted(set(names) & forbidden)
    if overlap:
        raise ValueError(f"Forbidden model inputs in pressure contract: {overlap}")
    provenance_names: list[str] = []
    for category in contract["feature_provenance"]["categories"].values():
        provenance_names.extend(str(name) for name in category["features"])
    duplicates = sorted(
        name for name in set(provenance_names) if provenance_names.count(name) > 1
    )
    if duplicates:
        raise ValueError(f"Features have multiple provenance categories: {duplicates}")
    missing_provenance = sorted(set(names) - set(provenance_names))
    unexpected_provenance = sorted(set(provenance_names) - set(names))
    if missing_provenance or unexpected_provenance:
        raise ValueError(
            "Feature provenance must cover the model contract exactly: "
            f"missing={missing_provenance}, unexpected={unexpected_provenance}"
        )


def feature_provenance_frame(contract: dict[str, Any]) -> pd.DataFrame:
    category_by_feature: dict[str, tuple[str, str]] = {}
    for category_name, category in contract["feature_provenance"]["categories"].items():
        for name in category["features"]:
            category_by_feature[str(name)] = (
                str(category_name),
                str(category["description"]),
            )
    rows: list[dict[str, Any]] = []
    for domain, domain_contract in contract["domains"].items():
        for feature in domain_contract["features"]:
            name = str(feature["name"])
            category, description = category_by_feature[name]
            rows.append(
                {
                    "domain": domain,
                    "feature": name,
                    "provenance_category": category,
                    "provenance_description": description,
                    "transform": feature["transform"],
                    "post_execution_evidence": True,
                    "direct_design_identifier": False,
                    "causal_root_cause_claim": False,
                }
            )
    return pd.DataFrame(rows)


def methodological_audit(
    executions: pd.DataFrame,
    pairs: pd.DataFrame,
    execution_scores: pd.DataFrame,
    predictions: pd.DataFrame,
    contract: dict[str, Any],
) -> dict[str, Any]:
    feature_set = {
        name
        for domain_contract in contract["domains"].values()
        for name in feature_names(domain_contract)
    }
    forbidden_overlap = sorted(feature_set & set(contract["forbidden_model_inputs"]))
    prediction_columns = set(predictions.columns)
    calibration_columns = {
        "local_median",
        "local_mad",
        "local_scale",
        "local_robust_z",
    }
    prediction_duplicates = (
        int(
            predictions.duplicated(
                ["domain", "holdout", "held_out_group", "pair_id"]
            ).sum()
        )
        if not predictions.empty
        else 0
    )
    pair_condition_counts = (
        executions[executions["pair_id"].isin(pairs["pair_id"])]
        .groupby("condition_id", dropna=False)["pair_id"]
        .nunique()
    )
    invalid_score_status = execution_scores[
        (
            execution_scores["score_status"].eq("insufficient_evidence")
            & execution_scores["coordinate_score"].notna()
        )
        | (
            execution_scores["score_status"].eq("measured")
            & execution_scores["coordinate_score"].isna()
        )
    ]
    excluded_sensitive = sorted(
        str(item["name"])
        for item in contract["feature_provenance"].get(
            "descriptive_only_evidence", []
        )
        if item.get("provenance") == "intervention_sensitive_estimate"
    )
    return {
        "calibration_leakage": {
            "status": (
                "PASS"
                if not prediction_columns.intersection(calibration_columns)
                and not contract["local_calibration"]["used_in_model_training"]
                and not contract["local_calibration"]["used_in_grouped_validation"]
                and contract["local_calibration"]["time_causal_for_live_use"]
                else "FAIL"
            ),
            "grouped_validation_uses_local_calibration": False,
            "local_calibration_evaluation_role": contract["local_calibration"][
                "evaluation_role"
            ],
            "local_calibration_reference_fit_scope": contract["local_calibration"][
                "reference_fit_scope"
            ],
            "live_time_causal_calibration": contract["local_calibration"][
                "time_causal_for_live_use"
            ],
        },
        "grouped_split_integrity": {
            "status": (
                "PASS"
                if prediction_duplicates == 0
                and int(pair_condition_counts.gt(1).sum()) == 0
                else "FAIL"
            ),
            "duplicate_holdout_pair_predictions": prediction_duplicates,
            "conditions_assigned_to_multiple_pairs": int(
                pair_condition_counts.gt(1).sum()
            ),
            "pair_members_and_repetitions_aggregated_before_split": True,
        },
        "model_input_scope": {
            "status": "PASS" if not forbidden_overlap else "FAIL",
            "forbidden_input_overlap": forbidden_overlap,
            "excluded_intervention_sensitive_estimates": excluded_sensitive,
            "interpretation": (
                "Scoreri koriste post-execution fizicke posljedice intervencije. "
                "To je dozvoljeno za dijagnosticku koordinatu, ali ne dokazuje "
                "skriveni uzrok niti pre-intervention predikciju. Procjene koje "
                "direktno koriste aktivni konfiguracijski knob ostaju deskriptivne."
            ),
        },
        "missingness_semantics": {
            "status": "PASS" if invalid_score_status.empty else "FAIL",
            "invalid_score_status_rows": int(len(invalid_score_status)),
            "insufficient_evidence_is_not_low_pressure": True,
        },
    }


def transform_series(series: pd.Series, kind: str) -> pd.Series:
    values = numeric(series)
    if kind == "identity":
        return values
    if kind == "log1p":
        return np.log1p(values.clip(lower=0))
    if kind == "signed_log1p":
        return np.sign(values) * np.log1p(values.abs())
    raise ValueError(f"Unknown transform: {kind}")


def transformed_matrix(frame: pd.DataFrame, specs: list[dict[str, Any]]) -> np.ndarray:
    return np.column_stack(
        [transform_series(frame[str(spec["name"])], str(spec["transform"])) for spec in specs]
    ).astype(float)


def fit_preprocessor(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    medians = np.nanmedian(values, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    filled = np.where(np.isfinite(values), values, medians)
    q25 = np.quantile(filled, 0.25, axis=0)
    q75 = np.quantile(filled, 0.75, axis=0)
    scales = q75 - q25
    scales = np.where(np.isfinite(scales) & (scales > 1e-9), scales, 1.0)
    return medians, scales


def apply_preprocessor(values: np.ndarray, medians: np.ndarray, scales: np.ndarray) -> np.ndarray:
    filled = np.where(np.isfinite(values), values, medians)
    return (filled - medians) / scales


def pair_member_frame(
    executions: pd.DataFrame,
    audit: pd.DataFrame,
    names: list[str],
) -> pd.DataFrame:
    source = executions[
        executions["pair_id"].isin(audit["pair_id"])
        & executions["variant"].isin(["stressed", "mitigated"])
    ].copy()
    numeric_frame = pd.DataFrame(
        {name: numeric(source[name]) for name in names}, index=source.index
    )
    numeric_frame.insert(0, "variant", source["variant"])
    numeric_frame.insert(0, "pair_id", source["pair_id"])
    members = numeric_frame.groupby(["pair_id", "variant"], as_index=False).median(
        numeric_only=True
    )
    stressed = members[members["variant"].eq("stressed")].drop(columns="variant")
    mitigated = members[members["variant"].eq("mitigated")].drop(columns="variant")
    pairs = stressed.merge(
        mitigated,
        on="pair_id",
        suffixes=("__stressed", "__mitigated"),
        validate="one_to_one",
    )
    metadata = audit.drop_duplicates("pair_id")
    return metadata.merge(pairs, on="pair_id", how="inner", validate="one_to_one")


def member_matrix(pairs: pd.DataFrame, specs: list[dict[str, Any]], variant: str) -> np.ndarray:
    source = pd.DataFrame(
        {
            str(spec["name"]): pairs[f"{spec['name']}__{variant}"]
            for spec in specs
        }
    )
    return transformed_matrix(source, specs)


def pair_coverage(pairs: pd.DataFrame, specs: list[dict[str, Any]], variant: str) -> pd.Series:
    columns = [f"{spec['name']}__{variant}" for spec in specs]
    return pairs[columns].apply(pd.to_numeric, errors="coerce").notna().mean(axis=1)


def required_pair_evidence(
    pairs: pd.DataFrame,
    required_features: list[str],
    variant: str,
) -> pd.Series:
    if not required_features:
        return pd.Series(True, index=pairs.index)
    columns = [f"{name}__{variant}" for name in required_features]
    return pairs[columns].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)


def fit_ranker(
    positive: pd.DataFrame,
    controls: pd.DataFrame,
    domain_contract: dict[str, Any],
    estimator_contract: dict[str, Any],
) -> dict[str, Any]:
    specs = list(domain_contract["features"])
    positive_stressed = member_matrix(positive, specs, "stressed")
    positive_mitigated = member_matrix(positive, specs, "mitigated")
    all_members = [positive_stressed, positive_mitigated]
    if not controls.empty:
        all_members.extend(
            [
                member_matrix(controls, specs, "stressed"),
                member_matrix(controls, specs, "mitigated"),
            ]
        )
    medians, scales = fit_preprocessor(np.vstack(all_members))
    stressed = apply_preprocessor(positive_stressed, medians, scales)
    mitigated = apply_preprocessor(positive_mitigated, medians, scales)
    differences = stressed - mitigated
    if controls.empty:
        control_differences = np.empty((0, differences.shape[1]))
    else:
        control_differences = apply_preprocessor(
            member_matrix(controls, specs, "stressed"), medians, scales
        ) - apply_preprocessor(member_matrix(controls, specs, "mitigated"), medians, scales)

    margin = float(estimator_contract["margin"])
    l2_penalty = float(estimator_contract["l2_penalty"])
    control_penalty = float(estimator_contract["control_invariance_penalty"])

    def objective(weights: np.ndarray) -> tuple[float, np.ndarray]:
        gaps = margin - differences @ weights
        positive_loss = np.logaddexp(0.0, gaps).mean()
        sigmoid = np.exp(-np.logaddexp(0.0, -gaps))
        gradient = -(differences.T @ sigmoid) / len(differences)
        control_loss = 0.0
        if len(control_differences):
            control_projection = control_differences @ weights
            control_loss = control_penalty * float(np.mean(control_projection**2))
            gradient += (
                2.0
                * control_penalty
                * (control_differences.T @ control_projection)
                / len(control_differences)
            )
        regularization = 0.5 * l2_penalty * float(weights @ weights)
        gradient += l2_penalty * weights
        return positive_loss + control_loss + regularization, gradient

    result = minimize(
        objective,
        np.zeros(differences.shape[1]),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": int(estimator_contract["maximum_iterations"])},
    )
    if not result.success:
        raise RuntimeError(f"Pairwise optimizer failed: {result.message}")
    weights = np.asarray(result.x, dtype=float)
    norm = float(np.linalg.norm(weights))
    if norm <= 1e-12:
        raise RuntimeError("Pairwise optimizer produced a zero projection")
    weights /= norm
    training_members = np.vstack([stressed, mitigated])
    offset = float(np.median(training_members @ weights))
    baseline = np.array(
        [float(spec["baseline_direction"]) for spec in specs], dtype=float
    )
    baseline /= np.linalg.norm(baseline)
    return {
        "features": specs,
        "medians": medians.tolist(),
        "scales": scales.tolist(),
        "weights": weights.tolist(),
        "baseline_weights": baseline.tolist(),
        "offset": offset,
        "optimizer_objective": float(result.fun),
        "optimizer_iterations": int(result.nit),
        "positive_pair_count": int(len(positive)),
        "control_pair_count": int(len(controls)),
    }


def score_values(
    frame: pd.DataFrame,
    state: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    specs = list(state["features"])
    values = transformed_matrix(frame, specs)
    coverage = np.isfinite(values).mean(axis=1)
    transformed = apply_preprocessor(
        values,
        np.asarray(state["medians"], dtype=float),
        np.asarray(state["scales"], dtype=float),
    )
    learned = transformed @ np.asarray(state["weights"], dtype=float) - float(state["offset"])
    baseline = transformed @ np.asarray(state["baseline_weights"], dtype=float)
    return learned, baseline, coverage


def filter_pairs_for_domain(
    pairs: pd.DataFrame,
    domain: str,
    domain_contract: dict[str, Any],
    pair_contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    roles = set(domain_contract["positive_roles"])
    strict = pairs["strict_gain_eligible"].astype(str).str.lower().eq("true")
    axis = pairs["pressure_axis"].eq(domain)
    positive = pairs[strict & axis & pairs["intervention_role"].isin(roles)].copy()
    controls = pairs[
        strict
        & axis
        & pairs["intervention_role"].eq(pair_contract["negative_control_role"])
    ].copy()
    threshold = float(
        domain_contract.get(
            "minimum_feature_coverage",
            pair_contract["minimum_member_feature_coverage"],
        )
    )
    required = list(domain_contract.get("required_features", []))
    for frame in (positive, controls):
        frame["stressed_feature_coverage"] = pair_coverage(
            frame, list(domain_contract["features"]), "stressed"
        )
        frame["mitigated_feature_coverage"] = pair_coverage(
            frame, list(domain_contract["features"]), "mitigated"
        )
        frame["stressed_required_evidence"] = required_pair_evidence(
            frame, required, "stressed"
        )
        frame["mitigated_required_evidence"] = required_pair_evidence(
            frame, required, "mitigated"
        )
    eligible_positive = positive[
        positive["stressed_feature_coverage"].ge(threshold)
        & positive["mitigated_feature_coverage"].ge(threshold)
        & positive["stressed_required_evidence"]
        & positive["mitigated_required_evidence"]
    ].copy()
    eligible_controls = controls[
        controls["stressed_feature_coverage"].ge(threshold)
        & controls["mitigated_feature_coverage"].ge(threshold)
        & controls["stressed_required_evidence"]
        & controls["mitigated_required_evidence"]
    ].copy()
    return positive, eligible_positive, eligible_controls


def pair_scores(pairs: pd.DataFrame, state: dict[str, Any]) -> pd.DataFrame:
    specs = list(state["features"])
    stressed_frame = pd.DataFrame(
        {str(spec["name"]): pairs[f"{spec['name']}__stressed"] for spec in specs}
    )
    mitigated_frame = pd.DataFrame(
        {str(spec["name"]): pairs[f"{spec['name']}__mitigated"] for spec in specs}
    )
    stressed, stressed_baseline, stressed_coverage = score_values(stressed_frame, state)
    mitigated, mitigated_baseline, mitigated_coverage = score_values(mitigated_frame, state)
    result = pairs[["pair_id"]].copy()
    result["stressed_score"] = stressed
    result["mitigated_score"] = mitigated
    result["score_delta"] = stressed - mitigated
    result["baseline_score_delta"] = stressed_baseline - mitigated_baseline
    result["stressed_feature_coverage"] = stressed_coverage
    result["mitigated_feature_coverage"] = mitigated_coverage
    return result


def directional_summary(scored: pd.DataFrame) -> dict[str, float]:
    delta = numeric(scored["score_delta"]).dropna()
    baseline = numeric(scored["baseline_score_delta"]).dropna()
    return {
        "pair_count": int(len(delta)),
        "direction_accuracy": float(delta.gt(0).mean()) if len(delta) else math.nan,
        "zero_tie_share": float(delta.eq(0).mean()) if len(delta) else math.nan,
        "median_score_delta": float(delta.median()) if len(delta) else math.nan,
        "baseline_direction_accuracy": (
            float(baseline.gt(0).mean()) if len(baseline) else math.nan
        ),
        "baseline_median_score_delta": (
            float(baseline.median()) if len(baseline) else math.nan
        ),
    }


def cross_validate_domain(
    positive: pd.DataFrame,
    controls: pd.DataFrame,
    domain: str,
    domain_contract: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[pd.DataFrame] = []
    validation = contract["validation"]
    for holdout in validation["holdouts"]:
        group_field = str(holdout["group_field"])
        for group_value in sorted(positive[group_field].dropna().astype(str).unique()):
            test = positive[positive[group_field].astype(str).eq(group_value)]
            train = positive[~positive[group_field].astype(str).eq(group_value)]
            train_controls = controls[~controls[group_field].astype(str).eq(group_value)]
            if len(train) < int(validation["minimum_train_pairs_per_fold"]):
                continue
            if len(test) < int(validation["minimum_test_pairs_per_fold"]):
                continue
            state = fit_ranker(
                train,
                train_controls,
                domain_contract,
                contract["estimator"],
            )
            scored = pair_scores(test, state)
            scored.insert(0, "held_out_group", group_value)
            scored.insert(0, "holdout", holdout["name"])
            scored.insert(0, "domain", domain)
            prediction_rows.append(scored)
            fold_rows.append(
                {
                    "domain": domain,
                    "holdout": holdout["name"],
                    "held_out_group": group_value,
                    "train_pair_count": len(train),
                    "test_pair_count": len(test),
                    **directional_summary(scored),
                }
            )
    return pd.DataFrame(fold_rows), (
        pd.concat(prediction_rows, ignore_index=True)
        if prediction_rows
        else pd.DataFrame()
    )


def bootstrap_median_interval(
    values: pd.Series,
    repetitions: int,
    confidence_level: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    clean = numeric(values).dropna().to_numpy(dtype=float)
    if not len(clean):
        return math.nan, math.nan
    samples = rng.choice(clean, size=(repetitions, len(clean)), replace=True)
    medians = np.median(samples, axis=1)
    alpha = (1.0 - confidence_level) / 2.0
    return float(np.quantile(medians, alpha)), float(np.quantile(medians, 1.0 - alpha))


def build_execution_scores(
    executions: pd.DataFrame,
    states: dict[str, dict[str, Any]],
    contract: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    identity = [
        "query_run_id",
        "database_sweep_id",
        "pair_id",
        "variant",
        "condition_id",
        "repetition_index",
        "pressure_axis",
        "intervention_role",
        "logical_question_id",
        "template_id",
        "dataset_profile_id",
        "topology_id",
        "execution_scope",
        "sql_normalized_hash",
        "plan_fingerprint",
        "created_at_utc",
        "elapsed_seconds",
    ]
    long_rows: list[pd.DataFrame] = []
    wide = executions[identity].copy()
    for domain, state in states.items():
        domain_contract = contract["domains"][domain]
        minimum_coverage = float(
            domain_contract.get(
                "minimum_feature_coverage",
                contract["pair_contract"]["minimum_member_feature_coverage"],
            )
        )
        required = list(domain_contract.get("required_features", []))
        learned, baseline, coverage = score_values(executions, state)
        required_available = (
            executions[required]
            .apply(pd.to_numeric, errors="coerce")
            .notna()
            .all(axis=1)
            if required
            else pd.Series(True, index=executions.index)
        )
        available = (coverage >= minimum_coverage) & required_available.to_numpy()
        coordinate = np.where(available, baseline, np.nan)
        learned_ablation = np.where(available, learned, np.nan)
        domain_frame = executions[identity].copy()
        domain_frame.insert(len(identity), "domain", domain)
        domain_frame["diagnostic_domain"] = domain
        domain_frame["output_mode"] = domain_contract["output_mode"]
        domain_frame["coordinate_score"] = coordinate
        domain_frame["learned_ablation_score"] = learned_ablation
        domain_frame["feature_coverage"] = coverage
        domain_frame["score_status"] = np.where(available, "measured", "insufficient_evidence")
        long_rows.append(domain_frame)
        if domain_contract["output_mode"] != "component_profile":
            wide[f"coordinate_{domain}"] = coordinate
        wide[f"learned_ablation_{domain}"] = learned_ablation
        wide[f"coverage_{domain}"] = coverage
    return pd.concat(long_rows, ignore_index=True), wide


def build_coordinate_components(
    executions: pd.DataFrame,
    execution_scores: pd.DataFrame,
    states: dict[str, dict[str, Any]],
    provenance: pd.DataFrame,
) -> pd.DataFrame:
    status_by_domain = execution_scores.set_index(["query_run_id", "domain"])[
        "score_status"
    ]
    provenance_by_feature = provenance.set_index(["domain", "feature"])[
        "provenance_category"
    ]
    rows: list[pd.DataFrame] = []
    for domain, state in states.items():
        specs = list(state["features"])
        raw = np.column_stack(
            [numeric(executions[str(spec["name"])]).to_numpy() for spec in specs]
        ).astype(float)
        transformed = transformed_matrix(executions, specs)
        medians = np.asarray(state["medians"], dtype=float)
        scales = np.asarray(state["scales"], dtype=float)
        standardized = apply_preprocessor(transformed, medians, scales)
        coordinate_weights = np.asarray(state["baseline_weights"], dtype=float)
        learned_weights = np.asarray(state["weights"], dtype=float)
        for index, spec in enumerate(specs):
            feature = str(spec["name"])
            frame = pd.DataFrame(
                {
                    "query_run_id": executions["query_run_id"],
                    "domain": domain,
                    "feature": feature,
                    "raw_value": raw[:, index],
                    "transformed_value": transformed[:, index],
                    "standardized_value": standardized[:, index],
                    "value_status": np.where(
                        np.isfinite(transformed[:, index]),
                        "observed",
                        "median_imputed_optional_component",
                    ),
                    "coordinate_weight": coordinate_weights[index],
                    "coordinate_component": standardized[:, index]
                    * coordinate_weights[index],
                    "learned_ablation_weight": learned_weights[index],
                    "learned_ablation_component": standardized[:, index]
                    * learned_weights[index],
                    "transform": spec["transform"],
                    "provenance_category": provenance_by_feature.loc[
                        (domain, feature)
                    ],
                }
            )
            frame["domain_score_status"] = [
                status_by_domain.loc[(query_run_id, domain)]
                for query_run_id in frame["query_run_id"]
            ]
            rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def build_gac_component_profiles(
    execution_scores: pd.DataFrame,
    coordinate_components: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    gac_contract = contract["domains"]["gac_finalization"]
    profiles = gac_contract["component_profiles"]
    gac_scores = execution_scores[
        execution_scores["domain"].eq("gac_finalization")
    ].copy()
    identity = [
        column
        for column in gac_scores.columns
        if column
        not in {
            "domain",
            "diagnostic_domain",
            "output_mode",
            "coordinate_score",
            "learned_ablation_score",
            "feature_coverage",
            "score_status",
        }
    ]
    rows: list[pd.DataFrame] = []
    for profile_name, features in profiles.items():
        source = coordinate_components[
            coordinate_components["domain"].eq("gac_finalization")
            & coordinate_components["feature"].isin(features)
        ]
        grouped = source.groupby("query_run_id", as_index=False).agg(
            coordinate_score=("coordinate_component", "sum"),
            feature_coverage=(
                "value_status",
                lambda values: float(values.eq("observed").mean()),
            ),
        )
        frame = gac_scores[identity + ["score_status"]].merge(
            grouped, on="query_run_id", how="left", validate="one_to_one"
        )
        frame["domain"] = str(profile_name)
        frame["diagnostic_domain"] = "gac_finalization"
        frame["output_mode"] = "component_profile"
        frame["learned_ablation_score"] = math.nan
        frame.loc[frame["score_status"].ne("measured"), "coordinate_score"] = math.nan
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def local_calibration(
    scores: pd.DataFrame,
    calibration_contract: dict[str, Any],
) -> pd.DataFrame:
    result = scores.copy()
    score_field = str(calibration_contract["coordinate_field"])
    minimum = int(calibration_contract["minimum_reference_executions"])
    scale_floor = float(calibration_contract["scale_floor"])
    exact_fields = list(calibration_contract["exact_group_fields"])
    fallback_enabled = bool(calibration_contract.get("fallback_enabled", False))
    fallback_fields = list(calibration_contract.get("fallback_group_fields", exact_fields))
    reference_variants = set(calibration_contract["reference_variants"])

    def key_for(row: dict[str, Any], fields: list[str]) -> tuple[Any, ...]:
        values: list[Any] = [row["domain"]]
        for field in fields:
            value = row.get(field)
            values.append("__MISSING__" if pd.isna(value) else value)
        return tuple(values)

    result["_calibration_timestamp"] = pd.to_datetime(
        result["created_at_utc"], errors="coerce", utc=True
    )
    result = result.sort_values(
        ["_calibration_timestamp", "query_run_id", "domain"],
        kind="stable",
        na_position="last",
    )
    exact_history: dict[tuple[Any, ...], list[float]] = {}
    fallback_history: dict[tuple[Any, ...], list[float]] = {}
    previous_scores: dict[tuple[Any, ...], float] = {}
    rows: list[dict[str, Any]] = []
    for row in result.to_dict(orient="records"):
        score = row[score_field]
        exact_key = key_for(row, exact_fields)
        fallback_key = key_for(row, fallback_fields)
        previous_score = previous_scores.get(exact_key, math.nan)
        base = {
            **row,
            "calibration_contract_version": calibration_contract[
                "feature_contract_version"
            ],
            "previous_coordinate_score": previous_score,
            "coordinate_score_change_from_previous": (
                float(score) - previous_score
                if pd.notna(score) and pd.notna(previous_score)
                else math.nan
            ),
        }
        if pd.isna(score) or not math.isfinite(float(score)):
            rows.append(
                {
                    **base,
                    "local_context_status": "coordinate_unavailable",
                    "reference_scope": "unavailable",
                    "reference_count": 0,
                    "local_median": math.nan,
                    "local_mad": math.nan,
                    "local_scale": math.nan,
                    "local_robust_z": math.nan,
                }
            )
            continue
        exact_values = exact_history.get(exact_key, [])
        fallback_values = fallback_history.get(fallback_key, []) if fallback_enabled else []
        reference_values = exact_values
        scope = "exact_query_context"
        if len(exact_values) < minimum and fallback_enabled:
            reference_values = fallback_values
            scope = "logical_question_context"
        if pd.isna(row["_calibration_timestamp"]):
            reference_values = []
            scope = "temporal_order_unavailable"
        if len(reference_values) < minimum:
            rows.append(
                {
                    **base,
                    "local_context_status": "insufficient_history",
                    "reference_scope": scope,
                    "reference_count": len(reference_values),
                    "local_median": math.nan,
                    "local_mad": math.nan,
                    "local_scale": math.nan,
                    "local_robust_z": math.nan,
                }
            )
        else:
            values = pd.Series(reference_values, dtype=float)
            median = float(values.median())
            mad = float((values - median).abs().median())
            scale = max(1.4826 * mad, scale_floor)
            rows.append(
                {
                    **base,
                    "local_context_status": "available",
                    "reference_scope": scope,
                    "reference_count": len(reference_values),
                    "local_median": median,
                    "local_mad": mad,
                    "local_scale": scale,
                    "local_scale_floor_applied": 1.4826 * mad < scale_floor,
                    "local_robust_z": (float(score) - median) / scale,
                }
            )
        previous_scores[exact_key] = float(score)
        if row["variant"] in reference_variants and pd.notna(
            row["_calibration_timestamp"]
        ):
            exact_history.setdefault(exact_key, []).append(float(score))
            if fallback_enabled:
                fallback_history.setdefault(fallback_key, []).append(float(score))
    calibrated = pd.DataFrame(rows).drop(columns="_calibration_timestamp")
    return calibrated.sort_values(
        ["domain", "sql_normalized_hash", "created_at_utc"], kind="stable"
    )


def build_pair_responses(
    execution_scores: pd.DataFrame,
    audit: pd.DataFrame,
    score_field: str,
    score_kind: str,
) -> pd.DataFrame:
    eligible = execution_scores[
        execution_scores["score_status"].eq("measured")
        & execution_scores["variant"].isin(["stressed", "mitigated"])
    ]
    medians = (
        eligible.groupby(["pair_id", "domain", "variant"], as_index=False)[score_field]
        .median()
        .pivot(index=["pair_id", "domain"], columns="variant", values=score_field)
        .reset_index()
    )
    medians.columns.name = None
    medians["score_delta"] = medians["stressed"] - medians["mitigated"]
    medians["score_kind"] = score_kind
    output_metadata = eligible[
        ["domain", "diagnostic_domain", "output_mode"]
    ].drop_duplicates()
    medians = medians.merge(
        output_metadata, on="domain", how="left", validate="many_to_one"
    )
    metadata = audit[
        [
            "pair_id",
            "pressure_axis",
            "intervention_role",
            "mitigation_action",
            "stressed_template_id",
            "dataset_profile_id",
        ]
    ].drop_duplicates("pair_id")
    return metadata.merge(medians, on="pair_id", how="inner", validate="one_to_many")


def build_response_matrix(
    pair_responses: pd.DataFrame,
    audit: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    rng = np.random.default_rng(int(contract["estimator"]["random_seed"]))
    repetitions = int(contract["bootstrap"]["repetitions"])
    confidence = float(contract["bootstrap"]["confidence_level"])
    rows: list[dict[str, Any]] = []
    universe = (
        audit.groupby(["pressure_axis", "intervention_role"], as_index=False)["pair_id"]
        .nunique()
        .rename(columns={"pair_id": "planned_pair_count"})
    )
    score_kind = str(pair_responses["score_kind"].iloc[0])
    outputs = pair_responses[
        ["domain", "diagnostic_domain", "output_mode"]
    ].drop_duplicates()
    for universe_row in universe.itertuples(index=False):
        axis = str(universe_row.pressure_axis)
        role = str(universe_row.intervention_role)
        planned = int(universe_row.planned_pair_count)
        for output in outputs.itertuples(index=False):
            domain = str(output.domain)
            diagnostic_domain = str(output.diagnostic_domain)
            output_mode = str(output.output_mode)
            group = pair_responses[
                pair_responses["pressure_axis"].eq(axis)
                & pair_responses["intervention_role"].eq(role)
                & pair_responses["domain"].eq(domain)
            ]
            delta = numeric(group["score_delta"]).dropna()
            status = (
                "unavailable"
                if not len(delta)
                else "available"
                if len(delta) == planned
                else "partial"
            )
            low, high = bootstrap_median_interval(
                group["score_delta"], repetitions, confidence, rng
            )
            rows.append(
                {
                    "score_kind": score_kind,
                    "intervention_axis": axis,
                    "intervention_role": role,
                    "scorer_domain": domain,
                    "diagnostic_domain": diagnostic_domain,
                    "output_mode": output_mode,
                    "planned_pair_count": planned,
                    "applicable_pair_count": len(delta),
                    "evidence_availability_share": len(delta) / planned,
                    "evidence_status": status,
                    "median_score_delta": (
                        float(delta.median()) if len(delta) else math.nan
                    ),
                    "iqr_low": float(delta.quantile(0.25)) if len(delta) else math.nan,
                    "iqr_high": float(delta.quantile(0.75)) if len(delta) else math.nan,
                    "ci_low": low,
                    "ci_high": high,
                    "positive_delta_share": (
                        float(delta.gt(0).mean()) if len(delta) else math.nan
                    ),
                    "expected_direction_defined": (
                        axis == diagnostic_domain
                        and output_mode != "component_profile"
                        and role in {"positive_case", "calibration"}
                    ),
                    "expected_direction_share": (
                        float(delta.gt(0).mean())
                        if len(delta)
                        and axis == diagnostic_domain
                        and output_mode != "component_profile"
                        and role in {"positive_case", "calibration"}
                        else math.nan
                    ),
                }
            )
    result = pd.DataFrame(rows)
    diagonal = result[
        result["intervention_axis"].eq(result["scorer_domain"])
        & result["output_mode"].ne("component_profile")
    ][
        ["intervention_axis", "intervention_role", "median_score_delta"]
    ].rename(columns={"median_score_delta": "diagonal_median_score_delta"})
    result = result.merge(
        diagonal,
        on=["intervention_axis", "intervention_role"],
        how="left",
        validate="many_to_one",
    )
    result["absolute_delta_relative_to_diagonal"] = (
        result["median_score_delta"].abs()
        / result["diagonal_median_score_delta"].abs().replace(0, np.nan)
    )
    return result


def write_response_figure(matrix: pd.DataFrame, path: Path) -> None:
    domains = list(matrix["scorer_domain"].drop_duplicates())
    fig, axes = plt.subplots(len(domains), 1, figsize=(10, 2.8 * len(domains)), squeeze=False)
    for axis, domain in zip(axes[:, 0], domains, strict=True):
        source = matrix[
            matrix["scorer_domain"].eq(domain)
            & matrix["intervention_role"].isin(["positive_case", "calibration"])
        ].sort_values("intervention_axis")
        positions = np.arange(len(source))
        medians = source["median_score_delta"].to_numpy(dtype=float)
        errors = np.vstack(
            [
                medians - source["ci_low"].to_numpy(dtype=float),
                source["ci_high"].to_numpy(dtype=float) - medians,
            ]
        )
        axis.errorbar(positions, medians, yerr=errors, fmt="o", capsize=3)
        axis.axhline(0, color="#555555", linewidth=0.8)
        axis.set_xticks(positions, source["intervention_axis"], rotation=20, ha="right")
        axis.set_ylabel("Delta score")
        axis.set_title(domain.replace("_", " "))
        axis.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    view = frame[columns].copy()
    for column in view.columns:
        if pd.api.types.is_float_dtype(view[column]):
            view[column] = view[column].map(
                lambda value: "" if pd.isna(value) else f"{value:.3f}"
            )
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines.extend(
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in view.itertuples(index=False, name=None)
    )
    return "\n".join(lines)


def write_report(
    out_dir: Path,
    domain_summary: pd.DataFrame,
    validation_summary: pd.DataFrame,
    response_matrix: pd.DataFrame,
    calibration_summary: pd.DataFrame,
    audit_checks: dict[str, Any],
    technical_gate: str,
    learned_gate: str,
    reasons: list[str],
) -> None:
    diagonal = response_matrix[
        response_matrix["intervention_axis"].eq(response_matrix["scorer_domain"])
        & response_matrix["intervention_role"].isin(["positive_case", "calibration"])
    ]
    cross_talk = response_matrix[
        response_matrix["intervention_axis"].ne(response_matrix["scorer_domain"])
        & response_matrix["intervention_role"].isin(["positive_case", "calibration"])
    ].nlargest(5, "absolute_delta_relative_to_diagonal")
    gac_profiles = response_matrix[
        response_matrix["diagnostic_domain"].eq("gac_finalization")
        & response_matrix["intervention_role"].isin(["positive_case", "calibration"])
    ]
    domain_table = markdown_table(
        domain_summary,
        [
            "domain",
            "planned_positive_pairs",
            "eligible_positive_pairs",
            "eligible_control_pairs",
            "feature_count",
            "coordinate_apparent_direction_accuracy",
            "learned_apparent_direction_accuracy",
            "control_median_absolute_delta",
        ],
    )
    validation_table = markdown_table(
        validation_summary,
        [
            "domain",
            "holdout",
            "pair_count",
            "direction_accuracy",
            "baseline_direction_accuracy",
            "minimum_fold_direction_accuracy",
            "fold_count",
        ],
    )
    diagonal_table = markdown_table(
        diagonal,
        [
            "intervention_axis",
            "scorer_domain",
            "planned_pair_count",
            "applicable_pair_count",
            "evidence_status",
            "median_score_delta",
            "iqr_low",
            "iqr_high",
            "ci_low",
            "ci_high",
            "expected_direction_share",
        ],
    )
    calibration_table = markdown_table(
        calibration_summary,
        [
            "domain",
            "scored_execution_count",
            "locally_calibrated_count",
            "insufficient_history_count",
            "exact_reference_count",
            "fallback_reference_count",
            "scale_floor_applied_count",
        ],
    )
    cross_talk_table = markdown_table(
        cross_talk,
        [
            "intervention_axis",
            "scorer_domain",
            "intervention_role",
            "median_score_delta",
            "absolute_delta_relative_to_diagonal",
        ],
    )
    gac_profile_table = markdown_table(
        gac_profiles,
        [
            "intervention_axis",
            "scorer_domain",
            "applicable_pair_count",
            "evidence_status",
            "median_score_delta",
            "iqr_low",
            "iqr_high",
        ],
    )
    audit_table = markdown_table(
        pd.DataFrame(
            [
                {"provjera": name, "status": values["status"]}
                for name, values in audit_checks.items()
            ]
        ),
        ["provjera", "status"],
    )
    report = f"""# Transparentne dijagnosticke koordinate

## Ugovor

- Centralni izlaz je pet nezavisno prikazanih dijagnostickih domena.
- Primarna koordinata je transparentan zbir transformisanih, robustno skaliranih
  fizickih komponenti sa unaprijed definisanim smjerom.
- Naucene projekcije su samo ablation i trenirane su uredjenjem
  `stressed > mitigated`.
- Trajanje, gain, identitet SQL templatea, dataset i konfiguracijski knobovi nisu ulazi.
- Negativne kontrole ulaze samo kao kazna za nestabilnost scorera.
- Koordinata nema univerzalni prag niti zajednicku fizicku jedinicu s drugim domenima.
- Lokalni `z*` koristi samo raniju mitigated historiju istog verzionisanog konteksta.
- Grupisana validacija koristi samo score prije lokalne kalibracije.
- Bez najmanje tri ranije reference raw koordinata ostaje dostupna, a lokalni
  kontekst dobija status `insufficient_history`.
- Ulazi su post-execution fizicki dokazi. Opažena posljedica intervencije nije
  dokaz njenog skrivenog uzroka niti pre-intervention predikcija.

## Korpus po domenu

{domain_table}

## Grupisana validacija ML ablationa

{validation_table}

## Dijagonalni odziv transparentnih koordinata

{diagonal_table}

## Najveci cross-talk transparentnih koordinata

{cross_talk_table}

## GAC profil komponenti

{gac_profile_table}

GAC izlaz nije jedan univerzalni skalar. `gac_fanin`, `gac_reduction`,
`gac_sort_spill` i `gac_aggregate_finalization` prikazuju se odvojeno.

## Lokalna kalibracija

{calibration_table}

## Metodoloski audit

{audit_table}

Detalji provjera, ukljucujuci scope lokalne kalibracije, integritet foldova,
zabranjene ulaze i `NA` semantiku, nalaze se u `methodological_audit.json`.
Provenance svake ulazne komponente nalazi se u `feature_provenance.csv`.

## Odluka

- Tehnicki gate transparentnih izlaza: `{technical_gate}`.
- Gate naucenih scorera: `{learned_gate}`.
- Ogranicenja ML ablationa: `{", ".join(reasons) or "nisu zabiljezena"}`.

Ovaj izlaz ne rangira pet domena po end-to-end steti. Vrijednosti iz razlicitih
domena nisu procenat uzroka, udio vremena niti ocekivano ubrzanje. Profil sluzi
za pracenje smjera i promjene svake fizicke ose zasebno. Numericka matrica
odziva prikazuje cross-talk bez oznaka `malo` ili `mnogo`. Magnitude razlicitih
kolona response matrice ne smiju se direktno porediti.

## Izlazi

- `execution_pressure_scores.csv`
- `execution_pressure_profile.csv`
- `execution_ml_ablation_scores.csv`
- `execution_coordinate_components.csv`
- `pair_pressure_response.csv`
- `pressure_response_matrix.csv`
- `ml_ablation_pair_response.csv`
- `ml_ablation_response_matrix.csv`
- `domain_summary.csv`
- `scorer_validation_folds.csv`
- `scorer_validation_predictions.csv`
- `scorer_validation_summary.csv`
- `scorer_coefficients.csv`
- `feature_coverage.csv`
- `feature_provenance.csv`
- `methodological_audit.json`
- `pressure_scorers.joblib`
- `coordinate_response_by_domain.png`
- `model_manifest.json`
- `checksums.sha256`
"""
    (out_dir / "README.md").write_text(report, encoding="utf-8")


def main() -> int:
    args = parse_args()
    package_dir = args.package_dir.resolve()
    audit_dir = args.action_audit_dir.resolve()
    out_dir = args.out_dir.resolve()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    audit_summary = json.loads((audit_dir / "summary.json").read_text(encoding="utf-8"))
    if audit_summary.get("gate") != "GO" or audit_summary.get("review_pair_count") != 0:
        raise ValueError("Action audit must be GO with zero unresolved review pairs")
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale_name in ("pressure_response_by_scorer.png",):
        stale_path = out_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()

    print("[PRESSURE PROFILE 1/7] loading execution and edge evidence", flush=True)
    executions = derive_pressure_features(
        read_csv(package_dir / "_index/execution_features.csv"),
        read_csv(package_dir / "_index/remote_edge_observations.csv"),
    )
    audit = read_csv(audit_dir / "mitigation_pair_audit.csv")
    validate_contract_inputs(executions, contract)
    provenance = feature_provenance_frame(contract)
    all_names = sorted(
        {
            name
            for domain_contract in contract["domains"].values()
            for name in feature_names(domain_contract)
        }
    )
    pairs = pair_member_frame(executions, audit, all_names)

    print("[PRESSURE PROFILE 2/7] fitting five independent pairwise scorers", flush=True)
    states: dict[str, dict[str, Any]] = {}
    domain_rows: list[dict[str, Any]] = []
    validation_folds: list[pd.DataFrame] = []
    validation_predictions: list[pd.DataFrame] = []
    coefficient_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    reasons: list[str] = []
    minimum_pairs = int(contract["validation"]["minimum_positive_pairs_per_domain"])
    minimum_controls = int(contract["validation"]["minimum_control_pairs_per_domain"])
    for domain, domain_contract in contract["domains"].items():
        planned, positive, controls = filter_pairs_for_domain(
            pairs,
            domain,
            domain_contract,
            contract["pair_contract"],
        )
        if len(positive) < minimum_pairs:
            reasons.append(f"insufficient_positive_pairs:{domain}:{len(positive)}")
            continue
        if len(controls) < minimum_controls:
            reasons.append(f"insufficient_control_pairs:{domain}:{len(controls)}")
        state = fit_ranker(positive, controls, domain_contract, contract["estimator"])
        states[domain] = state
        apparent = pair_scores(positive, state)
        control_scores = pair_scores(controls, state) if not controls.empty else pd.DataFrame()
        summary = directional_summary(apparent)
        control_delta = (
            float(numeric(control_scores["score_delta"]).abs().median())
            if not control_scores.empty
            else math.nan
        )
        domain_rows.append(
            {
                "domain": domain,
                "planned_positive_pairs": len(planned),
                "eligible_positive_pairs": len(positive),
                "eligible_control_pairs": len(controls),
                "feature_count": len(domain_contract["features"]),
                "learned_apparent_direction_accuracy": summary[
                    "direction_accuracy"
                ],
                "coordinate_apparent_direction_accuracy": summary[
                    "baseline_direction_accuracy"
                ],
                "apparent_median_score_delta": summary["median_score_delta"],
                "control_median_absolute_delta": control_delta,
            }
        )
        folds, predictions = cross_validate_domain(
            positive,
            controls,
            domain,
            domain_contract,
            contract,
        )
        if not folds.empty:
            validation_folds.append(folds)
            validation_predictions.append(predictions)
        for spec, weight, baseline_weight, median, scale in zip(
            state["features"],
            state["weights"],
            state["baseline_weights"],
            state["medians"],
            state["scales"],
            strict=True,
        ):
            coefficient_rows.append(
                {
                    "domain": domain,
                    "feature": spec["name"],
                    "transform": spec["transform"],
                    "learned_weight": weight,
                    "handcrafted_weight": baseline_weight,
                    "transformed_median": median,
                    "transformed_iqr_scale": scale,
                }
            )
            values = numeric(executions[str(spec["name"])])
            coverage_rows.append(
                {
                    "domain": domain,
                    "feature": spec["name"],
                    "execution_count": len(values),
                    "available_count": int(values.notna().sum()),
                    "availability_share": float(values.notna().mean()),
                    "unique_value_count": int(values.nunique(dropna=True)),
                }
            )

    if set(states) != set(contract["domains"]):
        missing = sorted(set(contract["domains"]) - set(states))
        raise ValueError(f"Could not fit all five pressure scorers: {missing}")

    print("[PRESSURE PROFILE 3/7] evaluating grouped holdouts", flush=True)
    folds = pd.concat(validation_folds, ignore_index=True) if validation_folds else pd.DataFrame()
    predictions = (
        pd.concat(validation_predictions, ignore_index=True)
        if validation_predictions
        else pd.DataFrame()
    )
    validation_summary = (
        folds.groupby(["domain", "holdout"], as_index=False)
        .agg(
            pair_count=("test_pair_count", "sum"),
            direction_accuracy=("direction_accuracy", "mean"),
            baseline_direction_accuracy=("baseline_direction_accuracy", "mean"),
            minimum_fold_direction_accuracy=("direction_accuracy", "min"),
            fold_count=("held_out_group", "nunique"),
        )
        if not folds.empty
        else pd.DataFrame(
            columns=[
                "domain",
                "holdout",
                "pair_count",
                "direction_accuracy",
                "baseline_direction_accuracy",
                "minimum_fold_direction_accuracy",
                "fold_count",
            ]
        )
    )
    minimum_accuracy = float(contract["validation"]["minimum_direction_accuracy"])
    for domain in contract["domains"]:
        domain_validation = validation_summary[validation_summary["domain"].eq(domain)]
        for holdout in contract["validation"]["holdouts"]:
            holdout_name = str(holdout["name"])
            holdout_validation = domain_validation[
                domain_validation["holdout"].eq(holdout_name)
            ]
            if holdout_validation.empty:
                reasons.append(f"no_grouped_validation:{domain}:{holdout_name}")
            elif (
                float(holdout_validation["minimum_fold_direction_accuracy"].min())
                < minimum_accuracy
            ):
                reasons.append(f"direction_accuracy_below_gate:{domain}:{holdout_name}")

    print("[PRESSURE PROFILE 4/7] scoring and locally calibrating executions", flush=True)
    execution_scores, wide_profile = build_execution_scores(
        executions, states, contract
    )
    coordinate_components = build_coordinate_components(
        executions,
        execution_scores,
        states,
        provenance,
    )
    gac_component_profiles = build_gac_component_profiles(
        execution_scores,
        coordinate_components,
        contract,
    )
    final_coordinate_scores = pd.concat(
        [
            execution_scores[
                execution_scores["domain"].ne("gac_finalization")
            ],
            gac_component_profiles,
        ],
        ignore_index=True,
    )
    calibrated_scores = local_calibration(
        final_coordinate_scores,
        contract["local_calibration"],
    )
    gac_wide = gac_component_profiles.pivot(
        index="query_run_id", columns="domain", values="coordinate_score"
    )
    gac_wide = gac_wide.add_prefix("coordinate_").reset_index()
    wide_profile = wide_profile.merge(
        gac_wide, on="query_run_id", how="left", validate="one_to_one"
    )
    local_columns = calibrated_scores[
        [
            "query_run_id",
            "domain",
            "local_robust_z",
            "local_context_status",
            "coordinate_score_change_from_previous",
        ]
    ]
    z_wide = local_columns.pivot(index="query_run_id", columns="domain", values="local_robust_z")
    z_wide = z_wide.add_prefix("local_z_").reset_index()
    wide_profile = wide_profile.merge(z_wide, on="query_run_id", how="left", validate="one_to_one")
    status_wide = local_columns.pivot(
        index="query_run_id", columns="domain", values="local_context_status"
    )
    status_wide = status_wide.add_prefix("local_status_").reset_index()
    wide_profile = wide_profile.merge(
        status_wide, on="query_run_id", how="left", validate="one_to_one"
    )
    change_wide = local_columns.pivot(
        index="query_run_id",
        columns="domain",
        values="coordinate_score_change_from_previous",
    )
    change_wide = change_wide.add_prefix("coordinate_change_").reset_index()
    wide_profile = wide_profile.merge(
        change_wide, on="query_run_id", how="left", validate="one_to_one"
    )

    calibrated_scores["exact_reference_available"] = (
        calibrated_scores["local_context_status"].eq("available")
        & calibrated_scores["reference_scope"].eq("exact_query_context")
    )
    calibrated_scores["fallback_reference_available"] = (
        calibrated_scores["local_context_status"].eq("available")
        & calibrated_scores["reference_scope"].eq("logical_question_context")
    )
    calibration_summary = (
        calibrated_scores.groupby("domain", as_index=False)
        .agg(
            scored_execution_count=("coordinate_score", "count"),
            locally_calibrated_count=("local_robust_z", "count"),
            insufficient_history_count=(
                "local_context_status",
                lambda values: int(values.eq("insufficient_history").sum()),
            ),
            exact_reference_count=(
                "exact_reference_available",
                "sum",
            ),
            fallback_reference_count=(
                "fallback_reference_available",
                "sum",
            ),
            scale_floor_applied_count=(
                "local_scale_floor_applied",
                lambda values: int(values.fillna(False).astype(bool).sum()),
            ),
        )
    )
    audit_checks = methodological_audit(
        executions,
        pairs,
        final_coordinate_scores,
        predictions,
        contract,
    )
    failed_audits = sorted(
        name for name, values in audit_checks.items() if values["status"] != "PASS"
    )
    reasons.extend(f"methodological_audit_failed:{name}" for name in failed_audits)

    print("[PRESSURE PROFILE 5/7] building numerical response matrix", flush=True)
    pair_responses = build_pair_responses(
        final_coordinate_scores,
        audit,
        "coordinate_score",
        "transparent_coordinate",
    )
    response_matrix = build_response_matrix(pair_responses, audit, contract)
    learned_pair_responses = build_pair_responses(
        execution_scores,
        audit,
        "learned_ablation_score",
        "learned_ablation",
    )
    learned_response_matrix = build_response_matrix(
        learned_pair_responses, audit, contract
    )
    write_response_figure(
        response_matrix, out_dir / "coordinate_response_by_domain.png"
    )

    print("[PRESSURE PROFILE 6/7] writing model and analysis artifacts", flush=True)
    domain_summary = pd.DataFrame(domain_rows)
    domain_summary.to_csv(out_dir / "domain_summary.csv", index=False)
    calibrated_scores.to_csv(out_dir / "execution_pressure_scores.csv", index=False)
    execution_scores.to_csv(
        out_dir / "execution_ml_ablation_scores.csv", index=False
    )
    wide_profile.to_csv(out_dir / "execution_pressure_profile.csv", index=False)
    coordinate_components.to_csv(
        out_dir / "execution_coordinate_components.csv", index=False
    )
    pair_responses.to_csv(out_dir / "pair_pressure_response.csv", index=False)
    response_matrix.to_csv(out_dir / "pressure_response_matrix.csv", index=False)
    learned_pair_responses.to_csv(
        out_dir / "ml_ablation_pair_response.csv", index=False
    )
    learned_response_matrix.to_csv(
        out_dir / "ml_ablation_response_matrix.csv", index=False
    )
    folds.to_csv(out_dir / "scorer_validation_folds.csv", index=False)
    predictions.to_csv(out_dir / "scorer_validation_predictions.csv", index=False)
    validation_summary.to_csv(out_dir / "scorer_validation_summary.csv", index=False)
    pd.DataFrame(coefficient_rows).to_csv(out_dir / "scorer_coefficients.csv", index=False)
    pd.DataFrame(coverage_rows).to_csv(out_dir / "feature_coverage.csv", index=False)
    provenance.to_csv(out_dir / "feature_provenance.csv", index=False)
    (out_dir / "methodological_audit.json").write_text(
        json.dumps(audit_checks, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    joblib.dump(states, out_dir / "pressure_scorers.joblib")

    technical_gate = "GO" if not failed_audits else "NO_GO"
    learned_gate = (
        "GO_LEARNED_SCORERS" if not reasons else "MIXED_SCORER_EVIDENCE"
    )
    write_report(
        out_dir,
        domain_summary,
        validation_summary,
        response_matrix,
        calibration_summary,
        audit_checks,
        technical_gate,
        learned_gate,
        reasons,
    )

    print("[PRESSURE PROFILE 7/7] writing manifest and checksums", flush=True)
    manifest = {
        "contract_version": contract["contract_version"],
        "program_id": contract["program_id"],
        "technical_artifact_gate": technical_gate,
        "learned_scorer_evidence_gate": learned_gate,
        "learned_scorer_gate_reasons": reasons,
        "execution_count": len(executions),
        "pair_count": int(audit["pair_id"].nunique()),
        "domain_count": len(states),
        "diagnostic_output_contract": {
            domain: {
                "output_mode": domain_contract["output_mode"],
                "component_profiles": domain_contract.get("component_profiles", {}),
            }
            for domain, domain_contract in contract["domains"].items()
        },
        "domains": {
            domain: {
                "feature_names": feature_names(contract["domains"][domain]),
                "positive_pair_count": state["positive_pair_count"],
                "control_pair_count": state["control_pair_count"],
                "optimizer_objective": state["optimizer_objective"],
                "optimizer_iterations": state["optimizer_iterations"],
            }
            for domain, state in states.items()
        },
        "primary_coordinate_semantics": "transparent_post_execution_diagnostic_coordinate",
        "learned_projection_role": "ablation_only",
        "score_constraints": {
            "independently_displayed_domains": True,
            "sum_to_one": False,
            "bounded_interval": None,
            "gac_universal_scalar_defined": False,
        },
        "training_supervision": "learned_ablation_stressed_score_greater_than_mitigated_score",
        "cross_domain_ranking_allowed": False,
        "universal_thresholds_defined": False,
        "gain_prediction_included": False,
        "response_matrix_semantics": {
            "primary_file": "pressure_response_matrix.csv",
            "primary_score": "transparent_coordinate",
            "ml_ablation_file": "ml_ablation_response_matrix.csv",
            "cross_column_magnitude_comparison_allowed": False,
        },
        "local_calibration": contract["local_calibration"],
        "model_input_forbidden_fields": contract["forbidden_model_inputs"],
        "feature_provenance": contract["feature_provenance"],
        "methodological_audit": audit_checks,
    }
    (out_dir / "model_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    outputs = sorted(
        path for path in out_dir.iterdir() if path.is_file() and path.name != "checksums.sha256"
    )
    checksums = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in outputs
    ]
    (out_dir / "checksums.sha256").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
