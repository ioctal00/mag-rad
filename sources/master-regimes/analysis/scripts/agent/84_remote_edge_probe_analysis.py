#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOGICAL_ROOT = (
    ROOT.parent / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs"
)
DEFAULT_RUN_ID = "remote-edge-collection-probe-v1b"

QUERY_CONTEXT_FIELDS = (
    "corpus_cell_id",
    "template_id",
    "param_json",
    "runtime_config_id",
    "network_profile_id",
    "pressure_pair_key",
    "pressure_level",
    "remote_shape_id",
    "edge_stress_scope",
    "transfer_volume_level",
    "network_subblock",
    "elapsed_seconds",
    "result_signature_status",
    "result_multiset_sha256",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and summarize the remote edge collection probe."
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=DEFAULT_LOGICAL_ROOT / DEFAULT_RUN_ID / "_index",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "analysis/reports/remote-edge-collection-probe-v1",
    )
    parser.add_argument("--expected-edges-per-query", type=int, default=2)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def number(value: Any) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int:
    parsed = number(value)
    return int(parsed) if parsed is not None else 0


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalized_parameters(value: Any) -> str:
    parsed = json_mapping(value)
    if parsed:
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    return str(value or "").strip()


def measurement_for_edge(row: dict[str, Any]) -> dict[str, Any]:
    payload = json_mapping(row.get("network_measurement_json", ""))
    measurements = payload.get("measurements", {})
    if not isinstance(measurements, dict):
        return {}
    edge_id = str(row.get("edge_id", ""))
    source_cluster_id = str(row.get("source_cluster_id", ""))
    for measurement in measurements.values():
        if not isinstance(measurement, dict):
            continue
        if measurement.get("edge_id") == edge_id:
            return measurement
        if measurement.get("source_cluster_id") == source_cluster_id:
            return measurement
    return {}


def enrich_edges(
    query_rows: list[dict[str, str]],
    edge_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    by_query = {
        str(row.get("query_run_id", "")): row
        for row in query_rows
        if row.get("query_run_id")
    }
    result: list[dict[str, Any]] = []
    for edge in edge_rows:
        query = by_query.get(str(edge.get("query_run_id", "")), {})
        measurement = measurement_for_edge(edge)
        result.append(
            {
                **edge,
                **{
                    field: edge.get(field, "") or query.get(field, "")
                    for field in QUERY_CONTEXT_FIELDS
                },
                "parameter_key": normalized_parameters(
                    query.get("param_json", "")
                ),
                "calibration_status": (
                    "available" if measurement else "not_measured_for_edge"
                ),
                "calibration_rtt_median_ms": (
                    measurement.get("rtt_context", {}).get("rtt_median_ms", "")
                    if isinstance(measurement.get("rtt_context"), dict)
                    else ""
                ),
                "calibration_packet_loss_percent": (
                    measurement.get("rtt_context", {}).get(
                        "packet_loss_percent",
                        "",
                    )
                    if isinstance(measurement.get("rtt_context"), dict)
                    else ""
                ),
                "calibration_sender_bits_per_second": measurement.get(
                    "achieved_sender_bits_per_second",
                    "",
                ),
                "calibration_receiver_bits_per_second": measurement.get(
                    "achieved_receiver_bits_per_second",
                    "",
                ),
                "calibration_retransmits": measurement.get("retransmits", ""),
            }
        )
    return result


def completed_query_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    for row in rows:
        status = str(
            row.get("execution_status", "")
            or row.get("status", "")
            or row.get("query_status", "")
        ).lower()
        if status in {"completed", "success", "ok"}:
            result.append(row)
    return result


def query_edge_balance(
    query_rows: list[dict[str, str]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in edges:
        by_query[str(row.get("query_run_id", ""))].append(row)
    result = []
    for query in completed_query_rows(query_rows):
        query_run_id = str(query.get("query_run_id", ""))
        members = by_query.get(query_run_id, [])
        source_tx = [
            value
            for value in (
                number(row.get("query_window_source_tx_bytes")) for row in members
            )
            if value is not None
        ]
        destination_rx = [
            value
            for value in (
                number(row.get("query_window_destination_rx_bytes_shared"))
                for row in members
            )
            if value is not None
        ]
        summed_tx = sum(source_tx) if source_tx else None
        shared_rx = statistics.median(destination_rx) if destination_rx else None
        result.append(
            {
                "query_run_id": query_run_id,
                "corpus_cell_id": query.get("corpus_cell_id", ""),
                "edge_count": len(members),
                "source_clusters": ",".join(
                    sorted(
                        {
                            str(row.get("source_cluster_id", ""))
                            for row in members
                            if row.get("source_cluster_id")
                        }
                    )
                ),
                "source_tx_bytes_sum": summed_tx if summed_tx is not None else "",
                "gac_rx_bytes_shared": shared_rx if shared_rx is not None else "",
                "gac_rx_to_source_tx_ratio": (
                    shared_rx / summed_tx
                    if shared_rx is not None and summed_tx and summed_tx > 0
                    else ""
                ),
            }
        )
    return result


def baseline_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("source_cluster_id", "")),
        str(row.get("template_id", "")),
        str(row.get("parameter_key", "")),
    )


def safe_ratio(numerator: Any, denominator: Any) -> float | str:
    top = number(numerator)
    bottom = number(denominator)
    if top is None or bottom is None or bottom <= 0:
        return ""
    return top / bottom


def intervention_contrasts(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baselines: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in edges:
        if not truthy(row.get("network_intervention_targeted")) and (
            (number(row.get("configured_delay_ms")) or 0) == 0
            and (number(row.get("configured_bandwidth_mbit")) or 0) == 0
            and str(row.get("network_subblock", "")) != "fetch_only"
        ):
            baselines[baseline_key(row)].append(row)

    result: list[dict[str, Any]] = []
    for stressed in edges:
        if not truthy(stressed.get("network_intervention_targeted")):
            continue
        candidates = baselines.get(baseline_key(stressed), [])
        if not candidates:
            continue
        baseline = candidates[0]
        result.append(
            {
                "contrast_kind": str(stressed.get("network_subblock", "")),
                "source_cluster_id": stressed.get("source_cluster_id", ""),
                "template_id": stressed.get("template_id", ""),
                "parameter_key": stressed.get("parameter_key", ""),
                "baseline_query_run_id": baseline.get("query_run_id", ""),
                "stressed_query_run_id": stressed.get("query_run_id", ""),
                "configured_delay_ms": stressed.get("configured_delay_ms", ""),
                "configured_jitter_ms": stressed.get("configured_jitter_ms", ""),
                "configured_loss_percent": stressed.get(
                    "configured_loss_percent",
                    "",
                ),
                "configured_bandwidth_mbit": stressed.get(
                    "configured_bandwidth_mbit",
                    "",
                ),
                "rtt_ratio": safe_ratio(
                    stressed.get("rtt_context_median_ms"),
                    baseline.get("rtt_context_median_ms"),
                ),
                "elapsed_ratio": safe_ratio(
                    stressed.get("elapsed_seconds"),
                    baseline.get("elapsed_seconds"),
                ),
                "foreign_scan_time_ratio": safe_ratio(
                    stressed.get("foreign_scan_time_ms_sum"),
                    baseline.get("foreign_scan_time_ms_sum"),
                ),
                "source_tx_bytes_ratio": safe_ratio(
                    stressed.get("query_window_source_tx_bytes"),
                    baseline.get("query_window_source_tx_bytes"),
                ),
                "remote_bytes_proxy_ratio": safe_ratio(
                    stressed.get("remote_bytes_proxy"),
                    baseline.get("remote_bytes_proxy"),
                ),
                "calibration_receiver_mbit": (
                    (number(stressed.get("calibration_receiver_bits_per_second")) or 0)
                    / 1_000_000
                    if number(stressed.get("calibration_receiver_bits_per_second"))
                    is not None
                    else ""
                ),
            }
        )

    fetch_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in edges:
        if str(row.get("network_subblock", "")) == "fetch_only":
            fetch_groups[baseline_key(row)].append(row)
    for key, members in fetch_groups.items():
        ordered = sorted(
            members,
            key=lambda row: number(row.get("fetch_size")) or math.inf,
        )
        if len(ordered) < 2:
            continue
        small, large = ordered[0], ordered[-1]
        if small.get("fetch_size") == large.get("fetch_size"):
            continue
        result.append(
            {
                "contrast_kind": "fetch_only",
                "source_cluster_id": key[0],
                "template_id": key[1],
                "parameter_key": key[2],
                "baseline_query_run_id": large.get("query_run_id", ""),
                "stressed_query_run_id": small.get("query_run_id", ""),
                "configured_delay_ms": 0,
                "configured_jitter_ms": 0,
                "configured_loss_percent": 0,
                "configured_bandwidth_mbit": 0,
                "rtt_ratio": safe_ratio(
                    small.get("rtt_context_median_ms"),
                    large.get("rtt_context_median_ms"),
                ),
                "elapsed_ratio": safe_ratio(
                    small.get("elapsed_seconds"),
                    large.get("elapsed_seconds"),
                ),
                "foreign_scan_time_ratio": safe_ratio(
                    small.get("foreign_scan_time_ms_sum"),
                    large.get("foreign_scan_time_ms_sum"),
                ),
                "source_tx_bytes_ratio": safe_ratio(
                    small.get("query_window_source_tx_bytes"),
                    large.get("query_window_source_tx_bytes"),
                ),
                "remote_bytes_proxy_ratio": safe_ratio(
                    small.get("remote_bytes_proxy"),
                    large.get("remote_bytes_proxy"),
                ),
                "small_fetch_size": small.get("fetch_size", ""),
                "large_fetch_size": large.get("fetch_size", ""),
                "estimated_fetch_cycles_ratio": safe_ratio(
                    small.get("estimated_fetch_cycles"),
                    large.get("estimated_fetch_cycles"),
                ),
                "calibration_receiver_mbit": "",
            }
        )
    return result


def gate_row(
    gate_id: str,
    *,
    passed: bool,
    observed: Any,
    expected: Any,
    severity: str = "blocking",
    note: str = "",
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "status": "PASS" if passed else "FAIL",
        "severity": severity,
        "observed": observed,
        "expected": expected,
        "note": note,
    }


def collection_gates(
    query_rows: list[dict[str, str]],
    edges: list[dict[str, Any]],
    *,
    expected_edges: int,
) -> list[dict[str, Any]]:
    completed = completed_query_rows(query_rows)
    completed_ids = {str(row.get("query_run_id", "")) for row in completed}
    relevant_edges = [
        row for row in edges if str(row.get("query_run_id", "")) in completed_ids
    ]
    counts = Counter(str(row.get("query_run_id", "")) for row in relevant_edges)
    duplicate_count = sum(
        count - 1
        for count in Counter(
            (
                str(row.get("query_run_id", "")),
                str(row.get("edge_id", "")),
            )
            for row in relevant_edges
        ).values()
        if count > 1
    )
    cardinality_ok = sum(
        counts.get(query_run_id, 0) == expected_edges
        for query_run_id in completed_ids
    )
    core_fields = (
        "edge_id",
        "source_cluster_id",
        "destination_gac_id",
        "foreign_schema_id",
        "foreign_server_id",
        "remote_sql_fingerprint",
        "remote_plan_fingerprint_count",
        "remote_rows",
        "remote_tuple_width",
        "remote_bytes_proxy",
        "foreign_scan_time_ms_sum",
        "regional_plan_time_ms_sum",
        "fetch_size",
        "estimated_fetch_cycles",
    )
    context_fields = (
        "rtt_context_median_ms",
        "rtt_context_max_ms",
        "route_device",
        "route_source_ip",
        "query_window_source_tx_bytes",
        "query_window_source_tx_packets",
    )
    core_complete = sum(
        all(str(row.get(field, "")).strip() for field in core_fields)
        for row in relevant_edges
    )
    context_complete = sum(
        all(str(row.get(field, "")).strip() for field in context_fields)
        for row in relevant_edges
    )
    targeted = [
        row for row in relevant_edges if truthy(row.get("network_intervention_targeted"))
    ]
    targeted_qdisc = sum(
        str(row.get("query_window_qdisc_bytes", "")).strip() != ""
        for row in targeted
    )
    target_scope_correct = sum(
        (
            str(row.get("edge_stress_scope", "")) == "both"
            or str(row.get("edge_stress_scope", ""))
            == str(row.get("source_cluster_id", ""))
        )
        for row in targeted
    )
    targeted_calibration = sum(
        str(row.get("calibration_status", "")) == "available" for row in targeted
    )
    signature_complete = sum(
        str(row.get("result_signature_status", "")).lower()
        in {"completed", "available", "ok"}
        for row in completed
    )
    return [
        gate_row(
            "completed_query_count",
            passed=bool(completed),
            observed=len(completed),
            expected=">0",
        ),
        gate_row(
            "edge_key_uniqueness",
            passed=duplicate_count == 0,
            observed=duplicate_count,
            expected=0,
        ),
        gate_row(
            "edge_cardinality",
            passed=cardinality_ok == len(completed),
            observed=f"{cardinality_ok}/{len(completed)}",
            expected=f"{expected_edges} edges for every completed query",
        ),
        gate_row(
            "core_edge_evidence",
            passed=core_complete == len(relevant_edges),
            observed=f"{core_complete}/{len(relevant_edges)}",
            expected="all normalized edge evidence fields available",
        ),
        gate_row(
            "edge_context",
            passed=context_complete == len(relevant_edges),
            observed=f"{context_complete}/{len(relevant_edges)}",
            expected="all RTT, route and query-window source counters available",
        ),
        gate_row(
            "intervention_target_scope",
            passed=target_scope_correct == len(targeted),
            observed=f"{target_scope_correct}/{len(targeted)}",
            expected="only configured region edges marked targeted",
        ),
        gate_row(
            "targeted_qdisc_accounting",
            passed=targeted_qdisc == len(targeted),
            observed=f"{targeted_qdisc}/{len(targeted)}",
            expected="qdisc delta available on every targeted edge",
        ),
        gate_row(
            "targeted_profile_calibration",
            passed=targeted_calibration == len(targeted),
            observed=f"{targeted_calibration}/{len(targeted)}",
            expected="iperf/ping calibration available on every targeted edge",
        ),
        gate_row(
            "result_signature",
            passed=signature_complete == len(completed),
            observed=f"{signature_complete}/{len(completed)}",
            expected="result signature available for every completed query",
        ),
    ]


def physical_checks(
    contrasts: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind in ("delay_only", "bandwidth_only", "combined", "fetch_only"):
        members = [row for row in contrasts if row.get("contrast_kind") == kind]
        if not members:
            rows.append(
                gate_row(
                    f"physical_{kind}",
                    passed=False,
                    observed=0,
                    expected="at least one evaluable contrast",
                    severity="diagnostic",
                    note="No matched baseline; does not invalidate the collector schema.",
                )
            )
            continue
        if kind == "delay_only":
            values = [
                number(row.get("rtt_ratio"))
                for row in members
                if number(row.get("rtt_ratio")) is not None
            ]
            passed = bool(values) and statistics.median(values) > 1.5
            observed = statistics.median(values) if values else ""
            expected = "median targeted RTT ratio > 1.5"
        elif kind == "bandwidth_only":
            values = [
                number(row.get("calibration_receiver_mbit"))
                for row in members
                if number(row.get("calibration_receiver_mbit")) is not None
            ]
            caps = [
                number(row.get("configured_bandwidth_mbit"))
                for row in members
                if number(row.get("configured_bandwidth_mbit")) is not None
            ]
            observed = statistics.median(values) if values else ""
            cap = statistics.median(caps) if caps else None
            passed = bool(values) and cap is not None and 0 < observed <= cap * 1.5
            expected = "median achieved receiver throughput <= 1.5 x configured cap"
        elif kind == "combined":
            rtt = [
                number(row.get("rtt_ratio"))
                for row in members
                if number(row.get("rtt_ratio")) is not None
            ]
            throughput = [
                number(row.get("calibration_receiver_mbit"))
                for row in members
                if number(row.get("calibration_receiver_mbit")) is not None
            ]
            observed = json.dumps(
                {
                    "median_rtt_ratio": statistics.median(rtt) if rtt else None,
                    "median_receiver_mbit": (
                        statistics.median(throughput) if throughput else None
                    ),
                },
                sort_keys=True,
            )
            passed = bool(rtt) and statistics.median(rtt) > 1.5 and bool(throughput)
            expected = "delay and bandwidth response both observable"
        else:
            values = [
                number(row.get("estimated_fetch_cycles_ratio"))
                for row in members
                if number(row.get("estimated_fetch_cycles_ratio")) is not None
            ]
            observed = statistics.median(values) if values else ""
            passed = bool(values) and statistics.median(values) > 1
            expected = "smaller fetch size yields more estimated fetch cycles"
        rows.append(
            gate_row(
                f"physical_{kind}",
                passed=passed,
                observed=observed,
                expected=expected,
                severity="diagnostic",
            )
        )

    raw_baseline = [
        row
        for row in edges
        if row.get("remote_shape_id") == "raw_wide"
        and row.get("network_subblock") == "transfer_volume"
    ]
    by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_baseline:
        by_edge[str(row.get("source_cluster_id", ""))].append(row)
    ratios = []
    for members in by_edge.values():
        ordered = sorted(
            members,
            key=lambda row: number(row.get("remote_bytes_proxy")) or 0,
        )
        if len(ordered) >= 2:
            ratio = safe_ratio(
                ordered[-1].get("remote_bytes_proxy"),
                ordered[0].get("remote_bytes_proxy"),
            )
            if ratio != "":
                ratios.append(float(ratio))
    rows.append(
        gate_row(
            "physical_transfer_volume",
            passed=bool(ratios) and statistics.median(ratios) > 1,
            observed=statistics.median(ratios) if ratios else "",
            expected="large transfer produces larger remote byte proxy",
            severity="diagnostic",
        )
    )
    return rows


def markdown_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Provjera | Status | Vrsta | Opaženo | Očekivano |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["gate_id"]),
                    str(row["status"]),
                    str(row["severity"]),
                    str(row["observed"]),
                    str(row["expected"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    query_rows = read_csv(args.index_dir / "query_runs.csv")
    edge_rows = read_csv(args.index_dir / "remote_edge_observations.csv")
    enriched = enrich_edges(query_rows, edge_rows)
    balances = query_edge_balance(query_rows, enriched)
    contrasts = intervention_contrasts(enriched)
    gates = collection_gates(
        query_rows,
        enriched,
        expected_edges=args.expected_edges_per_query,
    )
    diagnostics = physical_checks(contrasts, enriched)
    all_checks = [*gates, *diagnostics]
    blocking_failures = [
        row
        for row in gates
        if row["severity"] == "blocking" and row["status"] != "PASS"
    ]
    diagnostic_failures = [
        row
        for row in diagnostics
        if row["status"] != "PASS"
    ]
    status = (
        "GO"
        if not blocking_failures
        else "NO_GO"
    )
    physical_status = (
        "CONFIRMED"
        if not diagnostic_failures
        else "MIXED"
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    enriched_fields = list(enriched[0]) if enriched else []
    write_csv(
        args.out_dir / "edge_observations_enriched.csv",
        enriched,
        enriched_fields,
    )
    write_csv(
        args.out_dir / "query_edge_balance.csv",
        balances,
        list(balances[0]) if balances else ["query_run_id"],
    )
    contrast_fields = list(contrasts[0]) if contrasts else ["contrast_kind"]
    write_csv(
        args.out_dir / "intervention_contrasts.csv",
        contrasts,
        contrast_fields,
    )
    write_csv(
        args.out_dir / "collection_gate.csv",
        all_checks,
        ["gate_id", "status", "severity", "observed", "expected", "note"],
    )
    summary = {
        "contract_version": "remote-edge-probe-analysis-v1",
        "index_dir": str(args.index_dir.resolve()),
        "completed_query_count": len(completed_query_rows(query_rows)),
        "edge_observation_count": len(enriched),
        "intervention_contrast_count": len(contrasts),
        "collection_gate": status,
        "physical_response_status": physical_status,
        "blocking_failure_count": len(blocking_failures),
        "diagnostic_failure_count": len(diagnostic_failures),
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "README.md").write_text(
        "\n".join(
            [
                "# Remote edge collection probe",
                "",
                f"- Collection gate: **{status}**",
                f"- Physical response: **{physical_status}**",
                f"- Completed queries: {summary['completed_query_count']}",
                f"- Edge observations: {len(enriched)}",
                f"- Matched intervention contrasts: {len(contrasts)}",
                "",
                "Collection gate provjerava da li svaki završeni globalni upit ima",
                "jedinstvene EU->GAC i US->GAC redove sa plan, row-flow, fetch, RTT",
                "i query-window mrežnim dokazom. Physical response je odvojena",
                "dijagnostika kontrolisanih intervencija i ne mijenja schema gate.",
                "",
                "## Provjere",
                "",
                markdown_table(all_checks),
                "",
                "## Granice",
                "",
                "- RTT je kontekstualna sonda prije i poslije upita, ne RTT SQL socket-a.",
                "- Source TX je route-interface delta; destination RX je GAC node-globalna delta.",
                "- TCP retransmit je node-globalni kontekst i nije edge-čist pokazatelj.",
                "- `remote_bytes_proxy` koristi redove i plan width; nije packet capture.",
                "- `iperf3` kalibracija se izvršava jednom po mrežnom profilu, izvan SQL prozora.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(args.out_dir / "README.md")
    return 0 if status == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
