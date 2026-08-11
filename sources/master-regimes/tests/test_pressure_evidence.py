from __future__ import annotations

import json

import pandas as pd

from master_regimes.pressure_evidence import (
    PRESSURE_EVIDENCE_CONTRACT,
    build_pressure_evidence,
)


def test_pressure_evidence_is_multi_label_not_membership_sum() -> None:
    frame = pd.DataFrame(
        [
            {
                "query_run_id": "q_low",
                "remote_path_share": 0.0,
                "remote_to_final_rows_ratio": 1.0,
                "wan_output_to_final_rows_ratio": 1.0,
                "global_group_merge_ratio": 1.0,
                "drf_bytes_proxy": 1.0,
                "spill_per_wan_mb": 0.0,
                "temp_blocks_per_wan_row": 0.0,
                "temp_blocks_per_final_row": 0.0,
                "remote_region_rows_isf": 1.0,
                "worker_task_scan_rows_isf": 1.0,
                "worker_task_scan_actual_rows_max_share": 0.01,
                "task_count_to_shard_count_ratio": 0.1,
                "active_task_share": 0.1,
                "citus_repartition_query": 0,
                "root_rows_estimate_error_log": 0.0,
                "foreign_scan_rows_estimate_error_log": 0.0,
                "aggregate_rows_estimate_error_log": 0.0,
                "remote_root_rows_estimate_error_log": 0.0,
            },
            {
                "query_run_id": "q_mid",
                "remote_path_share": 0.5,
                "remote_to_final_rows_ratio": 100.0,
                "wan_output_to_final_rows_ratio": 100.0,
                "global_group_merge_ratio": 100.0,
                "drf_bytes_proxy": 10.0,
                "spill_per_wan_mb": 2.0,
                "temp_blocks_per_wan_row": 0.1,
                "temp_blocks_per_final_row": 100.0,
                "remote_region_rows_isf": 1.5,
                "worker_task_scan_rows_isf": 1.5,
                "worker_task_scan_actual_rows_max_share": 0.05,
                "task_count_to_shard_count_ratio": 0.5,
                "active_task_share": 0.5,
                "citus_repartition_query": 0,
                "root_rows_estimate_error_log": 1.0,
                "foreign_scan_rows_estimate_error_log": -1.0,
                "aggregate_rows_estimate_error_log": 1.0,
                "remote_root_rows_estimate_error_log": -1.0,
            },
            {
                "query_run_id": "q_high",
                "remote_path_share": 1.0,
                "remote_to_final_rows_ratio": 1_000_000.0,
                "wan_output_to_final_rows_ratio": 1_000_000.0,
                "global_group_merge_ratio": 1_000_000.0,
                "drf_bytes_proxy": 10_000.0,
                "spill_per_wan_mb": 100.0,
                "temp_blocks_per_wan_row": 10.0,
                "temp_blocks_per_final_row": 1_000_000.0,
                "remote_region_rows_isf": 8.0,
                "worker_task_scan_rows_isf": 9.0,
                "worker_task_scan_actual_rows_max_share": 0.6,
                "task_count_to_shard_count_ratio": 1.0,
                "active_task_share": 1.0,
                "citus_repartition_query": 1,
                "root_rows_estimate_error_log": 5.0,
                "foreign_scan_rows_estimate_error_log": -6.0,
                "aggregate_rows_estimate_error_log": 4.0,
                "remote_root_rows_estimate_error_log": -5.0,
            },
        ]
    )

    evidence, wide = build_pressure_evidence(frame)

    high = evidence[evidence["query_run_id"].eq("q_high")]
    confirmed = set(high[high["pressure_status"].eq("confirmed")]["pressure_id"])
    assert {"remote_fanin", "gac_finalization", "spill", "skew", "topology_task"}.issubset(
        confirmed
    )
    assert high["pressure_score"].sum() > 1.0
    assert set(wide.columns).issuperset(
        {"remote_fanin_score", "spill_score", "skew_score", "estimate_error_score"}
    )


def test_pressure_evidence_records_contract_and_feature_json() -> None:
    frame = pd.DataFrame(
        [
            {
                "query_run_id": "q1",
                "remote_path_share": 1.0,
                "remote_to_final_rows_ratio": 10.0,
                "wan_output_to_final_rows_ratio": 10.0,
            }
        ]
    )

    evidence, _ = build_pressure_evidence(frame)
    remote = evidence[evidence["pressure_id"].eq("remote_fanin")].iloc[0]
    missing_spill = evidence[evidence["pressure_id"].eq("spill")].iloc[0]

    assert remote["pressure_contract"] == PRESSURE_EVIDENCE_CONTRACT
    assert remote["pressure_model_role"] == "posthoc_feature_first_evidence_not_clustering_input"
    assert json.loads(remote["feature_evidence_json"])[0]["feature"] == "remote_path_share"
    assert missing_spill["pressure_status"] == "not_measured"
