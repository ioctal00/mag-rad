from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE_13_PATH = ROOT / "analysis/scripts/agent/13_nplusone_contract_audit.py"


def _load_phase13():
    script_dir = str(PHASE_13_PATH.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("phase13_nplusone_contract_audit", PHASE_13_PATH)
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


def test_phase13_rejects_child_identity_and_raw_plan_fields_in_m0(tmp_path: Path) -> None:
    phase13 = _load_phase13()
    index_dir = tmp_path / "_index"
    features_dir = tmp_path / "features"
    query_run_id = "q1"

    _write_csv(
        index_dir / "query_runs.csv",
        [
            {
                "query_run_id": query_run_id,
                "execution_status": "completed",
                "timed_out": "false",
                "execution_strategy": "multiregion_union",
                "main_has_foreign_scan": "true",
                "remote_region_observed_count": "2",
                "remote_region_evidence_completeness": "1",
                "worker_task_plan_count": "64",
            }
        ],
        [
            "query_run_id",
            "execution_status",
            "timed_out",
            "execution_strategy",
            "main_has_foreign_scan",
            "remote_region_observed_count",
            "remote_region_evidence_completeness",
            "worker_task_plan_count",
        ],
    )
    _write_csv(
        index_dir / "execution_features.csv",
        [
            {
                "query_run_id": query_run_id,
                "execution_status": "completed",
                "timed_out": "false",
                "execution_strategy": "multiregion_union",
                "main_has_foreign_scan": "true",
                "remote_region_observed_count": "2",
                "remote_region_evidence_completeness": "1",
                "worker_task_plan_count": "64",
            }
        ],
        [
            "query_run_id",
            "execution_status",
            "timed_out",
            "execution_strategy",
            "main_has_foreign_scan",
            "remote_region_observed_count",
            "remote_region_evidence_completeness",
            "worker_task_plan_count",
        ],
    )
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
            {"query_run_id": query_run_id, "fdw_region": "eu", "task_index": "1"},
            {"query_run_id": query_run_id, "fdw_region": "us", "task_index": "1"},
        ],
        ["query_run_id", "fdw_region", "task_index"],
    )
    _write_csv(
        index_dir / "plan_files.csv",
        [{"query_run_id": query_run_id, "plan_scope": "fdw_auto_explain_remote"}],
        ["query_run_id", "plan_scope"],
    )

    m0_fields = [
        "query_run_id",
        *phase13.REQUIRED_M0_FEATURES,
        "region_id",
        "worker_task_node_type_unknown_set_json",
        "rendered_sql_hash",
        "plan_fingerprint",
    ]
    m0_row = {"query_run_id": query_run_id}
    for field in phase13.REQUIRED_M0_FEATURES:
        m0_row[field] = "1"
    m0_row.update(
        {
            "region_id": "eu",
            "worker_task_node_type_unknown_set_json": "[]",
            "rendered_sql_hash": "abc",
            "plan_fingerprint": "abc",
        }
    )
    _write_csv(features_dir / "execution_features_m0.csv", [m0_row], m0_fields)

    report = phase13.build_report(index_dir, features_dir)

    assert "| no_child_identity_leakage_in_m0 | fail |" in report
    assert "region_id" in report
    assert "worker_task_node_type_unknown_set_json" in report
    assert "rendered_sql_hash" in report
    assert "plan_fingerprint" in report
