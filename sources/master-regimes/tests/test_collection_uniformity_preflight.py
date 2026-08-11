from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    script = ROOT / "analysis/scripts/agent/83_collection_uniformity_preflight.py"
    spec = importlib.util.spec_from_file_location(
        "collection_uniformity_preflight",
        script,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uniformity_contract_accepts_linked_remote_and_text_task_evidence() -> None:
    module = load_module()
    query_run_id = "q1"
    parent_plan_id = "q1:remote"
    executions = [
        {
            "query_run_id": query_run_id,
            "collection_family": "distributed_join",
            "source_index_id": "probe",
            "execution_status": "completed",
            "regional_plan_evidence_status": "available",
            "regional_remote_plan_count": "1",
            "remote_region_evidence_completeness": "1.0",
            "worker_task_evidence_status": "available",
            "worker_task_plan_count": "1",
            "worker_task_plan_format": "citus_embedded_text_in_explain_json",
            "worker_task_timing_status": "unavailable_in_embedded_task_plan",
            "worker_task_parse_ok_count": "0",
            "worker_task_parse_partial_count": "1",
            "worker_task_parse_failed_count": "0",
            "result_signature_status": "completed",
            "result_multiset_sha256": "abc",
            "database_result_rows_stored": "false",
        }
    ]
    children = {
        table: []
        for table in module.CHILD_TABLES
    }
    children["plan_files"] = [
        {"query_run_id": query_run_id, "plan_id": "q1:main", "plan_scope": "main"},
        {
            "query_run_id": query_run_id,
            "plan_id": parent_plan_id,
            "plan_scope": "fdw_auto_explain_remote",
        },
    ]
    children["fdw_remote_plans"] = [
        {
            "query_run_id": query_run_id,
            "plan_id": parent_plan_id,
            "remote_sql_text": "DECLARE c CURSOR FOR SELECT 1",
        }
    ]
    children["region_fragments"] = [
        {
            "query_run_id": query_run_id,
            "remote_plan_id": parent_plan_id,
            "source_type": "fdw_auto_explain_remote",
        }
    ]
    children["worker_task_fragments"] = [
        {
            "query_run_id": query_run_id,
            "plan_id": parent_plan_id,
            "parse_status": "partial",
        }
    ]
    children["plan_nodes"] = [
        {
            "query_run_id": query_run_id,
            "plan_id": f"{parent_plan_id}:task_000",
            "parent_plan_id": parent_plan_id,
        }
    ]
    children["plan_edges"] = [
        {
            "query_run_id": query_run_id,
            "plan_id": f"{parent_plan_id}:task_000",
            "parent_plan_id": parent_plan_id,
        }
    ]

    quality = module.evidence_quality_rows(executions, children)
    errors, warnings = module.validate(executions, children, quality)

    assert errors == []
    assert [warning["check_id"] for warning in warnings] == [
        "worker_task_timing_unavailable"
    ]


def test_remote_path_requires_two_unique_available_edges() -> None:
    module = load_module()
    query_run_id = "q-edge"
    executions = [
        {
            "query_run_id": query_run_id,
            "collection_family": "remote_path",
            "source_index_id": "remote-edge-probe",
            "execution_status": "completed",
            "regional_plan_evidence_status": "available",
            "regional_remote_plan_count": "2",
            "remote_region_evidence_completeness": "1.0",
            "worker_task_evidence_status": "not_applicable",
            "worker_task_plan_count": "0",
            "worker_task_timing_status": "not_applicable",
            "worker_task_parse_ok_count": "0",
            "worker_task_parse_partial_count": "0",
            "worker_task_parse_failed_count": "0",
            "result_signature_status": "completed",
            "result_multiset_sha256": "abc",
            "database_result_rows_stored": "false",
        }
    ]
    children = {table: [] for table in module.CHILD_TABLES}
    children["plan_files"] = [
        {"query_run_id": query_run_id, "plan_id": "q-edge:main", "plan_scope": "main"},
        {
            "query_run_id": query_run_id,
            "plan_id": "q-edge:eu",
            "plan_scope": "fdw_auto_explain_remote",
        },
        {
            "query_run_id": query_run_id,
            "plan_id": "q-edge:us",
            "plan_scope": "fdw_auto_explain_remote",
        },
    ]
    children["fdw_remote_plans"] = [
        {
            "query_run_id": query_run_id,
            "plan_id": "q-edge:eu",
            "remote_sql_text": "SELECT 1",
        },
        {
            "query_run_id": query_run_id,
            "plan_id": "q-edge:us",
            "remote_sql_text": "SELECT 1",
        },
    ]
    children["region_fragments"] = [
        {"query_run_id": query_run_id, "remote_plan_id": "q-edge:eu"},
        {"query_run_id": query_run_id, "remote_plan_id": "q-edge:us"},
    ]
    children["remote_edge_observations"] = [
        {
            "query_run_id": query_run_id,
            "edge_id": "eu->gac",
            "availability_status": "available",
        },
        {
            "query_run_id": query_run_id,
            "edge_id": "us->gac",
            "availability_status": "available",
        },
    ]

    quality = module.evidence_quality_rows(executions, children)
    errors, _warnings = module.validate(executions, children, quality)

    assert errors == []
