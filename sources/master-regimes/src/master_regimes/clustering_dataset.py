from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import Any

from .config import write_yaml

MATRIX_FILES = {
    "m0": "execution_features_m0.csv",
    "m1": "execution_features_m1.csv",
}

BAD_STATUSES = {
    "failed",
    "failure",
    "error",
    "errored",
    "timeout",
    "timed_out",
    "cancelled",
    "canceled",
}


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int_or_zero(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _row_filter_reasons(context_row: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    status = str(context_row.get("execution_status", "")).strip().lower()
    if status in BAD_STATUSES:
        reasons.append(f"execution_status={status}")
    if _truthy(context_row.get("timed_out")):
        reasons.append("timed_out=true")
    if _int_or_zero(context_row.get("collection_error_count")) > 0:
        reasons.append("collection_error_count>0")
    if _int_or_zero(context_row.get("remote_error_count")) > 0:
        reasons.append("remote_error_count>0")
    if _truthy(context_row.get("warmup_run_flag")):
        reasons.append("warmup_run_flag=true")
    return reasons


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _population_std(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _should_log1p(feature: str, values: list[float], policy: str) -> bool:
    if policy == "off":
        return False
    if not values or any(value < 0 for value in values):
        return False
    if max(values) <= 10:
        return False
    name = feature.lower()
    tokens = (
        "rows",
        "bytes",
        "blocks",
        "cost",
        "time",
        "seconds",
        "count",
        "width",
        "memory",
        "fanin",
        "task",
        "ratio",
    )
    return any(token in name for token in tokens)


def _standardize(values: list[float]) -> tuple[list[float], float, float]:
    mean = _mean(values)
    std = _population_std(values)
    if std == 0:
        return [], mean, std
    return [(value - mean) / std for value in values], mean, std


def _feature_stats(
    *,
    matrix: str,
    feature: str,
    values: list[str],
) -> dict[str, Any]:
    parsed = [_float_or_none(value) for value in values]
    numeric = [value for value in parsed if value is not None]
    non_blank = [value for value in values if value not in ("", None)]
    return {
        "matrix": matrix,
        "feature": feature,
        "row_count": len(values),
        "non_null_count": len(numeric),
        "null_count": len(values) - len(numeric),
        "null_fraction": (len(values) - len(numeric)) / len(values) if values else "",
        "non_numeric_count": len(non_blank) - len(numeric),
        "distinct_non_null_count": len({repr(value) for value in numeric}),
        "min": min(numeric) if numeric else "",
        "max": max(numeric) if numeric else "",
    }


def _add_missing_indicator(
    *,
    matrix: str,
    feature: str,
    parsed_values: list[float | None],
    output_rows: list[dict[str, Any]],
    report_rows: list[dict[str, Any]],
) -> int:
    indicator_values = [1.0 if value is None else 0.0 for value in parsed_values]
    if len(set(indicator_values)) <= 1:
        return 0
    standardized, mean, std = _standardize(indicator_values)
    if not standardized:
        return 0
    output_feature = f"{feature}__is_missing"
    for row, value in zip(output_rows, standardized, strict=True):
        row[output_feature] = value
    report_rows.append(
        {
            "matrix": matrix,
            "source_feature": feature,
            "output_feature": output_feature,
            "status": "kept",
            "reason": "missing_indicator",
            "transform": "identity",
            "imputation": "not_applicable",
            "center": mean,
            "scale": std,
            "null_fraction": "",
            "non_null_count": "",
            "distinct_non_null_count": 2,
        }
    )
    return 1


def _prepare_matrix(
    *,
    matrix: str,
    rows: list[dict[str, str]],
    fieldnames: list[str],
    max_null_fraction: float,
    min_non_null: int,
    add_missing_indicators: bool,
    log_transform: str,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    output_rows: list[dict[str, Any]] = [
        {"query_run_id": row.get("query_run_id", "")} for row in rows
    ]
    output_fields = ["query_run_id"]
    report_rows: list[dict[str, Any]] = []
    dropped_rows: list[dict[str, Any]] = []

    for feature in [field for field in fieldnames if field != "query_run_id"]:
        raw_values = [row.get(feature, "") for row in rows]
        parsed_values = [_float_or_none(value) for value in raw_values]
        numeric_values = [value for value in parsed_values if value is not None]
        stats = _feature_stats(matrix=matrix, feature=feature, values=raw_values)
        reason = ""

        if stats["non_numeric_count"] > 0:
            reason = "non_numeric_values_present"
        elif stats["non_null_count"] < min_non_null:
            reason = "too_few_non_null_values"
        elif stats["null_fraction"] != "" and stats["null_fraction"] > max_null_fraction:
            reason = "null_fraction_above_threshold"
        elif stats["distinct_non_null_count"] <= 1:
            reason = "constant_non_null_values"

        if reason:
            dropped_rows.append({**stats, "reason": reason})
            if (
                add_missing_indicators
                and reason in {"constant_non_null_values", "too_few_non_null_values"}
                and stats["null_count"] > 0
            ):
                added = _add_missing_indicator(
                    matrix=matrix,
                    feature=feature,
                    parsed_values=parsed_values,
                    output_rows=output_rows,
                    report_rows=report_rows,
                )
                if added:
                    output_fields.append(f"{feature}__is_missing")
            continue

        use_log = _should_log1p(feature, numeric_values, log_transform)
        transformed_non_null = [
            math.log1p(value) if use_log else value for value in numeric_values
        ]
        impute_value = _median(transformed_non_null)
        completed = [
            (math.log1p(value) if use_log else value) if value is not None else impute_value
            for value in parsed_values
        ]
        standardized, center, scale = _standardize(completed)
        if not standardized:
            dropped_rows.append({**stats, "reason": "constant_after_imputation"})
            continue

        for row, value in zip(output_rows, standardized, strict=True):
            row[feature] = value
        output_fields.append(feature)
        report_rows.append(
            {
                "matrix": matrix,
                "source_feature": feature,
                "output_feature": feature,
                "status": "kept",
                "reason": "",
                "transform": "log1p" if use_log else "identity",
                "imputation": "median" if stats["null_count"] else "none",
                "center": center,
                "scale": scale,
                "null_fraction": stats["null_fraction"],
                "non_null_count": stats["non_null_count"],
                "distinct_non_null_count": stats["distinct_non_null_count"],
            }
        )

        if add_missing_indicators and stats["null_count"] > 0:
            added = _add_missing_indicator(
                matrix=matrix,
                feature=feature,
                parsed_values=parsed_values,
                output_rows=output_rows,
                report_rows=report_rows,
            )
            if added:
                output_fields.append(f"{feature}__is_missing")

    return output_rows, output_fields, report_rows, dropped_rows


def _filter_rows(
    *,
    matrix_rows: list[dict[str, str]],
    context_by_run: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    kept: list[dict[str, str]] = []
    report_rows: list[dict[str, Any]] = []
    for row in matrix_rows:
        query_run_id = row.get("query_run_id", "")
        context_row = context_by_run.get(query_run_id, {})
        reasons = _row_filter_reasons(context_row)
        keep = not reasons
        if keep:
            kept.append(row)
        report_rows.append(
            {
                "query_run_id": query_run_id,
                "kept": 1 if keep else 0,
                "reason": ";".join(reasons) if reasons else "",
            }
        )
    return kept, report_rows


def prepare_clustering_dataset(
    *,
    features_dir: Path,
    out_dir: Path | None = None,
    max_null_fraction: float = 0.8,
    min_non_null: int = 2,
    add_missing_indicators: bool = True,
    log_transform: str = "auto",
) -> Path:
    features_dir = features_dir.resolve()
    if out_dir is None:
        out_dir = features_dir / "clustering"
    else:
        out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    context_rows, context_fields = _read_csv(features_dir / "model_context.csv")
    context_by_run = {row.get("query_run_id", ""): row for row in context_rows}
    filtered_query_run_ids: set[str] = set()
    all_row_filter_reports: list[dict[str, Any]] = []
    all_feature_reports: list[dict[str, Any]] = []
    all_dropped_features: list[dict[str, Any]] = []
    readiness_rows: list[dict[str, Any]] = []
    matrix_manifest: dict[str, Any] = {}

    for matrix, filename in MATRIX_FILES.items():
        matrix_rows, matrix_fields = _read_csv(features_dir / filename)
        if not matrix_rows:
            continue
        kept_rows, row_filter_report = _filter_rows(
            matrix_rows=matrix_rows,
            context_by_run=context_by_run,
        )
        all_row_filter_reports.extend(
            {**row, "matrix": matrix} for row in row_filter_report
        )
        if not kept_rows:
            matrix_manifest[matrix] = {
                "source_file": filename,
                "status": "no_usable_rows_after_quality_gate",
                "row_count_before_filter": len(matrix_rows),
                "row_count_after_filter": 0,
                "feature_count_after_preprocessing": 0,
                "feature_to_row_ratio": "",
                "readiness_warnings": ["no_usable_rows_after_quality_gate"],
                "output": "",
            }
            readiness_rows.append(
                {
                    "matrix": matrix,
                    "status": "no_usable_rows_after_quality_gate",
                    "row_count": 0,
                    "feature_count": 0,
                    "feature_to_row_ratio": "",
                    "warning_count": 1,
                    "warnings": "no_usable_rows_after_quality_gate",
                }
            )
            continue
        filtered_query_run_ids.update(row.get("query_run_id", "") for row in kept_rows)

        prepared_rows, prepared_fields, feature_report, dropped_features = _prepare_matrix(
            matrix=matrix,
            rows=kept_rows,
            fieldnames=matrix_fields,
            max_null_fraction=max_null_fraction,
            min_non_null=min_non_null,
            add_missing_indicators=add_missing_indicators,
            log_transform=log_transform,
        )
        if len(prepared_fields) <= 1:
            all_dropped_features.extend(dropped_features)
            matrix_manifest[matrix] = {
                "source_file": filename,
                "status": "insufficient_features_after_preprocessing",
                "row_count_before_filter": len(matrix_rows),
                "row_count_after_filter": len(kept_rows),
                "feature_count_after_preprocessing": 0,
                "feature_to_row_ratio": 0,
                "readiness_warnings": ["insufficient_features_after_preprocessing"],
                "output": "",
            }
            readiness_rows.append(
                {
                    "matrix": matrix,
                    "status": "insufficient_features_after_preprocessing",
                    "row_count": len(kept_rows),
                    "feature_count": 0,
                    "feature_to_row_ratio": 0,
                    "warning_count": 1,
                    "warnings": "insufficient_features_after_preprocessing",
                }
            )
            continue
        _write_csv(out_dir / f"clustering_input_{matrix}.csv", prepared_rows, prepared_fields)
        all_feature_reports.extend(feature_report)
        all_dropped_features.extend(dropped_features)
        feature_count = len(prepared_fields) - 1
        row_count = len(kept_rows)
        feature_to_row_ratio = feature_count / row_count if row_count else ""
        warnings: list[str] = []
        if row_count < 50:
            warnings.append("small_row_count_for_clustering")
        if row_count < feature_count * 5:
            warnings.append("rows_less_than_5x_feature_count")
        matrix_manifest[matrix] = {
            "source_file": filename,
            "status": "ready",
            "row_count_before_filter": len(matrix_rows),
            "row_count_after_filter": row_count,
            "feature_count_after_preprocessing": feature_count,
            "feature_to_row_ratio": feature_to_row_ratio,
            "readiness_warnings": warnings,
            "output": f"clustering_input_{matrix}.csv",
        }
        readiness_rows.append(
            {
                "matrix": matrix,
                "status": "ready",
                "row_count": row_count,
                "feature_count": feature_count,
                "feature_to_row_ratio": feature_to_row_ratio,
                "warning_count": len(warnings),
                "warnings": ";".join(warnings),
            }
        )

    filtered_context = [
        row for row in context_rows if row.get("query_run_id", "") in filtered_query_run_ids
    ]
    if filtered_context:
        _write_csv(out_dir / "clustering_context.csv", filtered_context, context_fields)

    _write_csv(
        out_dir / "row_filter_report.csv",
        all_row_filter_reports,
        ["matrix", "query_run_id", "kept", "reason"],
    )
    _write_csv(
        out_dir / "feature_preprocessing_report.csv",
        all_feature_reports,
        [
            "matrix",
            "source_feature",
            "output_feature",
            "status",
            "reason",
            "transform",
            "imputation",
            "center",
            "scale",
            "null_fraction",
            "non_null_count",
            "distinct_non_null_count",
        ],
    )
    _write_csv(
        out_dir / "dropped_features.csv",
        all_dropped_features,
        [
            "matrix",
            "feature",
            "row_count",
            "non_null_count",
            "null_count",
            "null_fraction",
            "non_numeric_count",
            "distinct_non_null_count",
            "min",
            "max",
            "reason",
        ],
    )
    _write_csv(
        out_dir / "clustering_readiness_report.csv",
        readiness_rows,
        [
            "matrix",
            "status",
            "row_count",
            "feature_count",
            "feature_to_row_ratio",
            "warning_count",
            "warnings",
        ],
    )

    manifest = {
        "clustering_dataset_contract": "master_regimes_clustering_dataset_v1",
        "source_features_dir": str(features_dir),
        "status": (
            "ready"
            if any(matrix.get("status") == "ready" for matrix in matrix_manifest.values())
            else "insufficient_for_clustering"
        ),
        "outputs": {
            "m0": "clustering_input_m0.csv",
            "m1": "clustering_input_m1.csv",
            "context": "clustering_context.csv",
            "row_filter_report": "row_filter_report.csv",
            "feature_preprocessing_report": "feature_preprocessing_report.csv",
            "dropped_features": "dropped_features.csv",
            "clustering_readiness_report": "clustering_readiness_report.csv",
        },
        "matrices": matrix_manifest,
        "row_quality_gate": {
            "drop_bad_execution_statuses": sorted(BAD_STATUSES),
            "drop_timed_out": True,
            "drop_collection_error_count_gt_zero": True,
            "drop_remote_error_count_gt_zero": True,
            "drop_warmup_runs": True,
        },
        "feature_quality_gate": {
            "max_null_fraction": max_null_fraction,
            "min_non_null": min_non_null,
            "drop_non_numeric": True,
            "drop_constant": True,
            "add_missing_indicators": add_missing_indicators,
            "imputation": "median",
            "scaling": "z_score_population_std",
            "log_transform": log_transform,
        },
        "rules": {
            "null_policy": (
                "NULL is never encoded as zero. Missing numeric values are median-imputed "
                "after optional log transform, and variable missingness is exposed through "
                "*__is_missing indicators."
            ),
            "context_policy": (
                "IDs, labels, runtime knobs, fingerprints and audit columns are preserved in "
                "clustering_context.csv, not injected into clustering_input_*.csv."
            ),
        },
    }
    write_yaml(out_dir / "clustering_dataset_manifest.yml", manifest)
    return out_dir
