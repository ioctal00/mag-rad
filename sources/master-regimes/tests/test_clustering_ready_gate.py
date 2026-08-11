from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE_11_PATH = ROOT / "analysis/scripts/agent/11_clustering_ready_gate.py"


def _load_phase11():
    script_dir = str(PHASE_11_PATH.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("phase11_clustering_ready_gate", PHASE_11_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_phase11_warns_for_single_row_preprocessing_insufficient(
    tmp_path: Path,
) -> None:
    phase11 = _load_phase11()
    index_dir = tmp_path / "_index"
    features_dir = tmp_path / "features"
    query_run_id = "q1"
    query_fields = [
        "query_run_id",
        "execution_status",
        "timed_out",
        "execution_strategy",
        "main_has_foreign_scan",
    ]
    rich_fields = query_fields + [
        "remote_region_observed_count",
        "remote_region_evidence_completeness",
        "worker_task_plan_count",
    ]
    rich_fields.extend(field for field in phase11.KEY_M0_FEATURES if field not in rich_fields)
    rich_row = {
        "query_run_id": query_run_id,
        "execution_status": "completed",
        "timed_out": "false",
        "execution_strategy": "multiregion_union",
        "main_has_foreign_scan": "true",
        "remote_region_observed_count": "2",
        "remote_region_evidence_completeness": "1",
        "worker_task_plan_count": "64",
    }
    for field in phase11.KEY_M0_FEATURES:
        rich_row.setdefault(field, "1")

    _write_csv(
        index_dir / "query_runs.csv",
        [{field: rich_row[field] for field in query_fields}],
        query_fields,
    )
    _write_csv(index_dir / "execution_features.csv", [rich_row], rich_fields)
    _write_csv(
        index_dir / "region_fragments.csv",
        [
            {"query_run_id": query_run_id, "region_id": "eu", "source_type": "fdw_auto_explain_remote"},
            {"query_run_id": query_run_id, "region_id": "us", "source_type": "fdw_auto_explain_remote"},
        ],
        ["query_run_id", "region_id", "source_type"],
    )
    _write_csv(
        index_dir / "worker_task_fragments.csv",
        [
            {
                "query_run_id": query_run_id,
                "fdw_region": "eu",
                "worker_task_node_type_unknown_count": "0",
                "worker_task_node_type_unknown_set_json": "[]",
            }
        ],
        [
            "query_run_id",
            "fdw_region",
            "worker_task_node_type_unknown_count",
            "worker_task_node_type_unknown_set_json",
        ],
    )
    _write_csv(
        index_dir / "plan_files.csv",
        [{"query_run_id": query_run_id, "plan_scope": "fdw_auto_explain_remote"}],
        ["query_run_id", "plan_scope"],
    )
    m0_fields = ["query_run_id", *phase11.KEY_M0_FEATURES]
    m0_row = {"query_run_id": query_run_id}
    for field in phase11.KEY_M0_FEATURES:
        m0_row[field] = rich_row[field]
    _write_csv(features_dir / "execution_features_m0.csv", [m0_row], m0_fields)
    _write_csv(
        features_dir / "preprocessed" / "clustering_readiness_report.csv",
        [
            {
                "matrix": "m0",
                "status": "insufficient_features_after_preprocessing",
                "row_count": "1",
                "feature_count": "0",
                "warnings": "insufficient_features_after_preprocessing",
            }
        ],
        ["matrix", "status", "row_count", "feature_count", "warnings"],
    )

    report = phase11.build_report(index_dir, features_dir)

    assert "parser_ready_but_preprocessing_sample_small" in report
    assert "| preprocessed_m0_available | warn | insufficient_features_after_preprocessing |" in report
    assert "| preprocessed_nplusone_feature_groups_present | warn |" in report
    assert "| preprocessed_m0_available | fail |" not in report


def test_phase11_rejects_generated_identity_and_raw_hash_leakage() -> None:
    phase11 = _load_phase11()

    leaked = phase11._forbidden_model_fields(
        [
            "query_run_id",
            "remote_region_actual_rows_cv",
            "region_id",
            "worker_task_node_type_unknown_set_json",
            "rendered_sql_hash",
            "plan_fingerprint",
            "worker_task_plan_fingerprint_count",
        ]
    )

    assert leaked == [
        "plan_fingerprint",
        "region_id",
        "rendered_sql_hash",
        "worker_task_node_type_unknown_set_json",
    ]
