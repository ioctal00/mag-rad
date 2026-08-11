from __future__ import annotations

import csv
import json
from pathlib import Path

from master_regimes import feature_matrix
from master_regimes.config import write_yaml
from master_regimes.feature_matrix import build_feature_matrix


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_flow_proxy_ratios_keep_zero_final_rows_as_extreme_fanin() -> None:
    row = {
        "remote_region_actual_rows_sum": 20_000_000,
        "remote_region_tuple_bytes_sum": 320_000_000,
        "worker_task_scan_actual_rows_sum": 20_000_000,
        "main_root_actual_rows": 0,
        "temp_blocks_sum": 146_488,
    }

    feature_matrix._add_flow_proxy_features(row)
    feature_matrix._add_topology_normalized_features(row)

    assert row["wan_output_rows"] == 20_000_000
    assert row["global_group_count_proxy"] == 0
    assert row["wan_output_to_final_rows_ratio"] == 20_000_000
    assert row["wan_output_to_client_rows_ratio"] == 20_000_000
    assert row["global_group_merge_ratio"] == 20_000_000
    assert row["regional_input_to_wan_rows_ratio"] == 1
    assert row["temp_blocks_per_final_row"] == 146_488
    assert row["spill_present"] == 0


def test_topology_ratios_fall_back_to_observed_region_task_count() -> None:
    row = {
        "topology_id": "eu_us_gac",
        "worker_task_plan_count": 64,
        "remote_region_task_count_mean": 32,
        "remote_region_observed_count": 2,
    }

    feature_matrix._add_topology_normalized_features(row)

    assert row["configured_shard_count"] == 32
    assert row["task_count_to_shard_count_ratio"] == 2
    assert row["observed_region_shard_slots"] == 64
    assert row["active_task_share"] == 1


def test_topology_ratios_use_observed_n_region_count_over_named_topology() -> None:
    row = {
        "topology_id": "eu_us_gac",
        "worker_task_plan_count": 96,
        "remote_region_task_count_mean": 32,
        "remote_region_observed_count": 3,
    }

    feature_matrix._add_topology_normalized_features(row)

    assert row["configured_region_count"] == 3
    assert row["configured_worker_count_total"] == 6
    assert row["observed_region_shard_slots"] == 96
    assert row["active_task_share"] == 1


def test_semantic_v2_repartition_uses_regional_mapmerge_evidence() -> None:
    row = {
        "citus_repartition_query": "false",
        "remote_citus_repartition_mapmerge_count": "2",
        "remote_citus_plan_locality_classes": "repartition_mapmerge",
    }

    feature_matrix._add_topology_normalized_features(row)

    assert row["citus_repartition_observed_v2"] == 1


def test_semantic_v2_repartition_preserves_main_plan_evidence() -> None:
    row = {
        "citus_repartition_query": "true",
        "remote_citus_repartition_mapmerge_count": "0",
    }

    feature_matrix._add_topology_normalized_features(row)

    assert row["citus_repartition_observed_v2"] == 1


def test_worker_tuple_bytes_distribution_adds_isf() -> None:
    result = feature_matrix._worker_task_aggregates(
        [
            {"tuple_data_received_bytes": "100"},
            {"tuple_data_received_bytes": "300"},
        ]
    )

    assert result["worker_task_tuple_bytes_sum"] == 400
    assert result["worker_task_tuple_bytes_max_share"] == 0.75
    assert result["worker_task_tuple_bytes_isf"] == 1.5


def test_semantic_v2_region_isf_uses_observed_zero_row_region() -> None:
    row = {
        "remote_region_actual_rows_max_share": 1.0,
        "remote_region_nonzero_count": 1,
        "remote_region_actual_rows_imbalance_ratio": 2.0,
        "remote_region_rows_available_count": 2,
    }

    feature_matrix._add_flow_proxy_features(row)

    assert row["remote_region_rows_isf"] == 1.0
    assert row["remote_region_rows_isf_observed"] == 2.0
    assert row["remote_region_rows_isf_normalized"] == 1.0


def test_semantic_v2_worker_scan_distribution_aggregates_by_worker() -> None:
    result = feature_matrix._worker_task_aggregates(
        [
            {
                "worker_node": "worker-a",
                "worker_task_actual_rows": "1",
                "worker_task_scan_actual_rows_sum": "90",
            },
            {
                "worker_node": "worker-b",
                "worker_task_actual_rows": "1",
                "worker_task_scan_actual_rows_sum": "10",
            },
        ]
    )

    assert result["worker_task_actual_rows_cv"] == 0
    assert result["worker_scan_rows_sum"] == 100
    assert result["worker_scan_rows_worker_count"] == 2
    assert result["worker_scan_rows_cv"] == 0.8
    assert result["worker_scan_rows_cv_normalized"] == 0.8
    assert result["worker_scan_rows_isf"] == 1.8
    assert result["worker_scan_rows_isf_normalized"] == 0.8


def test_remote_region_aggregates_add_citus_locality_audit() -> None:
    result = feature_matrix._remote_region_aggregates(
        [
            {
                "region_id": "eu",
                "remote_citus_tasks_shown_none": "true",
                "remote_citus_task_list_available": "false",
                "remote_citus_tuple_bytes_supported": "false",
                "remote_citus_map_merge_job_count": "2",
                "remote_citus_dependent_map_task_count_sum": "64",
                "remote_citus_dependent_merge_task_count_sum": "24",
                "remote_citus_repartition_fanout_ratio": str(64 / 12),
                "remote_citus_repartition_mapmerge": "true",
                "remote_citus_plan_locality_class": "repartition_mapmerge",
            }
        ],
        expected_regions=["eu"],
    )

    assert result["remote_citus_tasks_shown_none_count"] == 1
    assert result["remote_citus_task_list_available_count"] == 0
    assert result["remote_citus_tuple_bytes_unsupported_count"] == 1
    assert result["remote_citus_map_merge_job_count_sum"] == 2
    assert result["remote_citus_dependent_map_task_count_sum"] == 64
    assert result["remote_citus_dependent_merge_task_count_sum"] == 24
    assert result["remote_citus_repartition_fanout_ratio_max"] == 64 / 12
    assert result["remote_citus_repartition_mapmerge_count"] == 1
    assert result["remote_citus_dominant_plan_locality_class"] == "repartition_mapmerge"


def test_hash_batches_default_to_neutral_one_when_no_hash_batch_field() -> None:
    aggregates = feature_matrix._plan_node_aggregates(
        [
            {
                "query_run_id": "q1",
                "plan_scope": "main",
                "node_id": "0",
                "parent_node_id": "",
                "node_type": "Foreign Scan",
                "actual_rows": "100",
                "actual_total_time_ms": "10",
            }
        ]
    )

    assert aggregates["hash_batches_max"] == 1.0


def test_pushdown_fidelity_detects_local_filter_and_gac_finalization(tmp_path: Path) -> None:
    index_dir = tmp_path / "_index"
    index_dir.mkdir()
    main_plan_path = tmp_path / "main.explain.json"
    main_plan_path.write_text(
        json.dumps(
            [
                {
                    "Plan": {
                        "Node Type": "Sort",
                        "Actual Rows": 2,
                        "Plan Rows": 199,
                        "Plan Width": 48,
                        "Plans": [
                            {
                                "Node Type": "Aggregate",
                                "Plans": [
                                    {
                                        "Node Type": "Append",
                                        "Plans": [
                                            {
                                                "Node Type": "Foreign Scan",
                                                "Relation Name": "events",
                                                "Filter": (
                                                    "(events.created_at >= "
                                                    "(now() - '1 day'::interval))"
                                                ),
                                                "Remote SQL": (
                                                    "SELECT value, created_at FROM public.events"
                                                ),
                                                "Async Capable": False,
                                            },
                                            {
                                                "Node Type": "Foreign Scan",
                                                "Relation Name": "events",
                                                "Filter": (
                                                    "(events_1.created_at >= "
                                                    "(now() - '1 day'::interval))"
                                                ),
                                                "Remote SQL": (
                                                    "SELECT value, created_at FROM public.events"
                                                ),
                                                "Async Capable": False,
                                            },
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                }
            ]
        ),
        encoding="utf-8",
    )
    plan_nodes = [
        {
            "query_run_id": "q1",
            "plan_scope": "main",
            "plan_json_file": "main.explain.json",
            "node_id": "1",
            "parent_node_id": "",
            "node_type": "Sort",
            "actual_rows": "2",
            "actual_loops": "1",
            "actual_total_time": "100",
            "plan_rows": "199",
            "plan_width": "48",
            "temp_read_blocks": "0",
            "temp_written_blocks": "0",
        },
        {
            "query_run_id": "q1",
            "plan_scope": "main",
            "plan_json_file": "main.explain.json",
            "node_id": "2",
            "parent_node_id": "1",
            "node_type": "Aggregate",
            "actual_rows": "2",
            "actual_loops": "1",
            "plan_rows": "199",
            "plan_width": "48",
            "temp_read_blocks": "0",
            "temp_written_blocks": "0",
        },
        {
            "query_run_id": "q1",
            "plan_scope": "main",
            "plan_json_file": "main.explain.json",
            "node_id": "3",
            "parent_node_id": "2",
            "node_type": "Append",
            "actual_rows": "67553",
            "actual_loops": "1",
            "plan_rows": "854",
            "plan_width": "40",
            "temp_read_blocks": "0",
            "temp_written_blocks": "0",
        },
        {
            "query_run_id": "q1",
            "plan_scope": "main",
            "plan_json_file": "main.explain.json",
            "node_id": "4",
            "parent_node_id": "3",
            "node_type": "Foreign Scan",
            "actual_rows": "33625",
            "actual_loops": "1",
            "plan_rows": "427",
            "plan_width": "40",
            "temp_read_blocks": "0",
            "temp_written_blocks": "0",
        },
        {
            "query_run_id": "q1",
            "plan_scope": "main",
            "plan_json_file": "main.explain.json",
            "node_id": "5",
            "parent_node_id": "3",
            "node_type": "Foreign Scan",
            "actual_rows": "33928",
            "actual_loops": "1",
            "plan_rows": "427",
            "plan_width": "40",
            "temp_read_blocks": "0",
            "temp_written_blocks": "0",
        },
        {
            "query_run_id": "q1",
            "plan_scope": "fdw_auto_explain_remote",
            "node_id": "6",
            "parent_node_id": "",
            "node_type": "Custom Scan",
            "actual_rows": "10000000",
            "actual_loops": "1",
            "plan_rows": "100000",
            "plan_width": "16",
            "temp_read_blocks": "36622",
            "temp_written_blocks": "36622",
        },
        {
            "query_run_id": "q1",
            "plan_scope": "fdw_auto_explain_remote",
            "node_id": "7",
            "parent_node_id": "",
            "node_type": "Custom Scan",
            "actual_rows": "10000000",
            "actual_loops": "1",
            "plan_rows": "100000",
            "plan_width": "16",
            "temp_read_blocks": "36622",
            "temp_written_blocks": "36622",
        },
    ]

    row = feature_matrix._plan_node_aggregates(plan_nodes, index_dir=index_dir)
    feature_matrix._add_flow_proxy_features(row)
    feature_matrix._add_topology_normalized_features(row)

    assert row["fdw_local_filter_after_remote_flag"] == 1
    assert row["fdw_local_filter_after_remote_count"] == 2
    assert row["remote_sql_where_present_count"] == 0
    assert row["aggregate_pushdown_missed_flag"] == 1
    assert row["sort_pushdown_missed_flag"] == 1
    assert row["serial_remote_region_scan_count"] == 2
    assert row["projection_width_expansion_ratio"] == 2.5
    assert row["remote_spill_blocks_sum"] == 146488.0
    assert row["main_spill_blocks_sum"] == 0.0
    assert round(row["remote_to_foreign_scan_rows_ratio"], 3) == 296.064
    assert row["foreign_scan_to_final_rows_ratio"] == 33776.5
    assert row["fdw_pushdown_fidelity_contract"] == "fdw_pushdown_fidelity_v1"
    assert row["pushdown_fidelity_component_count"] == 4
    assert row["pushdown_fidelity_evidence_status"] == "available"
    assert row["pushdown_miss_reason_codes"] == (
        "local_filter_after_remote,"
        "aggregate_not_pushdowned,"
        "sort_not_pushdowned,"
        "projection_width_expansion"
    )
    assert round(row["pushdown_fidelity_score"], 3) == 0.1
    assert round(row["pushdown_miss_score"], 3) == 0.9


def test_pushdown_fidelity_resolves_logical_index_plan_paths(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus-sweeps"
    logical_index_dir = corpus_root / "_logical-runs" / "run-1" / "_index"
    query_sweep_dir = (
        corpus_root
        / "attempt-1"
        / "database-sweeps"
        / "db-1"
        / "query-sweeps"
        / "qs-1"
    )
    plan_path = query_sweep_dir / "query-collections" / "q1" / "plans" / "main.json"
    plan_path.parent.mkdir(parents=True)
    logical_index_dir.mkdir(parents=True)
    plan_path.write_text(
        json.dumps(
            [
                {
                    "Plan": {
                        "Node Type": "Aggregate",
                        "Plans": [
                            {
                                "Node Type": "Foreign Scan",
                                "Filter": "(events.tenant_id = 1)",
                                "Remote SQL": "SELECT tenant_id FROM public.events",
                            }
                        ],
                    }
                }
            ]
        ),
        encoding="utf-8",
    )

    row = feature_matrix._plan_node_aggregates(
        [
            {
                "query_run_id": "q1",
                "query_sweep_dir": "query-sweeps/qs-1",
                "plan_scope": "main",
                "plan_json_file": "query-collections/q1/plans/main.json",
                "node_type": "Aggregate",
                "actual_rows": "1",
                "plan_rows": "1",
            }
        ],
        index_dir=logical_index_dir,
    )

    assert row["fdw_foreign_scan_count"] == 1
    assert row["fdw_local_filter_after_remote_flag"] == 1
    assert row["aggregate_pushdown_missed_flag"] == 1


def test_worker_task_aggregates_tuple_byte_distribution() -> None:
    row = feature_matrix._worker_task_aggregates(
        [
            {
                "fdw_region": "eu",
                "tuple_data_received_bytes": "100",
                "worker_task_scan_actual_rows_sum": "10",
            },
            {
                "fdw_region": "eu",
                "tuple_data_received_bytes": "300",
                "worker_task_scan_actual_rows_sum": "30",
            },
            {
                "fdw_region": "us",
                "tuple_data_received_bytes": "600",
                "worker_task_scan_actual_rows_sum": "60",
            },
        ]
    )

    assert row["worker_task_tuple_bytes_sum"] == 1000.0
    assert row["worker_task_tuple_bytes_min"] == 100.0
    assert row["worker_task_tuple_bytes_max"] == 600.0
    assert row["worker_task_tuple_bytes_max_share"] == 0.6
    assert round(row["worker_task_tuple_bytes_cv"], 3) == 0.616


def test_build_feature_matrix_materializes_m0_m1_and_context(tmp_path: Path) -> None:
    index_dir = tmp_path / "_index"
    schema_path = index_dir / "feature_schema.yml"
    write_yaml(
        schema_path,
        {
            "schema_version": 1,
            "columns": [
                {
                    "name": "execution_time_seconds",
                    "source_column": "elapsed_seconds",
                    "source_table": "query_runs",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": None,
                    "requires_topology": "eu_only",
                    "null_policy": "missing_means_timing_not_collected",
                },
                {
                    "name": "has_foreign_scan",
                    "source_column": "main_has_foreign_scan",
                    "source_table": "query_runs",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": None,
                    "requires_topology": "eu_only",
                    "null_policy": "missing_means_main_plan_parse_failed",
                },
                {
                    "name": "main_plan_max_depth",
                    "source_table": "plan_structure_features",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": False,
                    "structural_feature": True,
                    "proxy_of": None,
                    "requires_topology": "eu_only",
                    "null_policy": "missing_means_plan_parse_failed",
                },
                {
                    "name": "worker_task_plan_count",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "parsed_worker_task_plan_count",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_worker_task_plan_summary_not_enabled",
                },
                {
                    "name": "worker_task_actual_rows_cv",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_row_imbalance",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_worker_task_rows_not_parsed",
                },
                {
                    "name": "worker_task_scan_actual_rows_cv",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_scan_row_imbalance",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_worker_task_scan_rows_not_parsed",
                },
                {
                    "name": "worker_task_scan_actual_rows_max_share",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_scan_row_imbalance",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_worker_task_scan_rows_not_parsed",
                },
                {
                    "name": "worker_task_seq_scan_share",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_scan_strategy",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_worker_task_scan_types_not_parsed",
                },
                {
                    "name": "worker_task_join_node_count",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_operator_class_count",
                    "requires_topology": "multi_region",
                    "null_policy": "zero_is_valid_after_worker_task_parse",
                },
                {
                    "name": "worker_task_blocking_node_count",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_operator_class_count",
                    "requires_topology": "multi_region",
                    "null_policy": "zero_is_valid_after_worker_task_parse",
                },
                {
                    "name": "worker_task_plan_fingerprint_count",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_plan_diversity",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_worker_task_plan_fingerprint_not_parsed",
                },
                {
                    "name": "remote_region_count",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "expected_remote_region_count",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_plan",
                },
                {
                    "name": "remote_region_observed_count",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "observed_remote_region_count",
                    "requires_topology": "multi_region",
                    "null_policy": "zero_is_valid_when_no_remote_region_plan",
                },
                {
                    "name": "remote_region_missing_count",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "expected_minus_observed_remote_regions",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_plan",
                },
                {
                    "name": "remote_region_evidence_completeness",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "observed_remote_regions_over_expected_regions",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_plan",
                },
                {
                    "name": "remote_region_actual_rows_sum",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "regional_remote_output_rows",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_rows",
                },
                {
                    "name": "remote_region_actual_rows_max_share",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "regional_remote_output_row_imbalance",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_rows",
                },
                {
                    "name": "remote_region_actual_rows_min_max_ratio",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "regional_remote_output_row_balance",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_rows",
                },
                {
                    "name": "remote_region_actual_rows_active_share",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "regional_remote_output_active_region_share",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_rows",
                },
                {
                    "name": "remote_region_tuple_bytes_max_share",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "regional_remote_tuple_bytes_imbalance",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_tuple_bytes",
                },
                {
                    "name": "remote_region_tuple_bytes_min_max_ratio",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "regional_remote_tuple_bytes_balance",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_tuple_bytes",
                },
                {
                    "name": "remote_region_plan_fingerprint_count",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "regional_remote_plan_diversity",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_plan_fingerprint",
                },
                {
                    "name": "remote_region_dominant_plan_fingerprint_share",
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "regional_remote_plan_diversity",
                    "requires_topology": "multi_region",
                    "null_policy": "missing_means_no_remote_region_plan_fingerprint",
                },
                {
                    "name": "first_blocking_operator_type",
                    "source_table": "plan_structure_features",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": False,
                    "structural_feature": True,
                    "proxy_of": None,
                    "requires_topology": "eu_only",
                    "null_policy": "missing_means_no_blocking_operator",
                },
                {
                    "name": "template_id",
                    "source_table": "query_runs",
                    "feature_scope": "template",
                    "feature_reliability": "A",
                    "model_role": "context",
                    "included_in_default_model": False,
                    "proxy_of": None,
                    "requires_topology": "eu_only",
                    "null_policy": "missing_context",
                },
            ],
            "column_patterns": [
                {
                    "pattern": "main_node_type_count_*",
                    "source_table": "plan_nodes",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": None,
                    "requires_topology": "eu_only",
                    "null_policy": "missing_node_type_count_means_zero_after_plan_parse",
                },
                {
                    "pattern": "parent_child_type_count_*",
                    "source_table": "plan_structure_features",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": False,
                    "structural_feature": True,
                    "proxy_of": "plan_parent_child_transition_count",
                    "requires_topology": "eu_only",
                    "null_policy": "missing_transition_count_means_zero_after_plan_parse",
                },
                {
                    "pattern": "worker_node_count_*",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_node_type_histogram",
                    "requires_topology": "multi_region",
                    "null_policy": "zero_is_valid_after_worker_task_parse",
                },
            ],
        },
    )
    _write_csv(
        index_dir / "execution_features.csv",
        [
            {
                "condition_id": "condition-1",
                "query_run_id": "q1",
                "template_id": "t1",
                "elapsed_seconds": "0.1",
                "main_has_foreign_scan": "true",
            },
            {
                "condition_id": "condition-2",
                "query_run_id": "q2",
                "template_id": "t2",
                "elapsed_seconds": "0.2",
                "main_has_foreign_scan": "false",
            },
        ],
        [
            "condition_id",
            "query_run_id",
            "template_id",
            "elapsed_seconds",
            "main_has_foreign_scan",
        ],
    )
    _write_csv(
        index_dir / "plan_nodes.csv",
        [
            {
                "query_run_id": "q1",
                "plan_scope": "main",
                "node_id": "1",
                "depth": "0",
                "node_path": "0",
                "node_type": "Limit",
            },
            {
                "query_run_id": "q2",
                "plan_scope": "main",
                "node_id": "1",
                "depth": "0",
                "node_path": "0",
                "node_type": "Aggregate",
            },
        ],
        ["query_run_id", "plan_scope", "node_id", "depth", "node_path", "node_type"],
    )
    _write_csv(
        index_dir / "plan_structure_features.csv",
        [
            {
                "query_run_id": "q1",
                "main_plan_node_count": "1",
                "main_plan_max_depth": "0",
                "first_blocking_operator_type": "Limit",
                "parent_child_type_count_Limit_Sort": "1",
            },
            {
                "query_run_id": "q2",
                "main_plan_node_count": "1",
                "main_plan_max_depth": "0",
                "first_blocking_operator_type": "Aggregate",
            },
        ],
        [
            "query_run_id",
            "main_plan_node_count",
            "main_plan_max_depth",
            "first_blocking_operator_type",
            "parent_child_type_count_Limit_Sort",
        ],
    )
    _write_csv(
        index_dir / "region_fragments.csv",
        [
            {
                "query_run_id": "q1",
                "region_id": "eu",
                "remote_actual_rows": "10",
                "remote_tuple_bytes_proxy": "100",
                "remote_plan_fingerprint": "eu-scan",
                "parse_status": "ok",
            },
            {
                "query_run_id": "q1",
                "region_id": "eu",
                "remote_actual_rows": "30",
                "remote_tuple_bytes_proxy": "300",
                "remote_plan_fingerprint": "eu-join",
                "parse_status": "ok",
            },
            {
                "query_run_id": "q1",
                "region_id": "us",
                "remote_actual_rows": "10",
                "remote_tuple_bytes_proxy": "100",
                "remote_plan_fingerprint": "eu-scan",
                "parse_status": "ok",
            },
        ],
        [
            "query_run_id",
            "region_id",
            "remote_actual_rows",
            "remote_tuple_bytes_proxy",
            "remote_plan_fingerprint",
            "parse_status",
        ],
    )
    _write_csv(
        index_dir / "worker_task_fragments.csv",
        [
            {
                "query_run_id": "q1",
                "fdw_region": "eu",
                "worker_task_actual_rows": "10",
                "worker_task_scan_actual_rows_sum": "100",
                "worker_task_scan_type_counts_json": '{"seq_scan":1}',
                "worker_task_node_type_counts_json": '{"Seq Scan":1,"Hash Join":1}',
                "worker_task_plan_fingerprint": "p1",
            },
            {
                "query_run_id": "q1",
                "fdw_region": "eu",
                "worker_task_actual_rows": "30",
                "worker_task_scan_actual_rows_sum": "300",
                "worker_task_scan_type_counts_json": '{"index_scan":1}',
                "worker_task_node_type_counts_json": (
                    '{"Index Scan":1,"Materialize":1,"Function Scan":1}'
                ),
                "worker_task_plan_fingerprint": "p2",
            },
        ],
        [
            "query_run_id",
            "fdw_region",
            "worker_task_actual_rows",
            "worker_task_scan_actual_rows_sum",
            "worker_task_scan_type_counts_json",
            "worker_task_node_type_counts_json",
            "worker_task_plan_fingerprint",
        ],
    )
    out_dir = build_feature_matrix(index_dir=index_dir, topology="multi_region")

    all_features = _read_csv(out_dir / "execution_features_all.csv")
    m0 = _read_csv(out_dir / "execution_features_m0.csv")
    m1 = _read_csv(out_dir / "execution_features_m1.csv")
    context = _read_csv(out_dir / "model_context.csv")
    expansions = _read_csv(out_dir / "categorical_expansions.csv")

    assert [row["query_run_id"] for row in m0] == ["q1", "q2"]
    assert [row["query_run_id"] for row in all_features] == ["q1", "q2"]
    assert [row["condition_id"] for row in context] == [
        "condition-1",
        "condition-2",
    ]
    assert "main_plan_max_depth" not in m0[0]
    assert m0[0]["has_foreign_scan"] == "1"
    assert m0[1]["has_foreign_scan"] == "0"
    assert float(m0[0]["main_node_type_count_Limit"]) == 1
    assert float(m0[1]["main_node_type_count_Limit"]) == 0
    assert float(m0[0]["worker_task_plan_count"]) == 2
    assert float(m0[0]["worker_task_actual_rows_cv"]) == 0.5
    assert float(m0[0]["worker_task_scan_actual_rows_cv"]) == 0.5
    assert float(m0[0]["worker_task_scan_actual_rows_max_share"]) == 0.75
    assert float(m0[0]["worker_task_seq_scan_share"]) == 0.5
    assert float(m0[0]["worker_task_join_node_count"]) == 1
    assert float(m0[0]["worker_task_blocking_node_count"]) == 1
    assert float(m0[0]["worker_node_count_seq_scan"]) == 1
    assert float(m0[0]["worker_node_count_index_scan"]) == 1
    assert float(m0[0]["worker_node_count_hash_join"]) == 1
    assert float(m0[0]["worker_node_count_materialize"]) == 1
    assert float(m0[0]["worker_node_count_other"]) == 1
    assert float(m0[0]["worker_task_plan_fingerprint_count"]) == 2
    assert float(m0[0]["remote_region_observed_count"]) == 2
    assert float(m0[0]["remote_region_count"]) == 2
    assert float(m0[0]["remote_region_missing_count"]) == 0
    assert float(m0[0]["remote_region_evidence_completeness"]) == 1.0
    assert float(m0[0]["remote_region_actual_rows_sum"]) == 50
    assert float(m0[0]["remote_region_actual_rows_max_share"]) == 0.8
    assert float(m0[0]["remote_region_actual_rows_min_max_ratio"]) == 0.25
    assert float(m0[0]["remote_region_actual_rows_active_share"]) == 1.0
    assert float(m0[0]["remote_region_tuple_bytes_max_share"]) == 0.8
    assert float(m0[0]["remote_region_tuple_bytes_min_max_ratio"]) == 0.25
    assert float(m0[0]["remote_region_plan_fingerprint_count"]) == 2
    assert float(m0[0]["remote_region_dominant_plan_fingerprint_share"]) == 0.5
    assert m0[1]["worker_task_plan_count"] == ""
    assert m0[1]["remote_region_observed_count"] == ""
    assert "main_plan_max_depth" in m1[0]
    assert float(m1[0]["parent_child_type_count_Limit_Sort"]) == 1
    assert float(m1[1]["parent_child_type_count_Limit_Sort"]) == 0
    assert "first_blocking_operator_type__limit" in m1[0]
    assert any(
        row["source_feature"] == "first_blocking_operator_type"
        and row["category"] == "Limit"
        for row in expansions
    )
    assert context[0]["template_id"] == "t1"
    assert "template_id" not in m0[0]


def test_build_feature_matrix_aggregates_remote_regions_by_expected_region(
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "_index"
    feature_names = [
        "remote_region_count",
        "remote_region_observed_count",
        "remote_region_missing_count",
        "remote_region_evidence_completeness",
        "remote_region_parse_success_count",
        "remote_region_rows_available_count",
        "remote_region_time_available_count",
        "remote_region_actual_rows_sum",
        "remote_region_actual_rows_max_share",
        "remote_region_actual_rows_imbalance_ratio",
        "remote_region_actual_rows_min_max_ratio",
        "remote_region_actual_rows_active_share",
        "remote_region_actual_time_sum",
        "remote_region_actual_time_max_share",
        "remote_region_tuple_bytes_sum",
        "remote_region_tuple_bytes_max_share",
        "remote_region_task_count_sum",
        "remote_region_task_count_max_share",
        "remote_region_plan_fingerprint_count",
        "remote_region_dominant_plan_fingerprint_share",
    ]
    write_yaml(
        index_dir / "feature_schema.yml",
        {
            "schema_version": 1,
            "columns": [
                {
                    "name": name,
                    "source_table": "region_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "A",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "remote_region_summary_test",
                    "requires_topology": "multi_region",
                    "null_policy": "test",
                }
                for name in feature_names
            ],
        },
    )
    _write_csv(
        index_dir / "execution_features.csv",
        [
            {
                "query_run_id": "q-missing-us",
                "template_id": "t-multiregion",
                "fdw_auto_explain_regions": "eu,us",
            },
            {
                "query_run_id": "q-two-regions",
                "template_id": "t-multiregion",
                "fdw_auto_explain_regions": '["eu","us"]',
            },
            {
                "query_run_id": "q-no-fragments",
                "template_id": "t-multiregion",
                "fdw_auto_explain_regions": "eu,us",
            },
        ],
        ["query_run_id", "template_id", "fdw_auto_explain_regions"],
    )
    _write_csv(
        index_dir / "region_fragments.csv",
        [
            {
                "query_run_id": "q-missing-us",
                "region_id": "eu",
                "parse_status": "ok",
                "remote_actual_rows": "100",
                "remote_actual_total_time_ms": "20",
                "remote_tuple_bytes_proxy": "1000",
                "remote_citus_task_count": "32",
                "remote_plan_fingerprint": "eu-a",
            },
            {
                "query_run_id": "q-two-regions",
                "region_id": "eu",
                "parse_status": "ok",
                "remote_actual_rows": "40",
                "remote_actual_total_time_ms": "4",
                "remote_tuple_bytes_proxy": "400",
                "remote_citus_task_count": "16",
                "remote_plan_fingerprint": "eu-a",
            },
            {
                "query_run_id": "q-two-regions",
                "region_id": "eu",
                "parse_status": "ok",
                "remote_actual_rows": "60",
                "remote_actual_total_time_ms": "6",
                "remote_tuple_bytes_proxy": "600",
                "remote_citus_task_count": "16",
                "remote_plan_fingerprint": "eu-b",
            },
            {
                "query_run_id": "q-two-regions",
                "region_id": "us",
                "parse_status": "ok",
                "remote_actual_rows": "100",
                "remote_actual_total_time_ms": "30",
                "remote_tuple_bytes_proxy": "3000",
                "remote_citus_task_count": "32",
                "remote_plan_fingerprint": "us-a",
            },
        ],
        [
            "query_run_id",
            "region_id",
            "parse_status",
            "remote_actual_rows",
            "remote_actual_total_time_ms",
            "remote_tuple_bytes_proxy",
            "remote_citus_task_count",
            "remote_plan_fingerprint",
        ],
    )

    out_dir = build_feature_matrix(index_dir=index_dir, topology="multi_region")
    rows = {row["query_run_id"]: row for row in _read_csv(out_dir / "execution_features_m0.csv")}

    missing = rows["q-missing-us"]
    assert float(missing["remote_region_count"]) == 2
    assert float(missing["remote_region_observed_count"]) == 1
    assert float(missing["remote_region_missing_count"]) == 1
    assert float(missing["remote_region_evidence_completeness"]) == 0.5
    assert float(missing["remote_region_actual_rows_max_share"]) == 1.0

    no_fragments = rows["q-no-fragments"]
    assert float(no_fragments["remote_region_count"]) == 2
    assert float(no_fragments["remote_region_observed_count"]) == 0
    assert float(no_fragments["remote_region_missing_count"]) == 2
    assert float(no_fragments["remote_region_evidence_completeness"]) == 0.0

    complete = rows["q-two-regions"]
    assert float(complete["remote_region_count"]) == 2
    assert float(complete["remote_region_observed_count"]) == 2
    assert float(complete["remote_region_missing_count"]) == 0
    assert float(complete["remote_region_evidence_completeness"]) == 1.0
    assert float(complete["remote_region_parse_success_count"]) == 3
    assert float(complete["remote_region_rows_available_count"]) == 2
    assert float(complete["remote_region_time_available_count"]) == 2
    assert float(complete["remote_region_actual_rows_sum"]) == 200
    assert float(complete["remote_region_actual_rows_max_share"]) == 0.5
    assert float(complete["remote_region_actual_rows_imbalance_ratio"]) == 1.0
    assert float(complete["remote_region_actual_rows_min_max_ratio"]) == 1.0
    assert float(complete["remote_region_actual_rows_active_share"]) == 1.0
    assert float(complete["remote_region_actual_time_sum"]) == 40
    assert float(complete["remote_region_actual_time_max_share"]) == 0.75
    assert float(complete["remote_region_tuple_bytes_sum"]) == 4000
    assert float(complete["remote_region_tuple_bytes_max_share"]) == 0.75
    assert float(complete["remote_region_task_count_sum"]) == 64
    assert float(complete["remote_region_task_count_max_share"]) == 0.5
    assert float(complete["remote_region_plan_fingerprint_count"]) == 2
    assert float(complete["remote_region_dominant_plan_fingerprint_share"]) == 0.5


def test_build_feature_matrix_summarizes_worker_task_deep_evidence(tmp_path: Path) -> None:
    index_dir = tmp_path / "_index"
    _write_csv(
        index_dir / "query_runs.csv",
        [
            {
                "query_run_id": "q-worker",
                "instance_id": "i-worker",
                "template_id": "t-worker",
                "execution_status": "completed",
            }
        ],
        ["query_run_id", "instance_id", "template_id", "execution_status"],
    )
    _write_csv(
        index_dir / "worker_task_fragments.csv",
        [
            {
                "query_run_id": "q-worker",
                "fdw_region": "eu",
                "worker_task_actual_rows": "10",
                "worker_task_scan_actual_rows_sum": "100",
                "worker_task_actual_time_ms": "5",
                "worker_task_scan_type_counts_json": '{"seq_scan":1}',
                "worker_task_node_type_counts_json": '{"Seq Scan":1,"HashAggregate":1}',
                "worker_task_node_type_unknown_count": "0",
                "worker_task_node_type_unknown_set_json": "[]",
                "worker_task_node_count": "2",
                "worker_task_plan_max_depth": "1",
                "worker_task_spill_count": "1",
                "worker_task_shared_hit_blocks": "14",
                "worker_task_shared_read_blocks": "4",
                "worker_task_temp_read_blocks": "1",
                "worker_task_temp_written_blocks": "2",
                "worker_task_plan_fingerprint": "fp-eu-1",
            },
            {
                "query_run_id": "q-worker",
                "fdw_region": "eu",
                "worker_task_actual_rows": "30",
                "worker_task_scan_actual_rows_sum": "300",
                "worker_task_actual_time_ms": "15",
                "worker_task_scan_type_counts_json": '{"bitmap_scan":1}',
                "worker_task_node_type_counts_json": (
                    '{"Bitmap Heap Scan":1,"Bitmap Index Scan":1,"Sort":1}'
                ),
                "worker_task_node_type_unknown_count": "1",
                "worker_task_node_type_unknown_set_json": '["Future Scan"]',
                "worker_task_node_count": "3",
                "worker_task_plan_max_depth": "2",
                "worker_task_spill_count": "0",
                "worker_task_shared_hit_blocks": "16",
                "worker_task_shared_read_blocks": "6",
                "worker_task_temp_read_blocks": "0",
                "worker_task_temp_written_blocks": "0",
                "worker_task_plan_fingerprint": "fp-eu-2",
            },
            {
                "query_run_id": "q-worker",
                "fdw_region": "us",
                "worker_task_actual_rows": "60",
                "worker_task_scan_actual_rows_sum": "600",
                "worker_task_actual_time_ms": "30",
                "worker_task_scan_type_counts_json": '{"index_scan":1}',
                "worker_task_node_type_counts_json": (
                    '{"Index Scan":1,"Hash Join":1,"Materialize":1}'
                ),
                "worker_task_node_type_unknown_count": "0",
                "worker_task_node_type_unknown_set_json": "[]",
                "worker_task_node_count": "3",
                "worker_task_plan_max_depth": "2",
                "worker_task_spill_count": "0",
                "worker_task_shared_hit_blocks": "22",
                "worker_task_shared_read_blocks": "8",
                "worker_task_temp_read_blocks": "2",
                "worker_task_temp_written_blocks": "3",
                "worker_task_plan_fingerprint": "fp-us-1",
            },
            {
                "query_run_id": "q-worker",
                "fdw_region": "us",
                "worker_task_actual_rows": "100",
                "worker_task_scan_actual_rows_sum": "1000",
                "worker_task_actual_time_ms": "50",
                "worker_task_scan_type_counts_json": '{"index_scan":1}',
                "worker_task_node_type_counts_json": '{"Index Scan":1,"Function Scan":1}',
                "worker_task_node_type_unknown_count": "0",
                "worker_task_node_type_unknown_set_json": "[]",
                "worker_task_node_count": "2",
                "worker_task_plan_max_depth": "1",
                "worker_task_spill_count": "0",
                "worker_task_shared_hit_blocks": "8",
                "worker_task_shared_read_blocks": "2",
                "worker_task_temp_read_blocks": "0",
                "worker_task_temp_written_blocks": "0",
                "worker_task_plan_fingerprint": "fp-us-1",
            },
        ],
        [
            "query_run_id",
            "fdw_region",
            "worker_task_actual_rows",
            "worker_task_scan_actual_rows_sum",
            "worker_task_actual_time_ms",
            "worker_task_scan_type_counts_json",
            "worker_task_node_type_counts_json",
            "worker_task_node_type_unknown_count",
            "worker_task_node_type_unknown_set_json",
            "worker_task_node_count",
            "worker_task_plan_max_depth",
            "worker_task_spill_count",
            "worker_task_shared_hit_blocks",
            "worker_task_shared_read_blocks",
            "worker_task_temp_read_blocks",
            "worker_task_temp_written_blocks",
            "worker_task_plan_fingerprint",
        ],
    )
    input_features = [
        "worker_task_plan_count",
        "worker_task_actual_rows_sum",
        "worker_task_actual_rows_max_share",
        "worker_task_scan_actual_rows_sum",
        "worker_task_scan_actual_rows_max_share",
        "worker_task_actual_time_sum",
        "worker_task_actual_time_max_share",
        "worker_task_seq_scan_share",
        "worker_task_index_scan_share",
        "worker_task_bitmap_scan_share",
        "worker_task_node_count_sum",
        "worker_task_plan_max_depth_max",
        "worker_task_plan_max_depth_mean",
        "worker_task_join_node_count",
        "worker_task_aggregate_node_count",
        "worker_task_sort_node_count",
        "worker_task_blocking_node_count",
        "worker_task_scan_node_count",
        "worker_task_materialization_node_count",
        "worker_task_bitmap_node_count",
        "worker_task_index_access_node_count",
        "worker_task_sequential_access_node_count",
        "worker_task_spill_capable_node_count",
        "worker_task_plan_fingerprint_count",
        "worker_task_plan_fingerprint_dominant_share",
        "worker_task_spill_count",
        "worker_task_shared_hit_sum",
        "worker_task_shared_read_sum",
        "worker_task_temp_read_sum",
        "worker_task_temp_written_sum",
        "worker_task_region_count",
        "worker_task_region_task_count_cv",
        "worker_task_region_rows_max_share",
        "worker_task_region_scan_rows_max_share",
        "worker_task_within_region_plan_fingerprint_count_max",
        "worker_task_within_region_scan_rows_cv_max",
        "worker_task_within_region_scan_rows_max_share_max",
    ]
    audit_features = [
        "worker_task_node_type_counts_json",
        "worker_task_node_type_unknown_count",
        "worker_task_node_type_unknown_set_json",
    ]
    write_yaml(
        index_dir / "feature_schema.yml",
        {
            "schema_version": 1,
            "columns": [
                {
                    "name": name,
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_summary_test",
                    "requires_topology": "multi_region",
                    "null_policy": "test",
                }
                for name in input_features
            ]
            + [
                {
                    "name": name,
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "audit",
                    "included_in_default_model": False,
                    "proxy_of": "worker_task_summary_test",
                    "requires_topology": "multi_region",
                    "null_policy": "test",
                }
                for name in audit_features
            ],
            "column_patterns": [
                {
                    "pattern": "worker_node_count_*",
                    "source_table": "worker_task_fragments",
                    "feature_scope": "execution",
                    "feature_reliability": "B",
                    "model_role": "input",
                    "included_in_default_model": True,
                    "proxy_of": "worker_task_operator_histogram_test",
                    "requires_topology": "multi_region",
                    "null_policy": "test",
                }
            ],
        },
    )

    out_dir = build_feature_matrix(index_dir=index_dir, topology="multi_region")
    m0 = _read_csv(out_dir / "execution_features_m0.csv")
    context = _read_csv(out_dir / "model_context.csv")

    assert len(m0) == 1
    row = m0[0]
    assert row["query_run_id"] == "q-worker"
    assert float(row["worker_task_plan_count"]) == 4
    assert float(row["worker_task_actual_rows_sum"]) == 200
    assert float(row["worker_task_actual_rows_max_share"]) == 0.5
    assert float(row["worker_task_scan_actual_rows_sum"]) == 2000
    assert float(row["worker_task_scan_actual_rows_max_share"]) == 0.5
    assert float(row["worker_task_actual_time_sum"]) == 100
    assert float(row["worker_task_actual_time_max_share"]) == 0.5
    assert float(row["worker_task_seq_scan_share"]) == 0.25
    assert float(row["worker_task_index_scan_share"]) == 0.5
    assert float(row["worker_task_bitmap_scan_share"]) == 0.25
    assert float(row["worker_task_node_count_sum"]) == 10
    assert float(row["worker_task_plan_max_depth_max"]) == 2
    assert float(row["worker_task_plan_max_depth_mean"]) == 1.5
    assert float(row["worker_task_join_node_count"]) == 1
    assert float(row["worker_task_aggregate_node_count"]) == 1
    assert float(row["worker_task_sort_node_count"]) == 1
    assert float(row["worker_task_blocking_node_count"]) == 3
    assert float(row["worker_task_scan_node_count"]) == 6
    assert float(row["worker_task_materialization_node_count"]) == 1
    assert float(row["worker_task_bitmap_node_count"]) == 2
    assert float(row["worker_task_index_access_node_count"]) == 3
    assert float(row["worker_task_sequential_access_node_count"]) == 1
    assert float(row["worker_task_spill_capable_node_count"]) == 4
    assert float(row["worker_task_plan_fingerprint_count"]) == 3
    assert float(row["worker_task_plan_fingerprint_dominant_share"]) == 0.5
    assert float(row["worker_task_spill_count"]) == 1
    assert float(row["worker_task_shared_hit_sum"]) == 60
    assert float(row["worker_task_shared_read_sum"]) == 20
    assert float(row["worker_task_temp_read_sum"]) == 3
    assert float(row["worker_task_temp_written_sum"]) == 5
    assert float(row["worker_task_region_count"]) == 2
    assert float(row["worker_task_region_task_count_cv"]) == 0
    assert float(row["worker_task_region_rows_max_share"]) == 0.8
    assert float(row["worker_task_region_scan_rows_max_share"]) == 0.8
    assert float(row["worker_task_within_region_scan_rows_cv_max"]) == 0.5
    assert float(row["worker_task_within_region_scan_rows_max_share_max"]) == 0.75
    assert float(row["worker_task_within_region_plan_fingerprint_count_max"]) == 2
    assert float(row["worker_node_count_seq_scan"]) == 1
    assert float(row["worker_node_count_index_scan"]) == 2
    assert float(row["worker_node_count_bitmap_heap_scan"]) == 1
    assert float(row["worker_node_count_bitmap_index_scan"]) == 1
    assert float(row["worker_node_count_hash_join"]) == 1
    assert float(row["worker_node_count_hash_aggregate"]) == 1
    assert float(row["worker_node_count_materialize"]) == 1
    assert float(row["worker_node_count_other"]) == 1
    assert context[0]["worker_task_node_type_unknown_count"] == "1.0"
    assert context[0]["worker_task_node_type_unknown_set_json"] == '["Future Scan"]'
    assert "worker_task_node_type_counts_json" in context[0]
