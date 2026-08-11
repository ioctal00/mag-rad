#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INDEX = (
    ROOT.parent
    / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs"
    / "coordinator-pressure-intensity-probe-v1/_index"
)
DEFAULT_DISTINCT_INDEX = (
    ROOT.parent
    / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs"
    / "coordinator-distinct-pushdown-probe-v1/_index"
)

MEASURES = (
    "elapsed_seconds",
    "coordinator_main_plan_total_time_ms",
    "coordinator_foreign_scan_time_ms_sum",
    "coordinator_fanin_rows",
    "coordinator_fanin_bytes_estimated",
    "coordinator_final_rows",
    "coordinator_final_bytes_estimated",
    "analytics_rx_bytes_sum",
    "regional_coordinator_tx_bytes_sum",
    "worker_rx_bytes_sum",
    "worker_tx_bytes_sum",
    "worker_rx_bytes_cv",
    "worker_tx_bytes_cv",
    "coordinator_blocking_input_rows_sum",
    "coordinator_blocking_output_rows_sum",
    "coordinator_non_foreign_time_ms_proxy",
    "coordinator_temp_read_blocks",
    "coordinator_temp_written_blocks",
    "coordinator_hashagg_disk_usage_kb_max",
    "coordinator_sort_space_used_kb_max",
    "coordinator_peak_memory_usage_kb_max",
    "coordinator_sort_input_rows_sum",
    "coordinator_sort_output_rows_sum",
    "coordinator_aggregate_input_rows_sum",
    "coordinator_aggregate_output_rows_sum",
    "coordinator_join_input_rows_sum",
    "coordinator_join_output_rows_sum",
    "coordinator_unique_input_rows_sum",
    "coordinator_unique_output_rows_sum",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze paired GAC coordinator pressure probe evidence."
    )
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--distinct-index-dir", type=Path, default=DEFAULT_DISTINCT_INDEX)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "analysis/reports/coordinator-pressure-intensity-probe-v1",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(row: dict[str, str], name: str) -> float | None:
    value = row.get(name, "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def integer(row: dict[str, str], name: str) -> int | None:
    value = number(row, name)
    return int(value) if value is not None else None


def boolean(row: dict[str, str], name: str) -> bool:
    return row.get(name, "").strip().lower() == "true"


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def log2_smoothed_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    return math.log2((numerator + 1.0) / (denominator + 1.0))


def text_number(value: float | None, digits: int = 3) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def normalized_row(row: dict[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "query_run_id": row["query_run_id"],
        "corpus_cell_id": row.get("corpus_cell_id", ""),
        "pressure_pair_key": row.get("pressure_pair_key", ""),
        "pressure_level": row.get("pressure_level", ""),
        "coordinator_pressure_kind": row.get("coordinator_pressure_kind", ""),
        "coordinator_shape_id": row.get("coordinator_shape_id", ""),
        "physical_strategy_id": row.get("physical_strategy_id", ""),
        "runtime_config_id": row.get("runtime_config_id", ""),
        "template_id": row.get("template_id", ""),
        "execution_status": row.get("execution_status", ""),
        "result_multiset_sha256": row.get("result_multiset_sha256", ""),
        "result_row_count": integer(row, "result_row_count"),
        "result_output_byte_count": integer(row, "result_output_byte_count"),
        "coordinator_spill_present": boolean(row, "coordinator_spill_present"),
        "coordinator_disk_sort_count": integer(row, "coordinator_disk_sort_count"),
        "coordinator_hash_batches_max": integer(row, "coordinator_hash_batches_max"),
        "coordinator_sort_operator_count": integer(row, "coordinator_sort_operator_count"),
        "coordinator_aggregate_operator_count": integer(
            row, "coordinator_aggregate_operator_count"
        ),
        "coordinator_join_operator_count": integer(row, "coordinator_join_operator_count"),
        "coordinator_unique_operator_count": integer(
            row, "coordinator_unique_operator_count"
        ),
    }
    for measure in MEASURES:
        normalized[measure] = number(row, measure)
    return normalized


def pair_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["pressure_pair_key"]].append(row)

    pairs: list[dict[str, Any]] = []
    for pair_key, members in sorted(groups.items()):
        by_level = {row["pressure_level"]: row for row in members}
        if not {"mitigated", "stressed"} <= set(by_level):
            continue
        mitigated = by_level["mitigated"]
        stressed = by_level["stressed"]
        pair: dict[str, Any] = {
            "pressure_pair_key": pair_key,
            "coordinator_shape_id": stressed["coordinator_shape_id"],
            "coordinator_pressure_kind": stressed["coordinator_pressure_kind"],
            "mitigated_template_id": mitigated["template_id"],
            "stressed_template_id": stressed["template_id"],
            "result_hash_equal": bool(mitigated["result_multiset_sha256"])
            and mitigated["result_multiset_sha256"] == stressed["result_multiset_sha256"],
            "mitigated_result_rows": mitigated["result_row_count"],
            "stressed_result_rows": stressed["result_row_count"],
            "mitigated_spill": mitigated["coordinator_spill_present"],
            "stressed_spill": stressed["coordinator_spill_present"],
            "mitigated_disk_sort_count": mitigated["coordinator_disk_sort_count"],
            "stressed_disk_sort_count": stressed["coordinator_disk_sort_count"],
            "mitigated_hash_batches_max": mitigated["coordinator_hash_batches_max"],
            "stressed_hash_batches_max": stressed["coordinator_hash_batches_max"],
        }
        for measure in MEASURES:
            mitigated_value = mitigated[measure]
            stressed_value = stressed[measure]
            pair[f"mitigated_{measure}"] = mitigated_value
            pair[f"stressed_{measure}"] = stressed_value
            pair[f"{measure}_ratio"] = safe_ratio(stressed_value, mitigated_value)
            pair[f"{measure}_log2_ratio_smoothed"] = log2_smoothed_ratio(
                stressed_value, mitigated_value
            )
        pairs.append(pair)
    return pairs


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def pair_table(pairs: list[dict[str, Any]]) -> str:
    lines = [
        (
            "| Par | Oblik | Hash | T omjer | Fan-in redovi M/S | "
            "GAC RX omjer | Temp blokovi M/S | Hash batch M/S | Spill M/S |"
        ),
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in pairs:
        mitigated_temp = (row["mitigated_coordinator_temp_read_blocks"] or 0) + (
            row["mitigated_coordinator_temp_written_blocks"] or 0
        )
        stressed_temp = (row["stressed_coordinator_temp_read_blocks"] or 0) + (
            row["stressed_coordinator_temp_written_blocks"] or 0
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["pressure_pair_key"]),
                    str(row["coordinator_shape_id"]),
                    "da" if row["result_hash_equal"] else "ne",
                    text_number(row["elapsed_seconds_ratio"], 2),
                    (
                        f"{text_number(row['mitigated_coordinator_fanin_rows'], 0)}/"
                        f"{text_number(row['stressed_coordinator_fanin_rows'], 0)}"
                    ),
                    text_number(row["analytics_rx_bytes_sum_ratio"], 2),
                    f"{text_number(mitigated_temp, 0)}/{text_number(stressed_temp, 0)}",
                    (
                        f"{row['mitigated_hash_batches_max'] or 0}/"
                        f"{row['stressed_hash_batches_max'] or 0}"
                    ),
                    f"{row['mitigated_spill']}/{row['stressed_spill']}",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    source_rows = read_csv(args.index_dir / "query_runs.csv")
    rows = [
        normalized_row(row)
        for row in source_rows
        if row.get("corpus_id") == "coordinator-pressure-intensity-probe-v1"
    ]
    initial_distinct_rows = [
        row for row in rows if row["coordinator_shape_id"] == "global_distinct"
    ]
    distinct_correction_applied = (args.distinct_index_dir / "query_runs.csv").exists()
    if distinct_correction_applied:
        corrected_source_rows = read_csv(args.distinct_index_dir / "query_runs.csv")
        corrected_distinct_rows = [
            normalized_row(row)
            for row in corrected_source_rows
            if row.get("corpus_id") == "coordinator-distinct-pushdown-probe-v1"
        ]
        rows = [
            row for row in rows if row["coordinator_shape_id"] != "global_distinct"
        ] + corrected_distinct_rows
    pairs = pair_rows(rows)
    if len(rows) != 12 or len(pairs) != 6:
        raise ValueError(
            f"Expected 12 rows and 6 pairs, got {len(rows)} rows and {len(pairs)} pairs"
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "coordinator_scenario_rows.csv", rows)
    write_csv(args.out_dir / "coordinator_pair_contrasts.csv", pairs)
    if initial_distinct_rows:
        write_csv(
            args.out_dir / "coordinator_initial_distinct_rows.csv",
            initial_distinct_rows,
        )

    matching = sum(row["result_hash_equal"] for row in pairs)
    positive = [
        row
        for row in pairs
        if row["coordinator_shape_id"] != "tenant_point"
    ]
    fanin_reductions = [
        row["coordinator_fanin_rows_log2_ratio_smoothed"]
        for row in positive
        if row["coordinator_fanin_rows_log2_ratio_smoothed"] is not None
    ]
    elapsed_ratios = [
        row["elapsed_seconds_ratio"]
        for row in positive
        if row["elapsed_seconds_ratio"] is not None
    ]
    memory_pair = next(
        row for row in pairs if row["coordinator_shape_id"] == "memory_response"
    )
    findings = "\n".join(
        [
            f"- Upareni result signatures se podudaraju u {matching}/{len(pairs)} parova.",
            (
                "- Medijanski log2 omjer stressed/mitigated coordinator fan-in redova "
                f"za pozitivne parove je {statistics.median(fanin_reductions):.3f}."
            ),
            (
                "- Medijanski stressed/mitigated omjer trajanja pozitivnih parova je "
                f"{statistics.median(elapsed_ratios):.3f}."
            ),
            (
                "- Memory-response par je promijenio spill stanje "
                f"{memory_pair['mitigated_spill']} -> {memory_pair['stressed_spill']} "
                "uz isti SQL. HashAggregate je porastao sa "
                f"{memory_pair['mitigated_hash_batches_max']} na "
                f"{memory_pair['stressed_hash_batches_max']} batch-eva, uz "
                f"{text_number(memory_pair['stressed_coordinator_hashagg_disk_usage_kb_max'], 0)} "
                "kB prijavljene disk upotrebe."
            ),
            (
                "- Blocking input sume su operator-work proxy. Red može biti prebrojan "
                "u više uzastopnih blokirajućih etapa i zato nije mrežni byte count."
            ),
            (
                "- Korektivni regionalni GROUP BY DISTINCT par je "
                + ("primijenjen." if distinct_correction_applied else "još nije dostupan.")
            ),
        ]
    )
    readme = "\n".join(
        [
            "# Coordinator pressure intensity probe v1",
            "",
            "## Sažetak",
            "",
            findings,
            "",
            "## Upareni kontrasti",
            "",
            pair_table(pairs),
            "",
            "## Tumačenje",
            "",
            "Probe razdvaja pet fizičkih dimenzija coordinator pritiska:",
            "",
            "1. broj i procijenjeni bajtovi redova koji ulaze u GAC;",
            "2. količina rada blokirajućih operatora nad tim redovima;",
            "3. mrežni GAC RX i regionalni coordinator TX tokom query prozora;",
            "4. memory-response dokaz kroz temp blokove, disk sort i hash batches;",
            "5. ukupno trajanje kao ishod, ne kao jedina definicija pritiska.",
            "",
            "SQL shape i intervencijski identitet ostaju auditni kontekst. Budući "
            "model ne smije dobiti target-defining kolonu za isti target.",
            "",
            "## Izlazi",
            "",
            "- `coordinator_scenario_rows.csv`",
            "- `coordinator_pair_contrasts.csv`",
            "- `coordinator_initial_distinct_rows.csv`",
        ]
    )
    (args.out_dir / "README.md").write_text(readme + "\n", encoding="utf-8")
    print(args.out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
