from __future__ import annotations

import csv
import json
from pathlib import Path

from master_regimes.extract.explain_json import extract_plan_rows
from master_regimes.extract.query_sweep_index import (
    _auto_explain_document_role,
    _citus_repartition_observed_v2,
    _citus_task_metadata,
    _citus_text_plan_summary,
    _coordinator_pressure_summary,
    _execution_evidence_contract_summary,
    _os_network_summary,
    _remote_edge_observation_rows,
    _worker_plan_summary,
    _worker_task_aggregates,
    _worker_text_plan_summary,
    index_query_sweep,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_os_network_summary_preserves_worker_level_movement_proxy(
    tmp_path: Path,
) -> None:
    artifacts: dict[str, str] = {}
    for node_name, rx_bytes, tx_bytes in (
        ("eu-worker-1", 100, 900),
        ("eu-worker-2", 300, 100),
        ("eu-coord-1", 50, 70),
    ):
        artifact = f"nodes/{node_name}/capture"
        artifacts[node_name] = artifact
        _write_json(
            tmp_path / artifact / "metrics" / "os_summary.json",
            {
                "sample_count": 2,
                "net_delta": {
                    "ens7": {
                        "rx_bytes": rx_bytes,
                        "tx_bytes": tx_bytes,
                        "rx_packets": 1,
                        "tx_packets": 1,
                    }
                },
            },
        )

    summary = _os_network_summary(
        tmp_path,
        {"local_artifacts": artifacts},
    )

    assert summary["worker_rx_bytes_sum"] == 400
    assert summary["worker_tx_bytes_sum"] == 1000
    assert summary["worker_rx_bytes_max_share"] == 0.75
    assert summary["worker_tx_bytes_max_share"] == 0.9
    assert summary["worker_rx_bytes_cv"] == 0.5
    assert summary["worker_tx_bytes_cv"] == 0.8
    assert summary["os_query_aligned_node_count"] == 0
    assert summary["os_query_alignment_worst_status"] == "legacy"
    regions = json.loads(summary["worker_network_regions_json"])
    assert regions["eu"]["worker_count"] == 2
    assert regions["eu"]["tx_bytes"] == 1000


def test_os_network_summary_prefers_query_aligned_artifact(
    tmp_path: Path,
) -> None:
    artifact = "nodes/eu-worker-1/capture"
    metrics = tmp_path / artifact / "metrics"
    _write_json(
        metrics / "os_summary.json",
        {
            "sample_count": 40,
            "summary_scope": "capture_envelope",
            "cpu_busy_pct": 2,
            "net_delta": {"ens7": {"rx_bytes": 10_000}},
        },
    )
    _write_json(
        metrics / "os_query_summary.json",
        {
            "sample_count": 4,
            "raw_sample_count": 40,
            "summary_scope": "query_bracket",
            "duration_seconds": 0.75,
            "cpu_busy_pct": 48,
            "first_sample": {
                "cpu": {"user": 10, "system": 10, "idle": 70, "steal": 10},
            },
            "last_sample": {
                "cpu": {"user": 30, "system": 20, "idle": 130, "steal": 20},
            },
            "mem": {
                "max_used_bytes": 500,
                "min_available_bytes": 300,
            },
            "disk_delta": {
                "vda": {
                    "read_bytes": 1024,
                    "written_bytes": 2048,
                }
            },
            "net_delta": {"ens7": {"rx_bytes": 900}},
            "alignment": {
                "status": "high",
                "coverage": True,
                "query_duration_seconds": 0.4,
                "total_padding_seconds": 0.35,
                "median_sample_interval_seconds": 0.25,
            },
        },
    )

    summary = _os_network_summary(
        tmp_path,
        {
            "local_artifacts": {"eu-worker-1": artifact},
            "node_clock_calibrations": {
                "eu-worker-1": {
                    "status": "available",
                    "remote_minus_controller_seconds": 0.03,
                    "uncertainty_seconds": 0.01,
                }
            },
        },
    )

    assert summary["os_query_aligned_node_count"] == 1
    assert summary["os_query_alignment_coverage_count"] == 1
    assert summary["os_query_alignment_worst_status"] == "high"
    assert summary["os_clock_calibrated_node_count"] == 1
    assert summary["os_clock_uncertainty_seconds_max"] == 0.01
    assert summary["os_raw_sample_count_sum"] == 40
    assert summary["os_cpu_busy_pct_mean"] == 48
    assert summary["os_cpu_steal_pct_mean"] == 10
    assert summary["os_cpu_steal_pct_max"] == 10
    assert summary["os_mem_used_peak_bytes_max"] == 500
    assert summary["os_mem_available_bytes_min"] == 300
    assert summary["os_disk_read_bytes_sum"] == 1024
    assert summary["os_disk_written_bytes_sum"] == 2048
    assert summary["os_net_rx_bytes_sum"] == 900


def test_explain_rows_preserve_fdw_schema_and_remote_sql() -> None:
    rows = extract_plan_rows(
        [
            {
                "Plan": {
                    "Node Type": "Foreign Scan",
                    "Schema": "fdw_eu",
                    "Relation Name": "events",
                    "Remote SQL": "SELECT tenant_id FROM public.events",
                }
            }
        ]
    )

    assert rows[0]["schema_name"] == "fdw_eu"
    assert rows[0]["remote_sql_text"] == "SELECT tenant_id FROM public.events"


def test_explain_rows_preserve_fdw_relations_for_aggregate_pushdown() -> None:
    rows = extract_plan_rows(
        [
            {
                "Plan": {
                    "Node Type": "Foreign Scan",
                    "Relations": "Aggregate on (fdw_eu.events e)",
                    "Remote SQL": "SELECT count(*) FROM public.events",
                }
            }
        ]
    )

    assert rows[0]["schema_name"] == ""
    assert rows[0]["relations_text"] == "Aggregate on (fdw_eu.events e)"


def test_remote_edge_rows_keep_edge_local_plan_network_and_fetch_context() -> None:
    query_row = {
        "query_run_id": "run-1",
        "instance_id": "instance-1",
        "template_id": "template-1",
        "fetch_size": "100",
        "elapsed_seconds": "2",
        "network_profile_id": "pressure_remote_bandwidth_10mbit_eu",
        "configured_bandwidth_mbit": "10",
        "network_profile_json": json.dumps(
            {
                "target_region_ids": ["eu"],
                "configured_delay_ms": 0,
                "configured_jitter_ms": 0,
                "configured_loss_percent": 0,
                "configured_bandwidth_mbit": 10,
            },
            sort_keys=True,
        ),
        "os_network_nodes_json": json.dumps(
            [
                {
                    "node_name": "eu-coord-1",
                    "net_delta_by_interface": {
                        "ens7": {"tx_bytes": 10000, "tx_packets": 100}
                    },
                    "tcp_retrans_segs": 2,
                    "qdisc_before": [
                        {
                            "kind": "netem",
                            "handle": "30:",
                            "bytes": 1000,
                            "packets": 10,
                            "drops": 0,
                            "overlimits": 1,
                        }
                    ],
                    "qdisc_after": [
                        {
                            "kind": "netem",
                            "handle": "30:",
                            "bytes": 5000,
                            "packets": 40,
                            "drops": 1,
                            "overlimits": 5,
                        }
                    ],
                },
                {
                    "node_name": "us-coord-1",
                    "net_delta_by_interface": {
                        "ens7": {"tx_bytes": 4000, "tx_packets": 40}
                    },
                    "tcp_retrans_segs": 0,
                    "qdisc_before": [],
                    "qdisc_after": [],
                },
                {
                    "node_name": "eu-analytics-1",
                    "rx_bytes": 15000,
                },
            ],
            sort_keys=True,
        ),
    }
    edge_context = [
        {
            "edge_id": "eu->eu-analytics-1",
            "source_cluster_id": "eu",
            "source_node": "eu-coord-1",
            "destination_gac_id": "eu-analytics-1",
            "before": {
                "route_device": "ens7",
                "route_source_ip": "10.0.0.11",
                "rtt_median_ms": 80,
                "rtt_max_ms": 84,
                "rtt_mdev_ms": 2,
                "packet_loss_percent": 0,
                "ping_packets_received": 5,
            },
            "after": {
                "route_device": "ens7",
                "route_source_ip": "10.0.0.11",
                "rtt_median_ms": 82,
                "rtt_max_ms": 88,
                "rtt_mdev_ms": 3,
                "packet_loss_percent": 20,
                "ping_packets_received": 4,
            },
        },
        {
            "edge_id": "us->eu-analytics-1",
            "source_cluster_id": "us",
            "source_node": "us-coord-1",
            "destination_gac_id": "eu-analytics-1",
            "before": {
                "route_device": "ens7",
                "route_source_ip": "10.0.0.21",
                "rtt_median_ms": 1,
                "rtt_max_ms": 2,
                "rtt_mdev_ms": 0.2,
                "packet_loss_percent": 0,
                "ping_packets_received": 5,
            },
            "after": {
                "route_device": "ens7",
                "route_source_ip": "10.0.0.21",
                "rtt_median_ms": 1.2,
                "rtt_max_ms": 2.2,
                "rtt_mdev_ms": 0.3,
                "packet_loss_percent": 0,
                "ping_packets_received": 5,
            },
        },
    ]
    plan_nodes = [
        {
            "plan_scope": "main",
            "node_type": "Foreign Scan",
            "schema_name": "",
            "relations_text": "Aggregate on (fdw_eu.events e)",
            "remote_sql_text": "SELECT tenant_id, value FROM public.events",
            "actual_rows": "250",
            "actual_total_time": "150",
            "plan_width": "16",
        },
        {
            "plan_scope": "main",
            "node_type": "Foreign Scan",
            "schema_name": "fdw_us",
            "remote_sql_text": "SELECT tenant_id, value FROM public.events",
            "actual_rows": "100",
            "actual_total_time": "20",
            "plan_width": "16",
        },
    ]
    region_fragments = [
        {
            "region_id": "eu",
            "remote_actual_rows": "250",
            "remote_actual_total_time_ms": "40",
            "remote_tuple_bytes_proxy": "4000",
        },
        {
            "region_id": "us",
            "remote_actual_rows": "100",
            "remote_actual_total_time_ms": "15",
            "remote_tuple_bytes_proxy": "1600",
        },
    ]
    remote_plans = [
        {"fdw_region": "eu", "remote_plan_fingerprint": "plan-eu"},
        {"fdw_region": "us", "remote_plan_fingerprint": "plan-us"},
    ]

    rows = _remote_edge_observation_rows(
        query_sweep_id="sweep-1",
        query_row=query_row,
        edge_context_rows=edge_context,
        plan_nodes=plan_nodes,
        region_fragments=region_fragments,
        remote_plans=remote_plans,
    )
    by_region = {row["source_cluster_id"]: row for row in rows}

    assert set(by_region) == {"eu", "us"}
    assert by_region["eu"]["edge_id"] == "eu->eu-analytics-1"
    assert by_region["eu"]["foreign_schema_id"] == "fdw_eu"
    assert by_region["eu"]["foreign_server_id"] == "eu_citus"
    assert by_region["eu"]["remote_rows"] == 250
    assert by_region["eu"]["remote_tuple_width"] == 16
    assert by_region["eu"]["remote_bytes_proxy"] == 4000
    assert by_region["eu"]["estimated_fetch_cycles"] == 3
    assert by_region["eu"]["remote_sql_fingerprint"]
    assert by_region["eu"]["remote_plan_fingerprint_count"] == 1
    assert by_region["eu"]["rtt_context_median_ms"] == 81
    assert by_region["eu"]["rtt_context_max_ms"] == 88
    assert by_region["eu"]["packet_loss_context_percent_max"] == 20
    assert by_region["eu"]["route_source_ip"] == "10.0.0.11"
    assert by_region["eu"]["query_window_source_tx_bytes"] == 10000
    assert by_region["eu"]["query_window_source_tx_bps"] == 40000
    assert by_region["eu"]["query_window_qdisc_bytes"] == 4000
    assert by_region["eu"]["query_window_qdisc_packets"] == 30
    assert by_region["eu"]["query_window_qdisc_drops"] == 1
    assert by_region["eu"]["query_window_qdisc_overlimits"] == 4
    assert by_region["eu"]["tcp_retrans_delta_node_global"] == 2
    assert by_region["eu"]["network_intervention_targeted"] == "true"
    assert by_region["eu"]["configured_bandwidth_mbit"] == 10
    assert by_region["us"]["estimated_fetch_cycles"] == 1
    assert by_region["us"]["rtt_context_median_ms"] == 1.1
    assert by_region["us"]["network_intervention_targeted"] == "false"
    assert by_region["us"]["configured_bandwidth_mbit"] == 0


def test_coordinator_pressure_summary_preserves_operator_inputs_and_spill(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.json"
    _write_json(
        plan_path,
        [
            {
                "Plan": {
                    "Node Type": "Limit",
                    "Actual Rows": 10,
                    "Actual Loops": 1,
                    "Actual Total Time": 30,
                    "Plan Width": 24,
                    "Temp Read Blocks": 8,
                    "Temp Written Blocks": 12,
                    "Plans": [
                        {
                            "Node Type": "Sort",
                            "Actual Rows": 10,
                            "Actual Loops": 1,
                            "Actual Total Time": 29,
                            "Plan Width": 24,
                            "Sort Method": "external merge",
                            "Sort Space Used": 2048,
                            "Sort Space Type": "Disk",
                            "Plans": [
                                {
                                    "Node Type": "HashAggregate",
                                    "Actual Rows": 100,
                                    "Actual Loops": 1,
                                    "Actual Total Time": 20,
                                    "Plan Width": 24,
                                    "HashAgg Batches": 4,
                                    "Disk Usage": 3072,
                                    "Peak Memory Usage": 256,
                                    "Plans": [
                                        {
                                            "Node Type": "Append",
                                            "Actual Rows": 2000,
                                            "Actual Loops": 1,
                                            "Actual Total Time": 10,
                                            "Plan Width": 16,
                                            "Plans": [
                                                {
                                                    "Node Type": "Foreign Scan",
                                                    "Actual Rows": 1000,
                                                    "Actual Loops": 1,
                                                    "Actual Total Time": 4,
                                                    "Plan Width": 16,
                                                },
                                                {
                                                    "Node Type": "Foreign Scan",
                                                    "Actual Rows": 1000,
                                                    "Actual Loops": 1,
                                                    "Actual Total Time": 5,
                                                    "Plan Width": 16,
                                                },
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
        ],
    )

    result = _coordinator_pressure_summary(plan_path)

    assert result["coordinator_fanin_rows"] == 2000
    assert result["coordinator_fanin_bytes_estimated"] == 32000
    assert result["coordinator_final_rows"] == 10
    assert result["coordinator_sort_input_rows_sum"] == 100
    assert result["coordinator_aggregate_input_rows_sum"] == 2000
    assert result["coordinator_limit_input_rows_sum"] == 10
    assert result["coordinator_blocking_input_rows_sum"] == 2100
    assert result["coordinator_temp_read_blocks"] == 8
    assert result["coordinator_temp_written_blocks"] == 12
    assert result["coordinator_disk_sort_count"] == 1
    assert result["coordinator_hash_batches_max"] == 4
    assert result["coordinator_hashagg_disk_usage_kb_max"] == 3072
    assert result["coordinator_spill_present"] == "true"
    assert result["coordinator_non_foreign_time_ms_proxy"] == 21


def test_worker_text_plan_summary_classifies_parallel_full_scan_plan() -> None:
    summary = _worker_text_plan_summary(
        "\n".join(
            [
                "Gather  (cost=1000.00..15000.00 rows=2 width=32) "
                "(actual time=1.000..2.000 rows=1 loops=1)",
                "  Workers Planned: 2",
                "  Workers Launched: 2",
                "  ->  Finalize Aggregate  "
                "(cost=0.00..0.01 rows=1 width=32) "
                "(actual time=0.800..0.900 rows=1 loops=3)",
                "        ->  Partial Aggregate  "
                "(cost=0.00..0.01 rows=1 width=32) "
                "(actual time=0.500..0.700 rows=1 loops=3)",
                "              ->  Parallel Seq Scan on events_105709 events  "
                "(cost=0.00..100.00 rows=1000 width=16) "
                "(actual time=0.100..0.400 rows=1000 loops=3)",
                "                    Buffers: shared hit=7 read=3, "
                "temp read=2 written=5",
            ]
        )
    )

    assert summary["root_node_type"] == "Gather"
    assert summary["node_type_counts"] == {
        "Finalize Aggregate": 1,
        "Gather": 1,
        "Parallel Seq Scan": 1,
        "Partial Aggregate": 1,
    }
    assert summary["scan_type_counts"] == {"seq_scan": 1}
    assert summary["aggregate_node_count"] == 2
    assert summary["blocking_node_count"] == 2
    assert summary["has_aggregate"] is True
    assert summary["shared_hit_blocks"] == 7
    assert summary["shared_read_blocks"] == 3
    assert summary["temp_read_blocks"] == 2
    assert summary["temp_written_blocks"] == 5
    assert summary["unknown_count"] == 0


def test_worker_plan_summary_reads_structured_citus_remote_plan() -> None:
    summary = _worker_plan_summary(
        {
            "Remote Plan": [
                [
                    {
                        "Plan": {
                            "Node Type": "Aggregate",
                            "Actual Rows": 4,
                            "Actual Total Time": 3.5,
                            "Plans": [
                                {
                                    "Node Type": "Hash Join",
                                    "Actual Rows": 20,
                                    "Actual Total Time": 3.0,
                                    "Plans": [
                                        {
                                            "Node Type": "Seq Scan",
                                            "Actual Rows": 20,
                                            "Actual Total Time": 1.0,
                                            "Shared Hit Blocks": 3,
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ]
            ]
        }
    )

    assert summary["parse_status"] == "ok"
    assert summary["root_node_type"] == "Aggregate"
    assert summary["actual_rows"] == 4
    assert summary["scan_actual_rows_sum"] == 20
    assert summary["join_node_count"] == 1
    assert summary["shared_hit_blocks"] == 3


def test_worker_task_aggregates_include_isf_features() -> None:
    rows = [
        {
            "fdw_region": "eu",
            "worker_node": "worker-a",
            "worker_task_actual_rows": "20",
            "worker_task_scan_actual_rows_sum": "20",
            "worker_task_actual_time_ms": "2",
            "tuple_data_received_bytes": "20",
        },
        {
            "fdw_region": "eu",
            "worker_node": "worker-b",
            "worker_task_actual_rows": "60",
            "worker_task_scan_actual_rows_sum": "60",
            "worker_task_actual_time_ms": "6",
            "tuple_data_received_bytes": "60",
        },
    ]

    result = _worker_task_aggregates(rows)

    assert result["worker_task_scan_actual_rows_max_share"] == 0.75
    assert result["worker_task_scan_rows_isf"] == 1.5
    assert result["worker_task_root_rows_isf"] == 1.5
    assert result["worker_task_within_region_scan_rows_isf_max"] == 1.5
    assert (
        result["worker_task_within_region_scan_rows_isf_normalized_max"] == 0.5
    )
    assert result["worker_task_count_cv"] == 0.0
    assert result["worker_rows_cv"] == 0.5
    assert result["worker_scan_rows_sum"] == 80.0
    assert result["worker_scan_rows_worker_count"] == 2
    assert result["worker_scan_rows_cv"] == 0.5
    assert result["worker_scan_rows_cv_normalized"] == 0.5
    assert result["worker_scan_rows_isf"] == 1.5
    assert result["worker_scan_rows_isf_normalized"] == 0.5
    assert result["worker_task_scan_rows_isf_normalized"] == 0.5
    assert result["worker_task_active_scan_rows_isf"] == 1.5
    assert result["worker_task_active_scan_rows_isf_normalized"] == 0.5
    assert result["worker_task_active_scan_skew_applicable"] == "true"
    assert result["worker_task_active_scan_skew_applicable_region_count"] == 1
    assert (
        result["worker_task_within_region_active_scan_rows_isf_normalized_max"]
        == 0.5
    )
    assert result["worker_task_tuple_bytes_sum"] == 80.0
    assert result["worker_task_tuple_bytes_isf"] == 1.5
    assert result["worker_task_tuple_bytes_isf_normalized"] == 0.5
    assert result["worker_task_tuple_bytes_skew_applicable"] == "true"
    assert result["worker_task_tuple_bytes_skew_applicable_region_count"] == 1
    assert (
        result["worker_task_within_region_tuple_bytes_isf_normalized_max"]
        == 0.5
    )
    assert result["worker_task_nonzero_scan_count"] == 2
    assert result["worker_task_nonzero_scan_share"] == 1.0
    assert result["worker_task_scan_skew_applicable"] == "true"
    assert result["worker_task_scan_skew_applicable_region_count"] == 1
    assert result["worker_scan_rows_skew_applicable"] == "true"
    assert result["worker_scan_rows_skew_applicable_region_count"] == 1
    assert result["worker_task_within_region_worker_scan_rows_cv_max"] == 0.5
    assert result["worker_task_within_region_worker_scan_rows_isf_max"] == 1.5
    assert (
        result["worker_task_within_region_worker_scan_rows_isf_normalized_max"]
        == 0.5
    )
    assert result["worker_task_actual_time_isf"] == 1.5
    assert result["worker_task_actual_time_isf_normalized"] == 0.5
    assert result["worker_time_cv"] == 0.5


def test_worker_time_cv_is_missing_when_worker_task_timing_is_unavailable() -> None:
    rows = [
        {
            "fdw_region": "eu",
            "worker_node": "worker-a",
            "worker_task_actual_rows": "20",
        },
        {
            "fdw_region": "eu",
            "worker_node": "worker-b",
            "worker_task_actual_rows": "60",
        },
    ]

    result = _worker_task_aggregates(rows)

    assert result["worker_rows_cv"] == 0.5
    assert result.get("worker_time_cv", "") == ""
    assert result.get("worker_time_isf", "") == ""


def test_evidence_contract_distinguishes_repartition_from_missing_tasks() -> None:
    repartition = _execution_evidence_contract_summary(
        query_row={
            "main_has_foreign_scan": "true",
            "citus_repartition_observed_v2": "true",
            "remote_citus_tasks_shown_none_count": "2",
        },
        plan_files=[
            {"plan_scope": "main"},
            {"plan_scope": "fdw_auto_explain_remote"},
            {"plan_scope": "fdw_auto_explain_internal"},
        ],
        region_fragments=[{"region_id": "eu"}],
        worker_tasks=[],
    )

    assert repartition["regional_remote_plan_count"] == 1
    assert repartition["regional_internal_plan_count"] == 1
    assert repartition["regional_plan_evidence_status"] == "available"
    assert (
        repartition["worker_task_evidence_status"]
        == "structurally_unavailable_repartition"
    )
    assert (
        repartition["worker_task_timing_status"]
        == "structurally_unavailable_repartition"
    )

    missing = _execution_evidence_contract_summary(
        query_row={
            "main_has_foreign_scan": "true",
            "remote_region_task_count_sum": "32",
        },
        plan_files=[{"plan_scope": "main"}],
        region_fragments=[],
        worker_tasks=[],
    )

    assert missing["regional_plan_evidence_status"] == "missing_unexpected"
    assert missing["worker_task_evidence_status"] == "missing_unexpected"


def test_evidence_contract_records_embedded_text_parse_and_timing_status() -> None:
    result = _execution_evidence_contract_summary(
        query_row={"main_has_foreign_scan": "false"},
        plan_files=[{"plan_scope": "main"}],
        region_fragments=[],
        worker_tasks=[
            {"parse_status": "ok", "worker_task_actual_time_ms": "2.5"},
            {"parse_status": "partial", "worker_task_actual_time_ms": ""},
        ],
    )

    assert result["worker_task_evidence_status"] == "available"
    assert result["worker_task_plan_format"] == "citus_embedded_text_in_explain_json"
    assert result["worker_task_timing_status"] == "available"
    assert result["worker_task_parse_ok_count"] == 1
    assert result["worker_task_parse_partial_count"] == 1
    assert result["worker_task_parse_failed_count"] == 0


def test_shard_pruned_tasks_are_not_reported_as_balanced_skew_cases() -> None:
    rows = [
        {
            "fdw_region": "eu",
            "worker_node": "eu-worker-a",
            "worker_task_actual_rows": "100",
            "worker_task_scan_actual_rows_sum": "100",
            "worker_task_actual_time_ms": "",
        },
        {
            "fdw_region": "us",
            "worker_node": "us-worker-b",
            "worker_task_actual_rows": "10",
            "worker_task_scan_actual_rows_sum": "10",
            "worker_task_actual_time_ms": "",
        },
    ]

    result = _worker_task_aggregates(rows)

    assert result["worker_task_plan_count"] == 2
    assert result["worker_task_scan_skew_applicable"] == "false"
    assert result["worker_task_scan_skew_applicable_region_count"] == 0
    assert result["worker_task_active_scan_skew_applicable"] == "false"
    assert result["worker_task_active_scan_skew_applicable_region_count"] == 0
    assert result["worker_scan_rows_skew_applicable"] == "false"
    assert result["worker_scan_rows_skew_applicable_region_count"] == 0
    # Cross-region values may differ, but there is only one task and one worker
    # per regional Citus cluster. That is a router/pruning case, not worker skew.
    assert result["worker_scan_rows_cv"] > 0


def test_auto_explain_explain_document_is_diagnostic_not_remote_query() -> None:
    document = {
        "Query Text": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM events",
        "Plan": {
            "Node Type": "Custom Scan",
            "Custom Plan Provider": "Citus Adaptive",
        },
    }

    assert _auto_explain_document_role(document) == "regional_diagnostic_explain"


def test_citus_task_metadata_marks_repartition_task_list_unavailable() -> None:
    metadata = _citus_task_metadata(
        {
            "Plan": {
                "Node Type": "Limit",
                "Distributed Query": {
                    "Job": {
                        "Task Count": 12,
                        "Tuple data received from nodes": "0 bytes",
                        "Tasks Shown": "None, not supported for re-partition queries",
                        "Dependent Jobs": [
                            {"Map Task Count": 32, "Merge Task Count": 12},
                            {"Map Task Count": 32, "Merge Task Count": 12},
                        ],
                    }
                },
            }
        }
    )

    assert metadata["remote_citus_task_count"] == 12
    assert metadata["remote_citus_tasks_shown_none"] == "true"
    assert metadata["remote_citus_task_list_available"] == "false"
    assert metadata["remote_citus_tuple_bytes_supported"] == "false"
    assert metadata["remote_citus_tuple_bytes_source"] == (
        "repartition_task_list_unavailable_reported_zero"
    )
    assert metadata["remote_citus_map_merge_job_count"] == 2
    assert metadata["remote_citus_dependent_map_task_count_sum"] == 64
    assert metadata["remote_citus_dependent_merge_task_count_sum"] == 24
    assert metadata["remote_citus_repartition_fanout_ratio"] == 64 / 12
    assert metadata["remote_citus_plan_locality_class"] == "repartition_mapmerge"
    assert metadata["remote_citus_repartition_mapmerge"] == "true"


def test_citus_task_metadata_distinguishes_reference_and_colocated_candidates() -> None:
    reference = _citus_task_metadata(
        {
            "Plan": {
                "Distributed Query": {
                    "Job": {
                        "Task Count": 2,
                        "Tasks Shown": "All",
                        "Tasks": [
                            {
                                "Query": (
                                    "SELECT * FROM events_102506 e "
                                    "JOIN tenants_102497 t ON e.tenant_id = t.tenant_id"
                                )
                            },
                            {
                                "Query": (
                                    "SELECT * FROM events_102507 e "
                                    "JOIN tenants_102497 t ON e.tenant_id = t.tenant_id"
                                )
                            },
                        ],
                    }
                }
            }
        }
    )
    colocated = _citus_task_metadata(
        {
            "Plan": {
                "Distributed Query": {
                    "Job": {
                        "Task Count": 2,
                        "Tasks Shown": "All",
                        "Tasks": [
                            {
                                "Query": (
                                    "SELECT * FROM events_102506 e "
                                    "JOIN users_102538 u "
                                    "ON u.tenant_id = e.tenant_id AND u.user_id = e.user_id"
                                )
                            },
                            {
                                "Query": (
                                    "SELECT * FROM events_102507 e "
                                    "JOIN users_102539 u "
                                    "ON u.tenant_id = e.tenant_id AND u.user_id = e.user_id"
                                )
                            },
                        ],
                    }
                }
            }
        }
    )

    assert reference["remote_citus_plan_locality_class"] == "reference_join_candidate"
    assert reference["remote_citus_reference_join_candidate"] == "true"
    assert colocated["remote_citus_plan_locality_class"] == "colocated_join_candidate"
    assert colocated["remote_citus_colocated_join_candidate"] == "true"


def test_citus_text_plan_summary_extracts_map_merge_counts() -> None:
    summary = _citus_text_plan_summary(
        """
        Task Count: 12
        Tasks Shown: None, not supported for re-partition queries
        MapMergeJob
          Map Task Count: 32
          Merge Task Count: 12
        MapMergeJob
          Map Task Count: 32
          Merge Task Count: 12
        """
    )

    assert summary["citus_top_task_count"] == 12
    assert summary["citus_map_merge_job_count"] == 2
    assert summary["citus_dependent_map_task_count_sum"] == 64
    assert summary["citus_dependent_merge_task_count_sum"] == 24
    assert summary["citus_repartition_fanout_ratio"] == 64 / 12
    assert summary["citus_repartition_query"] == "true"
    assert summary["citus_tasks_shown_none"] == "true"
    assert summary["citus_plan_locality_class"] == "repartition_mapmerge"


def test_semantic_v2_repartition_combines_main_and_regional_evidence() -> None:
    assert _citus_repartition_observed_v2(
        {
            "citus_repartition_query": "false",
            "remote_citus_repartition_mapmerge_count": "1",
            "remote_citus_plan_locality_classes": "repartition_mapmerge",
        }
    )
    assert _citus_repartition_observed_v2(
        {
            "citus_repartition_query": "true",
            "remote_citus_repartition_mapmerge_count": "0",
        }
    )
    assert not _citus_repartition_observed_v2(
        {
            "citus_repartition_query": "false",
            "remote_citus_repartition_mapmerge_count": "0",
        }
    )


def _plan(
    node_type: str,
    relation_name: str = "",
    *,
    plan_width: int = 16,
    plan_rows: int = 9,
    actual_rows: int = 10,
    children: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    plan: dict[str, object] = {
        "Node Type": node_type,
        "Plan Width": plan_width,
        "Plan Rows": plan_rows,
        "Actual Rows": actual_rows,
    }
    if relation_name:
        plan["Relation Name"] = relation_name
    if children:
        plan["Plans"] = children
    return [{"Plan": plan}]


def _citus_task_plan() -> list[dict[str, object]]:
    return [
        {
            "Plan": {
                "Node Type": "Custom Scan",
                "Custom Plan Provider": "Citus Adaptive",
                "Plan Width": 96,
                "Plan Rows": 4,
                "Actual Rows": 20,
                "Distributed Query": {
                    "Job": {
                        "Task Count": 2,
                        "Tasks": [
                            {
                                "Node": "host=worker-1 port=5432 dbname=app",
                                "Remote Plan": [
                                    [
                                        {
                                            "Plan": {
                                                "Node Type": "Seq Scan",
                                                "Plan Rows": 10,
                                                "Plan Width": 24,
                                                "Actual Rows": 20.0,
                                                "Actual Total Time": 5.0,
                                            }
                                        }
                                    ]
                                ],
                            },
                            {
                                "Node": "host=worker-2 port=5432 dbname=app",
                                "Remote Plan": [
                                    [
                                        {
                                            "Plan": {
                                                "Node Type": "Seq Scan",
                                                "Plan Rows": 10,
                                                "Plan Width": 24,
                                                "Actual Rows": 60.0,
                                                "Actual Total Time": 15.0,
                                            }
                                        }
                                    ]
                                ],
                            },
                        ],
                    }
                },
            }
        }
    ]


def test_index_query_sweep_links_main_and_fdw_remote_plans(tmp_path: Path) -> None:
    sweep = tmp_path / "query-sweep"
    collection = sweep / "query-collections" / "q1"
    node_dir = collection / "nodes" / "eu-analytics-1" / "run-1"
    remote_dir = node_dir / "plans" / "remote"

    _write_json(
        sweep / "query_sweep_manifest.json",
        {
            "sweep_id": "sweep-1",
            "executions": [
                {
                    "condition_id": "condition-1",
                    "instance_id": "instance-1",
                    "template_id": "template-1",
                    "corpus_id": "corpus-1",
                    "corpus_cell_id": "cell-1",
                    "logical_question_id": "top_tenants",
                    "execution_strategy": "fdw_raw",
                    "dataset_profile_id": "geo-skew-heavy-v1",
                    "runtime_config_id": "fetch_small",
                    "topology_id": "eu_gac",
                    "intervention_role": "positive_case",
                    "intervention_axis": "fetch_size",
                    "expected_regime_targets": "remote_fetch_heavy,gac_finalization_heavy",
                    "runtime_sensitivity": (
                        '{"fetch_size":"high","wan_latency":"high","work_mem":"high"}'
                    ),
                    "params": {"lookback_days": 1},
                    "expected_shape_tags": "fdw_remote_scan",
                    "rendered_sql_path": "/tmp/query.sql",
                    "collection_dir": str(collection),
                }
            ],
        },
    )
    _write_json(
        collection / "execution_manifest.json",
        {
            "execution_id": "run-1",
            "created_at_utc": "20260101T000000Z",
            "coordinator": "eu-analytics-1",
            "local_artifacts": {"eu-analytics-1": "nodes/eu-analytics-1/run-1"},
            "node_run_dirs": {"eu-analytics-1": "/var/lib/psql-benchmarks/runs/run-1"},
            "errors": [],
        },
    )
    _write_json(
        collection / "input" / "query_bindings.json",
        {
            "psql_variables": {"lookback_days": "1"},
            "pg_options": {},
            "sql_parameterization": "psql_variables_not_inlined",
        },
    )
    (collection / "input" / "query.sql").write_text(
        """
        select e.tenant_id, count(*)
        from events e
        join users u on u.tenant_id = e.tenant_id
        where e.tenant_id = 1
        group by e.tenant_id
        order by e.tenant_id;
        """,
        encoding="utf-8",
    )
    _write_json(node_dir / "metadata.json", {"bench_node_role": "analytics-client"})
    _write_json(
        node_dir / "plans" / "main.explain.json",
        _plan(
            "Aggregate",
            plan_width=128,
            plan_rows=9,
            actual_rows=20,
            children=[
                {
                    "Node Type": "Foreign Scan",
                    "Relation Name": "events",
                    "Plan Width": 128,
                    "Plan Rows": 9,
                    "Actual Rows": 20,
                }
            ],
        ),
    )
    _write_json(
        remote_dir / "remote_001.explain.json",
        _citus_task_plan(),
    )
    (node_dir / "plans" / "main.explain.txt").write_text("Foreign Scan\n", encoding="utf-8")
    (node_dir / "plans" / "main.explain.text.sql").write_text("EXPLAIN select 1;\n")
    (node_dir / "plans" / "main.explain.analyze.json.sql").write_text("EXPLAIN ANALYZE select 1;\n")
    (remote_dir / "remote_001.remote.sql").write_text("select 1;\n", encoding="utf-8")
    (remote_dir / "remote_001.explain.txt").write_text("Custom Scan\n", encoding="utf-8")
    (remote_dir / "remote_001.explain.text.sql").write_text("EXPLAIN select 1;\n")
    (remote_dir / "remote_001.explain.analyze.json.sql").write_text(
        "EXPLAIN ANALYZE select 1;\n"
    )
    _write_json(
        node_dir / "execution_manifest.json",
        {
            "plan_file": "plans/main.explain.json",
            "explain_text_file": "plans/main.explain.txt",
            "explain_text_sql_file": "plans/main.explain.text.sql",
            "explain_analyze_json_sql_file": "plans/main.explain.analyze.json.sql",
            "timing": {"elapsed_seconds": "0.1"},
            "errors": [],
            "fdw_remote_plan_probe": {
                "enabled": True,
                "status": "ok",
                "remote_sql_count": 1,
                "probes": [
                    {
                        "remote_sql_id": "remote_001",
                        "status": "ok",
                        "region": "eu",
                        "schema": "fdw_eu",
                        "relation_name": "events",
                        "alias": "e",
                        "node_type": "Foreign Scan",
                        "plan_file": "plans/remote/remote_001.explain.json",
                        "remote_sql_file": "plans/remote/remote_001.remote.sql",
                        "explain_text_file": "plans/remote/remote_001.explain.txt",
                        "explain_text_sql_file": "plans/remote/remote_001.explain.text.sql",
                        "explain_analyze_json_sql_file": (
                            "plans/remote/remote_001.explain.analyze.json.sql"
                        ),
                    }
                ],
            },
        },
    )

    out_dir = index_query_sweep(sweep_dir=sweep)

    query_rows = list(csv.DictReader((out_dir / "query_runs.csv").open()))
    corpus_rows = list(csv.DictReader((out_dir / "corpus_cells.csv").open()))
    plan_rows = list(csv.DictReader((out_dir / "plan_files.csv").open()))
    remote_rows = list(csv.DictReader((out_dir / "fdw_remote_plans.csv").open()))
    node_rows = list(csv.DictReader((out_dir / "plan_nodes.csv").open()))
    edge_rows = list(csv.DictReader((out_dir / "plan_edges.csv").open()))
    structure_rows = list(csv.DictReader((out_dir / "plan_structure_features.csv").open()))
    summary_rows = list(csv.DictReader((out_dir / "instance_summary_features.csv").open()))
    index_manifest = json.loads((out_dir / "index_manifest.json").read_text(encoding="utf-8"))

    assert query_rows[0]["fdw_remote_probe_status"] == "ok"
    assert query_rows[0]["condition_id"] == "condition-1"
    assert query_rows[0]["corpus_id"] == "corpus-1"
    assert query_rows[0]["corpus_cell_id"] == "cell-1"
    assert query_rows[0]["dataset_profile_id"] == "geo-skew-heavy-v1"
    assert query_rows[0]["runtime_config_id"] == "fetch_small"
    assert query_rows[0]["topology_id"] == "eu_gac"
    assert query_rows[0]["intervention_role"] == "positive_case"
    assert query_rows[0]["intervention_axis"] == "fetch_size"
    assert query_rows[0]["fdw_remote_sql_count"] == "1"
    assert query_rows[0]["logical_question_id"] == "top_tenants"
    assert query_rows[0]["execution_strategy"] == "fdw_raw"
    assert (
        query_rows[0]["expected_regime_targets"]
        == "remote_fetch_heavy,gac_finalization_heavy"
    )
    assert query_rows[0]["runtime_sensitivity"] == (
        '{"fetch_size":"high","wan_latency":"high","work_mem":"high"}'
    )
    assert len(corpus_rows) == 1
    assert corpus_rows[0]["corpus_cell_id"] == "cell-1"
    assert corpus_rows[0]["runtime_config_id"] == "fetch_small"
    assert corpus_rows[0]["query_run_count"] == "1"
    assert corpus_rows[0]["template_ids"] == "template-1"
    assert corpus_rows[0]["instance_ids"] == "instance-1"
    assert query_rows[0]["sql_normalized_hash"]
    assert query_rows[0]["rendered_sql_hash"]
    assert query_rows[0]["plan_fingerprint"]
    assert query_rows[0]["remote_plan_fingerprint"]
    assert query_rows[0]["repetition_index"] == "0"
    assert query_rows[0]["run_order"] == "1"
    assert query_rows[0]["cache_policy"] == "natural"
    assert query_rows[0]["distribution_key"] == "tenant_id"
    assert query_rows[0]["filter_uses_distribution_key"] == "true"
    assert query_rows[0]["join_uses_distribution_key"] == "true"
    assert query_rows[0]["group_by_uses_distribution_key"] == "true"
    assert query_rows[0]["order_by_uses_distribution_key"] == "true"
    assert query_rows[0]["tenant_filter_present"] == "true"
    assert query_rows[0]["single_tenant_scope"] == "true"
    assert query_rows[0]["multi_tenant_scope"] == "false"
    assert query_rows[0]["distribution_key_usage_source"] == "sql_heuristic"
    assert query_rows[0]["main_root_plan_width"] == "128.0"
    assert query_rows[0]["foreign_scan_plan_width_sum"] == "128.0"
    assert query_rows[0]["foreign_scan_plan_width_max"] == "128.0"
    assert query_rows[0]["remote_root_plan_width_sum"] == "96.0"
    assert query_rows[0]["remote_root_plan_width_max"] == "96.0"
    assert query_rows[0]["estimated_result_bytes"] == "2560.0"
    assert query_rows[0]["estimated_remote_output_bytes"] == "1920.0"
    assert query_rows[0]["estimated_fanin_bytes"] == "2560.0"
    assert query_rows[0]["result_width_class"] == "medium"
    assert round(float(query_rows[0]["foreign_scan_rows_estimate_error_log"]), 6) == round(
        0.7419373447293773,
        6,
    )
    assert round(float(query_rows[0]["remote_root_rows_estimate_error_log"]), 6) == round(
        1.4350845252893227,
        6,
    )
    assert query_rows[0]["task_count"] == "2"
    assert query_rows[0]["task_time_min_ms"] == "5.0"
    assert query_rows[0]["task_time_max_ms"] == "15.0"
    assert query_rows[0]["task_time_mean_ms"] == "10.0"
    assert query_rows[0]["task_time_cv"] == "0.5"
    assert query_rows[0]["task_rows_min"] == "20.0"
    assert query_rows[0]["task_rows_max"] == "60.0"
    assert query_rows[0]["task_rows_mean"] == "40.0"
    assert query_rows[0]["task_rows_cv"] == "0.5"
    assert query_rows[0]["worker_task_count_cv"] == "0.0"
    assert query_rows[0]["worker_rows_cv"] == "0.5"
    assert query_rows[0]["worker_time_cv"] == "0.5"
    assert len(plan_rows) == 2
    assert all(row["plan_fingerprint"] for row in plan_rows)
    assert len(remote_rows) == 1
    assert remote_rows[0]["plan_fingerprint"]
    assert {row["plan_scope"] for row in node_rows} == {
        "main",
        "fdw_remote",
        "citus_task_remote",
    }
    task_node_rows = [row for row in node_rows if row["plan_scope"] == "citus_task_remote"]
    assert len(task_node_rows) == 2
    assert {row["citus_task_index"] for row in task_node_rows} == {"0", "1"}
    assert {row["citus_task_worker"] for row in task_node_rows} == {
        "host=worker-1 port=5432 dbname=app",
        "host=worker-2 port=5432 dbname=app",
    }
    assert {row["node_path"] for row in node_rows if row["plan_scope"] == "main"} == {
        "0",
        "0.0",
    }
    assert {row["child_index"] for row in node_rows if row["plan_scope"] == "main"} == {
        "0"
    }
    assert len(edge_rows) == 1
    assert edge_rows[0]["plan_scope"] == "main"
    assert edge_rows[0]["parent_node_type"] == "Aggregate"
    assert edge_rows[0]["child_node_type"] == "Foreign Scan"
    assert edge_rows[0]["child_index"] == "0"
    assert edge_rows[0]["parent_node_path"] == "0"
    assert edge_rows[0]["child_node_path"] == "0.0"
    assert len(structure_rows) == 1
    assert structure_rows[0]["main_plan_node_count"] == "2"
    assert structure_rows[0]["main_plan_max_depth"] == "1"
    assert structure_rows[0]["main_plan_leaf_count"] == "1"
    assert structure_rows[0]["main_plan_branch_node_count"] == "1"
    assert structure_rows[0]["main_plan_avg_branching_factor"] == "1.0"
    assert structure_rows[0]["main_plan_max_branching_factor"] == "1"
    assert structure_rows[0]["remote_plan_leaf_count_sum"] == "3"
    assert structure_rows[0]["remote_plan_avg_branching_factor"] == "0.0"
    assert structure_rows[0]["aggregate_min_depth"] == "0"
    assert structure_rows[0]["aggregate_max_depth"] == "0"
    assert structure_rows[0]["foreign_scan_min_depth"] == "1"
    assert structure_rows[0]["foreign_scan_max_depth"] == "1"
    assert structure_rows[0]["sort_min_depth"] == ""
    assert structure_rows[0]["parent_child_type_count_Aggregate_ForeignScan"] == "1"
    assert len(summary_rows) == 1
    assert summary_rows[0]["query_run_count"] == "1"
    assert summary_rows[0]["plan_fingerprint_count"] == "1"
    assert summary_rows[0]["dominant_plan_fingerprint"] == query_rows[0]["plan_fingerprint"]
    assert summary_rows[0]["filter_uses_distribution_key"] == "true"
    assert summary_rows[0]["join_uses_distribution_key"] == "true"
    assert summary_rows[0]["single_tenant_scope"] == "true"
    assert summary_rows[0]["main_root_plan_width_mean"] == "128.0"
    assert summary_rows[0]["estimated_result_bytes_mean"] == "2560.0"
    assert summary_rows[0]["estimated_remote_output_bytes_mean"] == "1920.0"
    assert summary_rows[0]["estimated_fanin_bytes_mean"] == "2560.0"
    assert summary_rows[0]["dominant_result_width_class"] == "medium"
    assert round(
        float(summary_rows[0]["foreign_scan_rows_estimate_error_log_mean"]),
        6,
    ) == round(0.7419373447293773, 6)
    assert round(
        float(summary_rows[0]["foreign_scan_rows_estimate_error_abs_max"]),
        6,
    ) == round(0.7419373447293773, 6)
    assert round(
        float(summary_rows[0]["remote_root_rows_estimate_error_log_mean"]),
        6,
    ) == round(1.4350845252893227, 6)
    assert summary_rows[0]["task_count_mean"] == "2.0"
    assert summary_rows[0]["task_count_max"] == "2.0"
    assert summary_rows[0]["task_time_mean_ms_mean"] == "10.0"
    assert summary_rows[0]["task_time_cv_mean"] == "0.5"
    assert summary_rows[0]["task_time_cv_max"] == "0.5"
    assert summary_rows[0]["task_rows_mean_mean"] == "40.0"
    assert summary_rows[0]["task_rows_cv_mean"] == "0.5"
    assert summary_rows[0]["worker_task_count_cv_mean"] == "0.0"
    assert summary_rows[0]["worker_rows_cv_mean"] == "0.5"
    assert summary_rows[0]["worker_time_cv_mean"] == "0.5"
    assert (out_dir / "instance_summary_features.parquet").exists()
    assert (out_dir / "feature_schema.yml").exists()
    assert index_manifest["feature_schema_file"] == "feature_schema.yml"
    assert index_manifest["feature_schema_contract"] == "master_regimes_feature_schema_v1"
    assert index_manifest["plan_structure_feature_count"] == 1


def test_index_query_sweep_derives_repetition_order_and_previous_gap(tmp_path: Path) -> None:
    sweep = tmp_path / "query-sweep"
    collection_a = sweep / "query-collections" / "q1-a"
    collection_b = sweep / "query-collections" / "q1-b"

    executions = []
    for collection in (collection_a, collection_b):
        executions.append(
            {
                "instance_id": "instance-1",
                "template_id": "template-1",
                "params": {"lookback_days": 1},
                "collection_dir": str(collection),
            }
        )
    _write_json(
        sweep / "query_sweep_manifest.json",
        {
            "sweep_id": "sweep-1",
            "cache_policy": "randomized_order",
            "executions": executions,
        },
    )

    for index, collection in enumerate((collection_a, collection_b), start=1):
        node_dir = collection / "nodes" / "eu-analytics-1" / f"run-{index}"
        _write_json(
            collection / "execution_manifest.json",
            {
                "execution_id": f"run-{index}",
                "created_at_utc": "20260101T000000Z",
                "coordinator": "eu-analytics-1",
                "local_artifacts": {"eu-analytics-1": f"nodes/eu-analytics-1/run-{index}"},
                "errors": [],
            },
        )
        (collection / "input" / "query.sql").parent.mkdir(parents=True, exist_ok=True)
        (collection / "input" / "query.sql").write_text("select 1;\n", encoding="utf-8")
        _write_json(node_dir / "plans" / "main.explain.json", _plan("Result"))
        _write_json(
            node_dir / "execution_manifest.json",
            {
                "plan_file": "plans/main.explain.json",
                "timing": {
                    "elapsed_seconds": "0.1",
                    "query_started_at_unix": 100.0 + ((index - 1) * 30.0),
                    "query_finished_at_unix": 110.0 + ((index - 1) * 30.0),
                },
                "errors": [],
                "fdw_remote_plan_probe": {
                    "enabled": False,
                    "status": "skipped",
                    "remote_sql_count": 0,
                    "probes": [],
                },
            },
        )

    out_dir = index_query_sweep(sweep_dir=sweep)
    query_rows = list(csv.DictReader((out_dir / "query_runs.csv").open()))
    summary_rows = list(csv.DictReader((out_dir / "instance_summary_features.csv").open()))

    assert [row["run_order"] for row in query_rows] == ["1", "2"]
    assert [row["repetition_index"] for row in query_rows] == ["0", "1"]
    assert [row["cache_policy"] for row in query_rows] == [
        "randomized_order",
        "randomized_order",
    ]
    assert query_rows[0]["same_instance_previous_execution_gap_seconds"] == ""
    assert query_rows[1]["same_instance_previous_execution_gap_seconds"] == "20.0"
    assert len(summary_rows) == 1
    assert summary_rows[0]["query_run_count"] == "2"
    assert summary_rows[0]["measurement_count"] == "2"
    assert summary_rows[0]["successful_run_count"] == "2"
    assert summary_rows[0]["failed_run_count"] == "0"
    assert float(summary_rows[0]["failure_rate"]) == 0.0
    assert float(summary_rows[0]["execution_time_mean"]) == 0.1
    assert float(summary_rows[0]["execution_time_median"]) == 0.1
    assert float(summary_rows[0]["execution_time_p95"]) == 0.1
    assert float(summary_rows[0]["execution_time_std"]) == 0.0
    assert float(summary_rows[0]["execution_time_cv"]) == 0.0
    assert summary_rows[0]["plan_fingerprint_count"] == "1"
    assert summary_rows[0]["first_run_order"] == "1.0"
    assert summary_rows[0]["last_run_order"] == "2.0"
    assert (out_dir / "instance_summary_features.parquet").exists()


def test_index_query_sweep_keeps_auto_explain_internal_plans_out_of_region_fragments(
    tmp_path: Path,
) -> None:
    sweep = tmp_path / "query-sweep"
    collection = sweep / "query-collections" / "q1"
    node_dir = collection / "nodes" / "eu-analytics-1" / "run-1"
    auto_log = collection / "regional-auto-explain" / "eu-coord-1.log"

    _write_json(
        sweep / "query_sweep_manifest.json",
        {
            "sweep_id": "sweep-1",
            "executions": [
                {
                    "instance_id": "instance-1",
                    "template_id": "template-1",
                    "execution_strategy": "fdw_raw",
                    "collection_dir": str(collection),
                    "params": {},
                }
            ],
        },
    )
    _write_json(
        collection / "execution_manifest.json",
        {
            "execution_id": "run-1",
            "created_at_utc": "20260101T000000Z",
            "coordinator": "eu-analytics-1",
            "local_artifacts": {"eu-analytics-1": "nodes/eu-analytics-1/run-1"},
            "errors": [],
            "fdw_auto_explain": {
                "regions": ["eu"],
                "regional_hosts": {
                    "eu-coord-1": {
                        "region": "eu",
                        "local_log_file": "regional-auto-explain/eu-coord-1.log",
                        "captured_lines": 2,
                    }
                },
            },
        },
    )
    (collection / "input" / "query.sql").parent.mkdir(parents=True, exist_ok=True)
    (collection / "input" / "query.sql").write_text("select * from fdw_eu.events;\n")
    _write_json(node_dir / "plans" / "main.explain.json", _plan("Foreign Scan"))
    _write_json(
        node_dir / "execution_manifest.json",
        {
            "plan_file": "plans/main.explain.json",
            "timing": {"elapsed_seconds": "0.1"},
            "errors": [],
            "fdw_remote_plan_probe": {
                "enabled": False,
                "status": "skipped",
                "remote_sql_count": 0,
                "probes": [],
            },
        },
    )

    remote_document = {
        "Query Text": "DECLARE c1 CURSOR FOR SELECT tenant_id FROM events",
        "Plan": {
            "Node Type": "Custom Scan",
            "Custom Plan Provider": "Citus Adaptive",
            "Plan Rows": 10,
            "Plan Width": 32,
            "Actual Rows": 20,
            "Actual Total Time": 12.5,
            "Temp Read Blocks": 100,
            "Temp Written Blocks": 120,
            "Distributed Query": {
                "Job": {
                    "Task Count": 32,
                    "Tasks": [],
                }
            },
        },
    }
    internal_document = {
        "Query Text": "SELECT pg_catalog.pg_blocking_pids(pid)",
        "Plan": {
            "Node Type": "Function Scan",
            "Function Name": "pg_blocking_pids",
            "Plan Rows": 1,
            "Plan Width": 4,
            "Actual Rows": 0,
            "Actual Total Time": 0.2,
        },
    }
    auto_log.parent.mkdir(parents=True, exist_ok=True)
    auto_log.write_text(
        "\n".join(
            [
                "LOG:  duration: 12.500 ms  plan:",
                json.dumps(remote_document),
                "LOG:  duration: 0.200 ms  plan:",
                json.dumps(internal_document),
                "",
            ]
        ),
        encoding="utf-8",
    )

    out_dir = index_query_sweep(sweep_dir=sweep)

    query_rows = list(csv.DictReader((out_dir / "query_runs.csv").open()))
    plan_rows = list(csv.DictReader((out_dir / "plan_files.csv").open()))
    remote_rows = list(csv.DictReader((out_dir / "fdw_remote_plans.csv").open()))
    region_rows = list(csv.DictReader((out_dir / "region_fragments.csv").open()))
    node_rows = list(csv.DictReader((out_dir / "plan_nodes.csv").open()))

    assert len(query_rows) == 1
    assert query_rows[0]["remote_region_observed_count"] == "1"
    assert query_rows[0]["remote_region_count"] == "1"
    assert query_rows[0]["remote_region_evidence_completeness"] == "1.0"
    assert query_rows[0]["remote_region_task_count_sum"] == "32.0"
    assert query_rows[0]["regional_temp_evidence_region_count"] == "1"
    assert query_rows[0]["regional_temp_read_blocks_sum"] == "100.0"
    assert query_rows[0]["regional_temp_written_blocks_sum"] == "120.0"
    assert query_rows[0]["regional_spill_region_count"] == "1"
    assert query_rows[0]["regional_spill_present"] == "true"
    assert query_rows[0]["regional_remote_plan_count"] == "1"
    assert query_rows[0]["regional_internal_plan_count"] == "1"
    assert query_rows[0]["regional_plan_evidence_status"] == "available"
    assert query_rows[0]["worker_task_evidence_status"] == "missing_unexpected"

    assert [row["source_type"] for row in region_rows] == ["fdw_auto_explain_remote"]
    assert region_rows[0]["region_id"] == "eu"
    assert region_rows[0]["remote_citus_task_count"] == "32"

    assert len(remote_rows) == 1
    assert remote_rows[0]["auto_explain_document_role"] == "regional_remote_query"
    assert remote_rows[0]["fdw_region"] == "eu"
    assert remote_rows[0]["remote_sql_text"].startswith("DECLARE c1 CURSOR FOR")

    scopes = [row["plan_scope"] for row in plan_rows]
    assert scopes.count("fdw_auto_explain_remote") == 1
    assert scopes.count("fdw_auto_explain_internal") == 1
    assert all(row["source_type"] != "fdw_auto_explain_internal" for row in region_rows)
    assert any(row["plan_scope"] == "fdw_auto_explain_internal" for row in node_rows)
    assert any(row["plan_scope"] == "fdw_auto_explain_remote" for row in node_rows)
