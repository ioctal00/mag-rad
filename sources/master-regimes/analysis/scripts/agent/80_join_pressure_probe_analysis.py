#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOGICAL_ROOT = (
    ROOT.parent / "master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze paired colocated/repartition JOIN probe evidence."
    )
    parser.add_argument(
        "--direct-index",
        type=Path,
        default=DEFAULT_LOGICAL_ROOT / "join-pressure-intensity-probe-v1-direct-v2/_index",
    )
    parser.add_argument(
        "--planner-control-index",
        type=Path,
        default=DEFAULT_LOGICAL_ROOT / "join-pressure-intensity-probe-v1/_index",
    )
    parser.add_argument(
        "--gac-index",
        type=Path,
        default=DEFAULT_LOGICAL_ROOT / "join-pressure-intensity-probe-v1-forced-gac-v2/_index",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "analysis/reports/join-pressure-intensity-probe-v1",
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


def text_number(value: float | None, digits: int = 3) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def strategy(cell_id: str) -> str:
    if "reference" in cell_id:
        return "reference_control"
    if "repartition" in cell_id:
        return "repartition"
    if "colocated" in cell_id:
        return "colocated"
    return "other"


def level(cell_id: str) -> str:
    for candidate in ("router", "low", "medium", "high"):
        if f"_{candidate}_" in f"_{cell_id}_":
            return candidate
    return "control"


def normalized_row(row: dict[str, str], path: str) -> dict[str, Any]:
    remote_map_merge = integer(row, "remote_citus_map_merge_job_count_sum") or 0
    direct_map_merge = integer(row, "citus_map_merge_job_count") or 0
    remote_map_tasks = integer(row, "remote_citus_dependent_map_task_count_sum") or 0
    direct_map_tasks = integer(row, "citus_dependent_map_task_count_sum") or 0
    remote_merge_tasks = integer(row, "remote_citus_dependent_merge_task_count_sum") or 0
    direct_merge_tasks = integer(row, "citus_dependent_merge_task_count_sum") or 0
    return {
        "execution_path": path,
        "query_run_id": row["query_run_id"],
        "corpus_cell_id": row["corpus_cell_id"],
        "pressure_pair_key": row.get("pressure_pair_key", ""),
        "intensity_level": level(row["corpus_cell_id"]),
        "join_strategy": strategy(row["corpus_cell_id"]),
        "pressure_level": row.get("pressure_level", ""),
        "elapsed_seconds": number(row, "elapsed_seconds"),
        "result_row_count": integer(row, "result_row_count"),
        "result_output_byte_count": integer(row, "result_output_byte_count"),
        "result_multiset_sha256": row.get("result_multiset_sha256", ""),
        "worker_rx_bytes_sum": integer(row, "worker_rx_bytes_sum"),
        "worker_tx_bytes_sum": integer(row, "worker_tx_bytes_sum"),
        "worker_rx_bytes_cv": number(row, "worker_rx_bytes_cv"),
        "worker_tx_bytes_cv": number(row, "worker_tx_bytes_cv"),
        "repartition_confirmed": boolean(row, "citus_repartition_observed_v2"),
        "map_merge_job_count": max(remote_map_merge, direct_map_merge),
        "map_task_count": max(remote_map_tasks, direct_map_tasks),
        "merge_task_count": max(remote_merge_tasks, direct_merge_tasks),
        "citus_task_count": max(
            integer(row, "remote_region_task_count_sum") or 0,
            integer(row, "citus_top_task_count") or 0,
            integer(row, "task_count") or 0,
        ),
        "tasks_shown_none": max(
            integer(row, "remote_citus_tasks_shown_none_count") or 0,
            int(boolean(row, "citus_tasks_shown_none")),
        ),
        "worker_task_plan_count": integer(row, "worker_task_plan_count") or 0,
        "worker_task_scan_rows": number(row, "worker_task_scan_actual_rows_sum"),
        "main_temp_blocks": (
            (integer(row, "temp_blks_read_sum") or 0) + (integer(row, "temp_blks_written_sum") or 0)
        ),
        "worker_task_temp_blocks": (
            (integer(row, "worker_task_temp_read_sum") or 0)
            + (integer(row, "worker_task_temp_written_sum") or 0)
        ),
        "plan_locality": row.get("remote_citus_dominant_plan_locality_class")
        or row.get("citus_plan_locality_class", ""),
    }


def load_rows(index_dir: Path, path: str) -> list[dict[str, Any]]:
    rows = read_csv(index_dir / "execution_features.csv")
    if path == "direct_coordinator":
        rows = [row for row in rows if row["corpus_cell_id"].startswith("join_direct_")]
    elif path == "gac_default_planner_control":
        rows = [row for row in rows if row["corpus_cell_id"].startswith("join_gac_")]
    return [normalized_row(row, path) for row in rows]


def pair_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["join_strategy"] not in {"colocated", "repartition"}:
            continue
        groups[(row["execution_path"], row["pressure_pair_key"])].append(row)

    result: list[dict[str, Any]] = []
    for (path, pair_key), members in sorted(groups.items()):
        by_strategy = {row["join_strategy"]: row for row in members}
        if set(by_strategy) != {"colocated", "repartition"}:
            continue
        colocated = by_strategy["colocated"]
        repartition = by_strategy["repartition"]
        elapsed_ratio = safe_ratio(repartition["elapsed_seconds"], colocated["elapsed_seconds"])
        worker_tx_ratio = safe_ratio(
            repartition["worker_tx_bytes_sum"], colocated["worker_tx_bytes_sum"]
        )
        result.append(
            {
                "execution_path": path,
                "pressure_pair_key": pair_key,
                "intensity_level": colocated["intensity_level"],
                "result_hash_equal": bool(colocated["result_multiset_sha256"])
                and colocated["result_multiset_sha256"] == repartition["result_multiset_sha256"],
                "colocated_elapsed_seconds": colocated["elapsed_seconds"],
                "repartition_elapsed_seconds": repartition["elapsed_seconds"],
                "elapsed_ratio": elapsed_ratio,
                "log_elapsed_ratio": (
                    math.log(elapsed_ratio) if elapsed_ratio and elapsed_ratio > 0 else None
                ),
                "colocated_worker_tx_bytes": colocated["worker_tx_bytes_sum"],
                "repartition_worker_tx_bytes": repartition["worker_tx_bytes_sum"],
                "worker_tx_ratio": worker_tx_ratio,
                "worker_tx_excess_bytes": (
                    repartition["worker_tx_bytes_sum"] - colocated["worker_tx_bytes_sum"]
                    if repartition["worker_tx_bytes_sum"] is not None
                    and colocated["worker_tx_bytes_sum"] is not None
                    else None
                ),
                "result_output_byte_count": repartition["result_output_byte_count"],
                "worker_tx_excess_per_result_byte": safe_ratio(
                    (
                        repartition["worker_tx_bytes_sum"] - colocated["worker_tx_bytes_sum"]
                        if repartition["worker_tx_bytes_sum"] is not None
                        and colocated["worker_tx_bytes_sum"] is not None
                        else None
                    ),
                    repartition["result_output_byte_count"],
                ),
                "colocated_main_temp_blocks": colocated["main_temp_blocks"],
                "repartition_main_temp_blocks": repartition["main_temp_blocks"],
                "colocated_worker_task_temp_blocks": colocated["worker_task_temp_blocks"],
                "repartition_worker_task_temp_blocks": (
                    repartition["worker_task_temp_blocks"]
                    if repartition["worker_task_plan_count"] > 0
                    else None
                ),
                "repartition_confirmed": repartition["repartition_confirmed"],
                "map_merge_job_count": repartition["map_merge_job_count"],
                "map_task_count": repartition["map_task_count"],
                "merge_task_count": repartition["merge_task_count"],
                "colocated_worker_task_plan_count": colocated["worker_task_plan_count"],
                "repartition_worker_task_plan_count": repartition["worker_task_plan_count"],
                "repartition_tasks_shown_none": repartition["tasks_shown_none"],
            }
        )
    return result


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(pairs: list[dict[str, Any]]) -> str:
    lines = [
        (
            "| Putanja | Nivo | T colocated (s) | T repartition (s) | "
            "Omjer T | Omjer worker TX | MapMerge | Task planovi C/R |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in pairs:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["execution_path"]),
                    str(row["intensity_level"]),
                    text_number(row["colocated_elapsed_seconds"]),
                    text_number(row["repartition_elapsed_seconds"]),
                    text_number(row["elapsed_ratio"], 2),
                    text_number(row["worker_tx_ratio"], 2),
                    str(row["map_merge_job_count"]),
                    (
                        f"{row['colocated_worker_task_plan_count']}/"
                        f"{row['repartition_worker_task_plan_count']}"
                    ),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    direct = load_rows(args.direct_index, "direct_coordinator")
    planner_control = load_rows(
        args.planner_control_index,
        "gac_default_planner_control",
    )
    gac = load_rows(args.gac_index, "gac_remote_join_pushdown")
    rows = [*direct, *planner_control, *gac]
    pairs = pair_rows(rows)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "join_scenario_rows.csv", rows)
    write_csv(args.out_dir / "join_pair_contrasts.csv", pairs)

    planner_repartition = sum(row["repartition_confirmed"] for row in planner_control)
    valid_pairs = [
        row
        for row in pairs
        if row["execution_path"] in {"direct_coordinator", "gac_remote_join_pushdown"}
    ]
    matching_results = sum(row["result_hash_equal"] for row in valid_pairs)
    confirmed_repartition = sum(row["repartition_confirmed"] for row in valid_pairs)
    planner_candidates = sum(row["join_strategy"] == "repartition" for row in planner_control)
    findings = "\n".join(
        [
            (f"- Result signatures match in {matching_results}/{len(valid_pairs)} valid pairs."),
            (
                "- Repartition/MapMerge is confirmed in "
                f"{confirmed_repartition}/{len(valid_pairs)} stressed pair "
                "members."
            ),
            (
                "- Default GAC planning exposed repartition in "
                f"{planner_repartition}/{planner_candidates} candidate rows. "
                "Those rows are planner controls, not regional JOIN evidence."
            ),
            (
                "- Colocated Citus plans expose embedded task plans. "
                "Repartition plans report `Tasks Shown: None, not supported "
                "for re-partition queries`, so missing task rows are "
                "structural missingness rather than zero work."
            ),
            (
                "- Worker network counters are query-window OS proxies. They "
                "include a small amount of control/background traffic and "
                "must be interpreted through paired contrasts."
            ),
        ]
    )
    report = f"""# Distributed JOIN pressure probe

## Scope

This bounded probe separates JOIN strategy from observed severity. It is not a
training result. The compared query pairs return the same result while replacing
the colocated `users` table with the non-colocated `global_users` table.

## Main contrasts

{markdown_table(valid_pairs)}

## Findings

{findings}

## Interpretation contract

`MapMerge` confirms the strategy. It is not an intensity measure. JOIN pressure
severity is represented by multiple paired outcomes:

```text
log(T_repartition / T_colocated)
worker_tx_repartition - worker_tx_colocated
log(worker_tx_repartition / worker_tx_colocated)
worker_tx_excess / final_result_bytes
spill/temp-block excess, when present
```

The final result byte count is retained as a normalization denominator. A
single scalar should not merge elapsed-time penalty, internal movement and
spill unless that aggregation is explicitly justified.

## Collector boundary

Coordinator `auto_explain` reliably captures one regional Citus plan per
GAC Foreign Scan when the complete JOIN and regional aggregate are shippable.
For colocated plans, the Citus JSON contains task `Remote Plan` objects. For
repartition plans, Citus exposes MapMerge job/task counts but intentionally
omits individual task plans. Recovering those plans would require worker-side
logging and a separate correlation contract. The bounded capture also showed
that coordinator `auto_explain` contains many internal
`fetch_intermediate_results` statements. Their execution window is
correlatable, but they are phase evidence rather than complete worker plans.
Missing repartition task spill values therefore remain not applicable, not
zero, and must not be fabricated from the coordinator summary.
"""
    (args.out_dir / "README.md").write_text(report, encoding="utf-8")
    print(args.out_dir / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
