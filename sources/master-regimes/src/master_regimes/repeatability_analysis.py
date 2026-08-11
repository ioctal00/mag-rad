from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

IDENTITY_COLUMNS = {
    "condition_id",
    "execution_id",
    "source_query_run_id",
    "repetition_index",
    "run_order",
    "attempt_number",
    "execution_status",
    "timed_out",
    "main_plan_fingerprint",
    "evidence_completeness",
    "ambiguous_candidate_count",
    "missing_applicable_evidence_count",
    "display_state",
    "hard_cluster",
}

ROBUST_SIGMA_SCALE = 1.4826
DEFAULT_TIMING_COLUMNS = (
    "elapsed_seconds",
    "main_root_actual_total_time_ms",
)


def prepare_attempt_frame(
    query_attempts: pd.DataFrame,
    query_runs: pd.DataFrame,
    raw_features: pd.DataFrame,
    projection: pd.DataFrame,
    evidence_audit: pd.DataFrame,
    selection: pd.DataFrame,
) -> pd.DataFrame:
    required_attempt = {
        "query_run_id",
        "condition_id",
        "repetition_index",
        "attempt_number",
        "execution_status",
    }
    missing = required_attempt - set(query_attempts.columns)
    if missing:
        raise ValueError(f"Logical attempts are missing fields: {sorted(missing)}")
    if (
        query_attempts["condition_id"].fillna("").astype(str).eq("").any()
        or query_attempts["repetition_index"].isna().any()
    ):
        raise ValueError("Repeatability attempt identity is incomplete")

    selected_sources = (
        selection[["condition_id", "source_query_run_id"]]
        .drop_duplicates("condition_id")
        .copy()
    )
    run_columns = [
        column
        for column in [
            "query_run_id",
            "plan_fingerprint",
            "run_order",
            "repetition_index",
            "condition_id",
        ]
        if column in query_runs.columns
    ]
    evidence_columns = [
        column
        for column in [
            "query_run_id",
            "evidence_completeness",
            "missing_region_count",
            "unexpected_region_count",
            "region_identity_duplicate_rows",
            "remote_sql_slot_duplicate_rows",
            "worker_identity_duplicate_rows",
            "plan_identity_duplicate_rows",
            "issue_count",
        ]
        if column in evidence_audit.columns
    ]
    frame = query_attempts.copy()
    frame["query_run_id"] = frame["query_run_id"].fillna("").astype(str)
    frame = frame.merge(
        query_runs[run_columns].drop_duplicates("query_run_id"),
        on="query_run_id",
        how="left",
        suffixes=("", "_run"),
    )
    frame = frame.merge(raw_features, on="query_run_id", how="left")
    frame = frame.merge(projection, on="query_run_id", how="left")
    frame = frame.merge(
        evidence_audit[evidence_columns].drop_duplicates("query_run_id"),
        on="query_run_id",
        how="left",
    )
    frame = frame.merge(selected_sources, on="condition_id", how="left")
    frame = frame.copy()

    frame["execution_id"] = frame["query_run_id"]
    if "run_order_run" in frame:
        frame["run_order"] = frame["run_order"].fillna(frame["run_order_run"])
    if "repetition_index_run" in frame:
        frame["repetition_index"] = frame["repetition_index"].fillna(
            frame["repetition_index_run"]
        )
    if "plan_fingerprint" in frame:
        frame["main_plan_fingerprint"] = frame["plan_fingerprint"]
    else:
        frame["main_plan_fingerprint"] = ""
    duplicate_columns = [
        "region_identity_duplicate_rows",
        "remote_sql_slot_duplicate_rows",
        "worker_identity_duplicate_rows",
        "plan_identity_duplicate_rows",
    ]
    frame["ambiguous_candidate_count"] = (
        frame[[column for column in duplicate_columns if column in frame]]
        .fillna(0)
        .sum(axis=1)
    )
    frame["missing_applicable_evidence_count"] = (
        frame[
            [
                column
                for column in ["missing_region_count", "unexpected_region_count"]
                if column in frame
            ]
        ]
        .fillna(0)
        .sum(axis=1)
    )
    return frame


def resolve_attempts(attempts: pd.DataFrame) -> pd.DataFrame:
    required = {
        "condition_id",
        "repetition_index",
        "attempt_number",
        "execution_status",
    }
    missing = required - set(attempts.columns)
    if missing:
        raise ValueError(f"Missing repeatability attempt columns: {sorted(missing)}")
    rows = []
    for _, group in attempts.groupby(
        ["condition_id", "repetition_index"], sort=True
    ):
        ordered = group.sort_values("attempt_number")
        completed = ordered[
            ordered["execution_status"].astype(str).eq("completed")
        ]
        rows.append((completed.iloc[-1] if not completed.empty else ordered.iloc[-1]).to_dict())
    return pd.DataFrame(rows)


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    membership = {
        column for column in frame.columns if column.startswith("membership_c")
    }
    candidates = [
        column
        for column in frame.columns
        if column not in IDENTITY_COLUMNS and column not in membership
    ]
    return [
        column
        for column in candidates
        if pd.api.types.is_numeric_dtype(frame[column])
    ]


def feature_stability(
    resolved: pd.DataFrame,
    *,
    epsilon: float = 1.0e-9,
    feature_columns: list[str] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for condition, group in resolved.groupby("condition_id", sort=True):
        for feature in feature_columns or _feature_columns(group):
            if feature not in group.columns:
                raise ValueError(f"Repeatability frame is missing feature {feature}")
            values = pd.to_numeric(group[feature], errors="coerce").dropna()
            if values.empty:
                rows.append(
                    {
                        "condition_id": condition,
                        "feature": feature,
                        "observed_repetitions": 0,
                        "median": math.nan,
                        "mad": math.nan,
                        "robust_relative_dispersion": math.nan,
                        "minimum": math.nan,
                        "maximum": math.nan,
                    }
                )
                continue
            median = float(values.median())
            mad = float((values - median).abs().median())
            rrd = (
                ROBUST_SIGMA_SCALE * mad / (abs(median) + epsilon)
                if abs(median) > epsilon
                else math.nan
            )
            rows.append(
                {
                    "condition_id": condition,
                    "feature": feature,
                    "observed_repetitions": len(values),
                    "median": median,
                    "mad": mad,
                    "robust_relative_dispersion": rrd,
                    "minimum": float(values.min()),
                    "maximum": float(values.max()),
                }
            )
    return pd.DataFrame(rows)


def fingerprint_stability(resolved: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for condition, group in resolved.groupby("condition_id", sort=True):
        fingerprints = (
            group["main_plan_fingerprint"].fillna("").astype(str).str.strip()
        )
        counts = fingerprints[fingerprints.ne("")].value_counts()
        rows.append(
            {
                "condition_id": condition,
                "repetition_count": len(group),
                "fingerprint_count": len(counts),
                "dominant_fingerprint": counts.index[0] if len(counts) else "",
                "dominant_fingerprint_share": (
                    float(counts.iloc[0] / len(group))
                    if len(counts) and len(group)
                    else math.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def evidence_completeness(resolved: pd.DataFrame) -> pd.DataFrame:
    return (
        resolved.groupby("condition_id", as_index=False)
        .agg(
            repetition_count=("repetition_index", "size"),
            minimum_completeness=("evidence_completeness", "min"),
            median_completeness=("evidence_completeness", "median"),
            complete_repetition_count=(
                "evidence_completeness",
                lambda values: int(pd.Series(values).eq(1.0).sum()),
            ),
            ambiguous_candidate_count=("ambiguous_candidate_count", "sum"),
            missing_applicable_evidence_count=(
                "missing_applicable_evidence_count",
                "sum",
            ),
        )
        .sort_values("condition_id")
    )


def membership_stability(resolved: pd.DataFrame) -> pd.DataFrame:
    membership_columns = sorted(
        column for column in resolved.columns if column.startswith("membership_c")
    )
    rows = []
    for condition, group in resolved.groupby("condition_id", sort=True):
        values = group[membership_columns].astype(float).to_numpy()
        mean = values.mean(axis=0)
        l1 = np.abs(values - mean).sum(axis=1)
        dominant = values.argmax(axis=1)
        counts = np.bincount(dominant, minlength=len(membership_columns))
        rows.append(
            {
                "condition_id": condition,
                "repetition_count": len(group),
                "mean_l1_to_condition_mean": float(l1.mean()),
                "max_l1_to_condition_mean": float(l1.max()),
                "dominant_cluster": int(counts.argmax()),
                "dominant_cluster_agreement": float(counts.max() / len(group)),
                **{
                    f"mean_{column}": float(mean[index])
                    for index, column in enumerate(membership_columns)
                },
            }
        )
    return pd.DataFrame(rows)


def display_transitions(resolved: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for condition, group in resolved.groupby("condition_id", sort=True):
        ordered = group.sort_values("repetition_index")
        states = ordered["display_state"].astype(str).tolist()
        if len(states) == 1:
            rows.append(
                {
                    "condition_id": condition,
                    "from_state": states[0],
                    "to_state": states[0],
                    "transition_count": 0,
                }
            )
            continue
        counts: dict[tuple[str, str], int] = {}
        for left, right in zip(states, states[1:], strict=False):
            counts[(left, right)] = counts.get((left, right), 0) + 1
        for (left, right), count in sorted(counts.items()):
            rows.append(
                {
                    "condition_id": condition,
                    "from_state": left,
                    "to_state": right,
                    "transition_count": count,
                }
            )
    return pd.DataFrame(rows)


def failure_retry_audit(attempts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in attempts.groupby(
        ["condition_id", "repetition_index"], sort=True
    ):
        condition, repetition = keys
        ordered = group.sort_values("attempt_number")
        rows.append(
            {
                "condition_id": condition,
                "repetition_index": repetition,
                "attempt_count": len(ordered),
                "first_status": str(ordered.iloc[0]["execution_status"]),
                "final_status": str(ordered.iloc[-1]["execution_status"]),
                "timeout_preserved": bool(
                    ordered["execution_status"].astype(str).eq("timeout").any()
                ),
                "completed_after_retry": bool(
                    len(ordered) > 1
                    and ordered.iloc[-1]["execution_status"] == "completed"
                ),
            }
        )
    return pd.DataFrame(rows)


def runtime_stability(
    resolved: pd.DataFrame,
    *,
    timing_columns: tuple[str, ...] = DEFAULT_TIMING_COLUMNS,
    epsilon: float = 1.0e-9,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for condition, group in resolved.groupby("condition_id", sort=True):
        for metric in timing_columns:
            if metric not in group.columns:
                continue
            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            if values.empty:
                continue
            mean = float(values.mean())
            median = float(values.median())
            standard_deviation = (
                float(values.std(ddof=1)) if len(values) > 1 else 0.0
            )
            mad = float((values - median).abs().median())
            rows.append(
                {
                    "condition_id": condition,
                    "metric": metric,
                    "observed_repetitions": len(values),
                    "mean": mean,
                    "standard_deviation": standard_deviation,
                    "coefficient_of_variation": (
                        standard_deviation / abs(mean)
                        if abs(mean) > epsilon
                        else math.nan
                    ),
                    "median": median,
                    "mad": mad,
                    "robust_relative_dispersion": (
                        ROBUST_SIGMA_SCALE * mad / abs(median)
                        if abs(median) > epsilon
                        else math.nan
                    ),
                    "minimum": float(values.min()),
                    "maximum": float(values.max()),
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "condition_id",
            "metric",
            "observed_repetitions",
            "mean",
            "standard_deviation",
            "coefficient_of_variation",
            "median",
            "mad",
            "robust_relative_dispersion",
            "minimum",
            "maximum",
        ],
    )


def _membership_condition_metrics(memberships: pd.DataFrame) -> pd.DataFrame:
    membership_columns = sorted(
        column
        for column in memberships.columns
        if column.startswith("mean_membership_c")
    )
    result = memberships.copy()
    values = result[membership_columns].astype(float).to_numpy()
    ordered = np.sort(values, axis=1)
    result["mean_top_membership"] = ordered[:, -1]
    result["mean_top2_margin"] = ordered[:, -1] - ordered[:, -2]
    return result


def condition_repeatability_summary(
    resolved: pd.DataFrame,
    *,
    fingerprints: pd.DataFrame,
    memberships: pd.DataFrame,
    runtime: pd.DataFrame,
) -> pd.DataFrame:
    metadata_columns = [
        column
        for column in [
            "condition_id",
            "execution_strategy",
            "dataset_profile_id",
            "dataset_id",
            "runtime_config_id",
            "template_id",
            "logical_question_id",
        ]
        if column in resolved.columns
    ]
    metadata = (
        resolved.sort_values(["condition_id", "repetition_index"])
        .drop_duplicates("condition_id")[metadata_columns]
        .copy()
    )
    state = (
        resolved.groupby("condition_id", as_index=False)
        .agg(
            repetition_count=("repetition_index", "size"),
            display_state=("display_state", "first"),
            display_state_count=("display_state", "nunique"),
        )
        .sort_values("condition_id")
    )
    membership_metrics = _membership_condition_metrics(memberships)
    summary = (
        metadata.merge(state, on="condition_id", how="left")
        .merge(
            fingerprints.drop(columns=["repetition_count"], errors="ignore"),
            on="condition_id",
            how="left",
        )
        .merge(
            membership_metrics.drop(
                columns=["repetition_count"],
                errors="ignore",
            ),
            on="condition_id",
            how="left",
        )
    )
    if not runtime.empty:
        runtime_wide = runtime.pivot(
            index="condition_id",
            columns="metric",
            values=["coefficient_of_variation", "robust_relative_dispersion"],
        )
        runtime_wide.columns = [
            f"{metric}_{measure}"
            for measure, metric in runtime_wide.columns.to_flat_index()
        ]
        summary = summary.merge(
            runtime_wide.reset_index(),
            on="condition_id",
            how="left",
        )
    return summary.sort_values("condition_id").reset_index(drop=True)


def grouped_repeatability_summary(
    conditions: pd.DataFrame,
    *,
    group_column: str,
) -> pd.DataFrame:
    if group_column not in conditions.columns:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for group_value, group in conditions.groupby(group_column, dropna=False):
        rows.append(
            {
                group_column: group_value,
                "condition_count": len(group),
                "repetition_count": int(group["repetition_count"].sum()),
                "plan_stable_condition_count": int(
                    (
                        group["fingerprint_count"].eq(1)
                        & group["dominant_fingerprint_share"].eq(1.0)
                    ).sum()
                ),
                "minimum_dominant_cluster_agreement": float(
                    group["dominant_cluster_agreement"].min()
                ),
                "median_top_membership": float(
                    group["mean_top_membership"].median()
                ),
                "median_top2_margin": float(group["mean_top2_margin"].median()),
                "median_mean_membership_l1": float(
                    group["mean_l1_to_condition_mean"].median()
                ),
                "maximum_membership_l1": float(
                    group["max_l1_to_condition_mean"].max()
                ),
                "clear_prototype_condition_count": int(
                    group["display_state"].eq("clear_prototype").sum()
                ),
                "mixed_boundary_condition_count": int(
                    group["display_state"].eq("mixed_boundary").sum()
                ),
                "weak_prototype_coverage_condition_count": int(
                    group["display_state"].eq(
                        "weak_prototype_coverage"
                    ).sum()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(group_column).reset_index(drop=True)


def _quantile(series: pd.Series, value: float) -> float:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return float(numeric.quantile(value)) if not numeric.empty else math.nan


def build_repeatability_summary(
    *,
    attempts: pd.DataFrame,
    resolved: pd.DataFrame,
    feature: pd.DataFrame,
    fingerprints: pd.DataFrame,
    evidence: pd.DataFrame,
    memberships: pd.DataFrame,
    transitions: pd.DataFrame,
    runtime: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    finite_rrd = feature["robust_relative_dispersion"].dropna()
    observed_feature = feature[feature["observed_repetitions"].gt(0)]
    off_diagonal = transitions[
        transitions["from_state"].ne(transitions["to_state"])
    ]
    runtime_summary: dict[str, Any] = {}
    for metric, group in runtime.groupby("metric", sort=True):
        runtime_summary[str(metric)] = {
            "median_coefficient_of_variation": _quantile(
                group["coefficient_of_variation"], 0.5
            ),
            "p95_coefficient_of_variation": _quantile(
                group["coefficient_of_variation"], 0.95
            ),
            "maximum_coefficient_of_variation": _quantile(
                group["coefficient_of_variation"], 1.0
            ),
        }
    state_counts = (
        resolved.groupby("condition_id")["display_state"]
        .first()
        .value_counts()
        .to_dict()
    )
    summary = {
        "condition_count": int(resolved["condition_id"].nunique()),
        "attempt_row_count": len(attempts),
        "resolved_execution_count": len(resolved),
        "plan_stable_condition_count": int(
            (
                fingerprints["fingerprint_count"].eq(1)
                & fingerprints["dominant_fingerprint_share"].eq(1.0)
            ).sum()
        ),
        "minimum_evidence_completeness": float(
            evidence["minimum_completeness"].min()
        ),
        "ambiguous_candidate_count": int(
            evidence["ambiguous_candidate_count"].sum()
        ),
        "minimum_dominant_cluster_agreement": float(
            memberships["dominant_cluster_agreement"].min()
        ),
        "median_mean_membership_l1": _quantile(
            memberships["mean_l1_to_condition_mean"], 0.5
        ),
        "p95_mean_membership_l1": _quantile(
            memberships["mean_l1_to_condition_mean"], 0.95
        ),
        "maximum_membership_l1": _quantile(
            memberships["max_l1_to_condition_mean"], 1.0
        ),
        "off_diagonal_display_transition_count": int(
            off_diagonal["transition_count"].sum()
        ),
        "display_state_condition_counts": {
            str(key): int(value) for key, value in state_counts.items()
        },
        "feature_condition_row_count": len(feature),
        "zero_mad_feature_condition_share": (
            float(observed_feature["mad"].eq(0).mean())
            if not observed_feature.empty
            else math.nan
        ),
        "median_feature_rrd": _quantile(finite_rrd, 0.5),
        "p95_feature_rrd": _quantile(finite_rrd, 0.95),
        "maximum_feature_rrd": _quantile(finite_rrd, 1.0),
        "not_applicable_feature_condition_count": int(
            feature["observed_repetitions"].eq(0).sum()
        ),
        "runtime_audit": runtime_summary,
    }
    flat_rows: list[dict[str, Any]] = []
    for key, value in summary.items():
        if key == "display_state_condition_counts":
            for state, count in value.items():
                flat_rows.append(
                    {
                        "scope": "display_state",
                        "metric": f"{state}_condition_count",
                        "value": count,
                    }
                )
        elif key == "runtime_audit":
            for metric, metrics in value.items():
                for runtime_key, runtime_value in metrics.items():
                    flat_rows.append(
                        {
                            "scope": metric,
                            "metric": runtime_key,
                            "value": runtime_value,
                        }
                    )
        else:
            flat_rows.append(
                {"scope": "overall", "metric": key, "value": value}
            )
    return summary, pd.DataFrame(flat_rows)


def repeatability_measure_dictionary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "measure": "dominant_fingerprint_share",
                "definition": "Udio ponavljanja sa najčešćim plan fingerprintom.",
                "interpretation": "1 znači isti dominantni fingerprint u svim ponavljanjima.",
            },
            {
                "measure": "robust_relative_dispersion",
                "definition": "1.4826 * MAD / abs(median); null kada je medijana nula.",
                "interpretation": "Robusna relativna promjena pokazatelja ili vremena.",
            },
            {
                "measure": "mean_l1_to_condition_mean",
                "definition": "Srednja L1 udaljenost membership vektora od srednjeg vektora uslova.",
                "interpretation": "Niža vrijednost znači stabilnije fuzzy članstvo.",
            },
            {
                "measure": "dominant_cluster_agreement",
                "definition": "Najveći udio ponavljanja sa istim argmax prototipom.",
                "interpretation": "1 znači isti dominantni prototip u svim ponavljanjima.",
            },
            {
                "measure": "display_state_transition",
                "definition": "Broj prijelaza između uzastopnih display-state vrijednosti.",
                "interpretation": "Off-diagonal prijelaz znači promjenu dijagnostičke kategorije.",
            },
            {
                "measure": "coefficient_of_variation",
                "definition": "Standardna devijacija podijeljena apsolutnom sredinom.",
                "interpretation": "Audit relativne runtime varijabilnosti; nije model feature.",
            },
        ]
    )


def write_repeatability_report(
    attempts: pd.DataFrame,
    *,
    out_dir: Path,
    manifest_extra: dict[str, Any] | None = None,
    feature_columns: list[str] | None = None,
) -> dict[str, Any]:
    resolved = resolve_attempts(attempts)
    selected_features = feature_columns or _feature_columns(resolved)
    feature = feature_stability(
        resolved,
        feature_columns=selected_features,
    )
    fingerprints = fingerprint_stability(resolved)
    evidence = evidence_completeness(resolved)
    memberships = membership_stability(resolved)
    transitions = display_transitions(resolved)
    failures = failure_retry_audit(attempts)
    runtime = runtime_stability(resolved)
    condition_repeatability = condition_repeatability_summary(
        resolved,
        fingerprints=fingerprints,
        memberships=memberships,
        runtime=runtime,
    )
    condition_summary = (
        resolved.groupby("condition_id", as_index=False)
        .agg(
            resolved_repetition_count=("repetition_index", "size"),
            execution_status=("execution_status", lambda x: ",".join(sorted(set(x)))),
            minimum_evidence_completeness=("evidence_completeness", "min"),
            main_plan_fingerprint_count=(
                "main_plan_fingerprint",
                lambda values: (
                    values.fillna("")
                    .astype(str)
                    .str.strip()
                    .replace("", pd.NA)
                    .nunique()
                ),
            ),
            display_state_count=("display_state", "nunique"),
        )
        .sort_values("condition_id")
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    condition_summary.to_csv(out_dir / "condition_summary.csv", index=False)
    feature.to_csv(out_dir / "feature_stability.csv", index=False)
    fingerprints.to_csv(out_dir / "fingerprint_stability.csv", index=False)
    evidence.to_csv(out_dir / "evidence_completeness.csv", index=False)
    memberships.to_csv(out_dir / "membership_stability.csv", index=False)
    transitions.to_csv(out_dir / "display_state_transitions.csv", index=False)
    failures.to_csv(out_dir / "failure_and_retry_audit.csv", index=False)
    runtime.to_csv(out_dir / "runtime_stability.csv", index=False)
    condition_repeatability.to_csv(
        out_dir / "condition_repeatability_summary.csv",
        index=False,
    )
    grouped_outputs = {
        "repeatability_by_strategy.csv": "execution_strategy",
        "repeatability_by_dataset.csv": "dataset_profile_id",
        "repeatability_by_runtime.csv": "runtime_config_id",
    }
    for file_name, group_column in grouped_outputs.items():
        grouped_repeatability_summary(
            condition_repeatability,
            group_column=group_column,
        ).to_csv(out_dir / file_name, index=False)
    repeatability_measure_dictionary().to_csv(
        out_dir / "repeatability_measure_dictionary.csv",
        index=False,
    )

    manifest = {
        "report_id": "repeatability-v1",
        "synthetic_fixture": False,
        "attempt_row_count": len(attempts),
        "resolved_execution_count": len(resolved),
        "condition_count": int(resolved["condition_id"].nunique()),
        "feature_count": len(selected_features),
        "timeout_attempt_count": int(
            attempts["execution_status"].astype(str).eq("timeout").sum()
        ),
        "retry_execution_count": int(
            failures["completed_after_retry"].sum()
        ),
        "minimum_evidence_completeness": float(
            evidence["minimum_completeness"].min()
        ),
        "ambiguous_candidate_count": int(
            evidence["ambiguous_candidate_count"].sum()
        ),
        "database_result_rows_stored": False,
        **(manifest_extra or {}),
    }
    summary, summary_table = build_repeatability_summary(
        attempts=attempts,
        resolved=resolved,
        feature=feature,
        fingerprints=fingerprints,
        evidence=evidence,
        memberships=memberships,
        transitions=transitions,
        runtime=runtime,
    )
    (out_dir / "repeatability_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "repeatability_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_table.to_csv(out_dir / "repeatability_summary.csv", index=False)
    if manifest["synthetic_fixture"]:
        closing_lines = [
            "## Sintetički fixture",
            "",
            "Namjerno ubačeni missing/duplicate/fingerprint-drift slučajevi",
            "moraju ostati vidljivi u izlazima.",
        ]
    else:
        unresolved_count = int(
            manifest.get("collector_unresolved_issue_count", 0)
        )
        closing_lines = [
            "## Primjenjivost i ograničenje",
            "",
            (
                "Nisu pronađeni nerazriješeni collector problemi."
                if unresolved_count == 0
                else f"Nerazriješeni collector problemi: {unresolved_count}."
            ),
            (
                "Null vrijednost zbog odsustva operatora ili neprimjenjivog "
                "evidence sloja nije collector rupa."
            ),
            (
                "Runtime se prikazuje kao odvojeni audit i nije dio "
                "zaključanog 21-feature modela."
            ),
        ]
    (out_dir / "README.md").write_text(
        "\n".join(
            [
                "# Repeatability v1",
                "",
                (
                    "Ovaj paket sažima ponovljena izvršenja po zaključanom "
                    "`condition_id` ugovoru."
                    if not manifest["synthetic_fixture"]
                    else "Ovaj paket je lokalna sintetička provjera ugovora."
                ),
                "",
                f"- Uslovi: {manifest['condition_count']}",
                f"- Razriješena izvršenja: {manifest['resolved_execution_count']}",
                f"- Feature-i: {manifest['feature_count']}",
                f"- Timeout attempti: {manifest['timeout_attempt_count']}",
                f"- Uspješni retry slučajevi: {manifest['retry_execution_count']}",
                "",
                "## Integritet prikupljanja",
                "",
                (
                    f"- Minimalna evidence completeness vrijednost: "
                    f"{summary['minimum_evidence_completeness']:.3f}"
                ),
                (
                    f"- Dvosmisleni kandidati: "
                    f"{summary['ambiguous_candidate_count']}"
                ),
                "",
                "## Ponovljivost reprezentacije",
                "",
                (
                    f"- Uslovi sa stabilnim plan fingerprintom: "
                    f"{summary['plan_stable_condition_count']}/"
                    f"{summary['condition_count']}"
                ),
                (
                    f"- Udio feature/uslov parova sa nultim MAD-om: "
                    f"{summary['zero_mad_feature_condition_share']:.3f}"
                ),
                (
                    f"- 95. percentil feature RRD: "
                    f"{summary['p95_feature_rrd']:.6f}"
                ),
                "",
                "## Ponovljivost dijagnostičkog izlaza",
                "",
                (
                    f"- Minimalno slaganje dominantnog prototipa: "
                    f"{summary['minimum_dominant_cluster_agreement']:.3f}"
                ),
                (
                    f"- Off-diagonal display-state prijelazi: "
                    f"{summary['off_diagonal_display_transition_count']}"
                ),
                (
                    f"- 95. percentil srednjeg membership L1 pomaka: "
                    f"{summary['p95_mean_membership_l1']:.6f}"
                ),
                "",
                *closing_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return manifest
