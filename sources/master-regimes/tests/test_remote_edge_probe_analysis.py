from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "analysis/scripts/agent/84_remote_edge_probe_analysis.py"
)
SPEC = importlib.util.spec_from_file_location("remote_edge_probe_analysis", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _edge(region: str, *, targeted: bool) -> dict[str, str]:
    measurement = {
        "measurements": {
            f"{region}-coord-1": {
                "edge_id": f"{region}->eu-analytics-1",
                "source_cluster_id": region,
                "rtt_context": {
                    "rtt_median_ms": 80 if targeted else 1,
                    "packet_loss_percent": 0,
                },
                "achieved_sender_bits_per_second": 9_000_000,
                "achieved_receiver_bits_per_second": 8_500_000,
                "retransmits": 0,
            }
        }
    }
    return {
        "query_run_id": "query-1",
        "edge_id": f"{region}->eu-analytics-1",
        "source_cluster_id": region,
        "destination_gac_id": "eu-analytics-1",
        "source_node": f"{region}-coord-1",
        "destination_node": "eu-analytics-1",
        "foreign_schema_id": f"fdw_{region}",
        "foreign_server_id": f"{region}_citus",
        "remote_sql_fingerprint": f"sql-{region}",
        "remote_plan_fingerprint_count": "1",
        "remote_rows": "100",
        "remote_tuple_width": "16",
        "remote_bytes_proxy": "1600",
        "foreign_scan_time_ms_sum": "20",
        "regional_plan_time_ms_sum": "10",
        "fetch_size": "100",
        "estimated_fetch_cycles": "1",
        "rtt_context_median_ms": "80" if targeted else "1",
        "rtt_context_max_ms": "84" if targeted else "2",
        "route_device": "ens7",
        "route_source_ip": f"10.0.0.{11 if region == 'eu' else 21}",
        "query_window_source_tx_bytes": "2000",
        "query_window_source_tx_packets": "20",
        "query_window_qdisc_bytes": "1800" if targeted else "",
        "network_intervention_targeted": "true" if targeted else "false",
        "configured_delay_ms": "80" if targeted else "0",
        "configured_bandwidth_mbit": "10" if targeted else "0",
        "network_measurement_json": json.dumps(measurement),
    }


def test_enrichment_and_collection_gate_keep_edge_intervention_local() -> None:
    queries = [
        {
            "query_run_id": "query-1",
            "execution_status": "completed",
            "corpus_cell_id": "edge_eu_combined_raw_wide",
            "template_id": "raw_wide",
            "param_json": '{"limit_k":10000}',
            "edge_stress_scope": "eu",
            "network_subblock": "combined",
            "result_signature_status": "completed",
        }
    ]
    edges = [_edge("eu", targeted=True), _edge("us", targeted=False)]

    enriched = MODULE.enrich_edges(queries, edges)
    gates = MODULE.collection_gates(queries, enriched, expected_edges=2)
    by_id = {row["gate_id"]: row for row in gates}
    by_region = {row["source_cluster_id"]: row for row in enriched}

    assert by_region["eu"]["calibration_status"] == "available"
    assert by_region["us"]["calibration_status"] == "available"
    assert by_region["eu"]["network_intervention_targeted"] == "true"
    assert by_region["us"]["network_intervention_targeted"] == "false"
    assert by_id["edge_key_uniqueness"]["status"] == "PASS"
    assert by_id["edge_cardinality"]["status"] == "PASS"
    assert by_id["core_edge_evidence"]["status"] == "PASS"
    assert by_id["edge_context"]["status"] == "PASS"
    assert by_id["intervention_target_scope"]["status"] == "PASS"
    assert by_id["targeted_qdisc_accounting"]["status"] == "PASS"
    assert by_id["targeted_profile_calibration"]["status"] == "PASS"
