from __future__ import annotations

import csv
from pathlib import Path

import yaml

from master_regimes.clustering_dataset import prepare_clustering_dataset


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_prepare_clustering_dataset_filters_rows_and_gates_features(tmp_path: Path) -> None:
    features_dir = tmp_path / "features"
    matrix_rows = [
        {
            "query_run_id": "q1",
            "elapsed_seconds": "0.10",
            "global_fanin_rows": "1000",
            "constant_feature": "7",
            "fdw_only_feature": "",
        },
        {
            "query_run_id": "q2",
            "elapsed_seconds": "0.20",
            "global_fanin_rows": "2000",
            "constant_feature": "7",
            "fdw_only_feature": "5",
        },
        {
            "query_run_id": "q3",
            "elapsed_seconds": "0.30",
            "global_fanin_rows": "3000",
            "constant_feature": "7",
            "fdw_only_feature": "5",
        },
        {
            "query_run_id": "q4",
            "elapsed_seconds": "0.40",
            "global_fanin_rows": "4000",
            "constant_feature": "7",
            "fdw_only_feature": "5",
        },
    ]
    fieldnames = [
        "query_run_id",
        "elapsed_seconds",
        "global_fanin_rows",
        "constant_feature",
        "fdw_only_feature",
    ]
    _write_csv(features_dir / "execution_features_m0.csv", matrix_rows, fieldnames)
    _write_csv(features_dir / "execution_features_m1.csv", matrix_rows, fieldnames)
    _write_csv(
        features_dir / "model_context.csv",
        [
            {
                "query_run_id": "q1",
                "template_id": "a",
                "execution_status": "ok",
                "timed_out": "false",
                "collection_error_count": "0",
                "warmup_run_flag": "false",
            },
            {
                "query_run_id": "q2",
                "template_id": "b",
                "execution_status": "ok",
                "timed_out": "false",
                "collection_error_count": "0",
                "warmup_run_flag": "false",
            },
            {
                "query_run_id": "q3",
                "template_id": "c",
                "execution_status": "timeout",
                "timed_out": "true",
                "collection_error_count": "0",
                "warmup_run_flag": "false",
            },
            {
                "query_run_id": "q4",
                "template_id": "d",
                "execution_status": "ok",
                "timed_out": "false",
                "collection_error_count": "1",
                "warmup_run_flag": "false",
            },
        ],
        [
            "query_run_id",
            "template_id",
            "execution_status",
            "timed_out",
            "collection_error_count",
            "warmup_run_flag",
        ],
    )

    out_dir = prepare_clustering_dataset(features_dir=features_dir, log_transform="off")

    clustering = _read_csv(out_dir / "clustering_input_m0.csv")
    row_report = _read_csv(out_dir / "row_filter_report.csv")
    dropped = _read_csv(out_dir / "dropped_features.csv")
    feature_report = _read_csv(out_dir / "feature_preprocessing_report.csv")

    assert [row["query_run_id"] for row in clustering] == ["q1", "q2"]
    assert "elapsed_seconds" in clustering[0]
    assert "global_fanin_rows" in clustering[0]
    assert "constant_feature" not in clustering[0]
    assert "fdw_only_feature" not in clustering[0]
    assert "fdw_only_feature__is_missing" in clustering[0]
    assert any(row["query_run_id"] == "q3" and row["kept"] == "0" for row in row_report)
    assert any(row["feature"] == "constant_feature" for row in dropped)
    assert any(
        row["source_feature"] == "fdw_only_feature"
        and row["reason"] == "missing_indicator"
        for row in feature_report
    )


def test_prepare_clustering_dataset_reports_insufficient_single_row_smoke(
    tmp_path: Path,
) -> None:
    features_dir = tmp_path / "features"
    fieldnames = ["query_run_id", "elapsed_seconds", "remote_region_observed_count"]
    matrix_rows = [
        {
            "query_run_id": "q1",
            "elapsed_seconds": "0.10",
            "remote_region_observed_count": "2",
        }
    ]
    _write_csv(features_dir / "execution_features_m0.csv", matrix_rows, fieldnames)
    _write_csv(features_dir / "execution_features_m1.csv", matrix_rows, fieldnames)
    _write_csv(
        features_dir / "model_context.csv",
        [
            {
                "query_run_id": "q1",
                "execution_status": "completed",
                "timed_out": "false",
                "collection_error_count": "0",
                "remote_error_count": "0",
                "warmup_run_flag": "false",
            }
        ],
        [
            "query_run_id",
            "execution_status",
            "timed_out",
            "collection_error_count",
            "remote_error_count",
            "warmup_run_flag",
        ],
    )

    out_dir = prepare_clustering_dataset(features_dir=features_dir, log_transform="off")

    manifest = yaml.safe_load((out_dir / "clustering_dataset_manifest.yml").read_text())
    readiness = _read_csv(out_dir / "clustering_readiness_report.csv")

    assert manifest["status"] == "insufficient_for_clustering"
    assert manifest["matrices"]["m0"]["status"] == "insufficient_features_after_preprocessing"
    assert not (out_dir / "clustering_input_m0.csv").exists()
    assert readiness[0]["status"] == "insufficient_features_after_preprocessing"
