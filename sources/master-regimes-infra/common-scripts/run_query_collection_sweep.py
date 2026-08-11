#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import selectors
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

INSTANCE_METADATA_FIELDS = [
    "corpus_version",
    "batch_id",
    "collection_contract_version",
    "execution_slot_id",
    "pair_id",
    "repeat_id",
    "variant",
    "condition_id",
    "corpus_id",
    "corpus_cell_id",
    "logical_question_id",
    "execution_strategy",
    "execution_scope",
    "target_scope",
    "component_match_id",
    "dataset_profile_id",
    "runtime_config_id",
    "topology_id",
    "intervention_role",
    "intervention_axis",
    "pressure_axis",
    "pressure_level",
    "pressure_pair_key",
    "physical_strategy_id",
    "scenario_level",
    "join_shape_id",
    "remote_shape_id",
    "edge_stress_scope",
    "transfer_volume_level",
    "network_subblock",
    "coordinator_pressure_kind",
    "coordinator_shape_id",
    "mitigation_action",
    "target_metric",
    "dataset_role",
    "runtime_expected_effect",
    "work_mem",
    "fetch_size",
    "pg_options_json",
    "regional_pg_options_json",
    "psql_variables_json",
    "fdw_server_options_json",
    "network_profile_json",
    "network_profile_id",
    "configured_latency_ms",
    "configured_jitter_ms",
    "configured_loss_percent",
    "configured_bandwidth_mbit",
    "expected_regime_targets",
    "execution_class",
    "runtime_sensitivity",
    "required_dataset_capabilities",
    "intervention_roles",
    "cache_policy",
    "order_policy",
    "shuffle_seed",
    "dataset_size_class",
    "planned_query_passes",
    "progress_dataset_weight",
    "progress_runtime_multiplier",
    "planned_work_units",
    "progress_cost_class",
    "progress_weight_basis",
]


def utc_clock() -> str:
    return datetime.now(UTC).strftime("%H:%M:%SZ")


def format_duration(started_at: float) -> str:
    return f"{time.monotonic() - started_at:.1f}s"


def short_path(path_text: str) -> str:
    path = Path(path_text)
    if not path.is_absolute():
        return path_text
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        pass
    try:
        return "../" + str(path.relative_to(REPO_ROOT.parent))
    except ValueError:
        return path_text


def log_event(component: str, message: str) -> None:
    print(f"[{utc_clock()}] [{component}] {message}", flush=True)


def is_prefixed_log_line(value: str) -> bool:
    return value.startswith("[") and "] [" in value


def int_from_env(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def float_from_env(name: str, default: float = 0.0) -> float:
    return float_value(os.environ.get(name, ""), default)


def count_dict_from_env(name: str) -> dict[str, int]:
    raw_value = os.environ.get(name, "")
    if not raw_value:
        return {}
    parsed = json.loads(raw_value)
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): int(value)
        for key, value in parsed.items()
    }


def remaining_counts(
    *,
    initial: dict[str, int],
    processed_rows: list[dict[str, str]],
    field: str,
) -> dict[str, int]:
    result = dict(initial)
    for row in processed_rows:
        key = str(row.get(field, "unknown"))
        result[key] = max(0, result.get(key, 0) - 1)
    return {
        key: value
        for key, value in sorted(result.items())
        if value > 0
    }


def format_seconds(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "calibrating"
    rounded = int(round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def progress_percent(completed: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return min(100.0, max(0.0, completed * 100.0 / total))


def progress_bar(completed: float, total: float, width: int = 18) -> str:
    ratio = 0.0 if total <= 0 else min(1.0, max(0.0, completed / total))
    filled = int(round(ratio * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def progress_confidence(sample_count: int) -> str:
    if sample_count >= 20:
        return "high"
    if sample_count >= 5:
        return "medium"
    return "low"


def planned_work_units(row: dict[str, str]) -> float:
    return max(0.1, float_value(row.get("planned_work_units"), 1.0))


def estimated_rate(
    *,
    local_seconds_per_unit: list[float],
    prior_seconds_per_unit: float,
) -> float | None:
    if len(local_seconds_per_unit) >= 3:
        return statistics.median(local_seconds_per_unit)
    if prior_seconds_per_unit > 0:
        return prior_seconds_per_unit
    if local_seconds_per_unit:
        return statistics.median(local_seconds_per_unit)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run sequential query-bounded collection from an instance_manifest.csv."
    )
    parser.add_argument("--instance-manifest", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--max-instances", type=int, default=None)
    parser.add_argument(
        "--skip-static-snapshot",
        action="store_true",
        help="Compatibility alias for --global-stats-scope none.",
    )
    parser.add_argument(
        "--global-stats-scope",
        choices=("sweep", "query", "none"),
        default=None,
        help=(
            "Where PostgreSQL/Citus cumulative snapshots are collected. "
            "'sweep' collects before/after once around this query sweep; "
            "'query' collects before/after inside each query collection; "
            "'none' skips them. Defaults to 'none' for the core thesis collection."
        ),
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "query-sweeps",
    )
    parser.add_argument("--var", action="append", default=[], help="psql variable as name=value")
    parser.add_argument("--pg-option", action="append", default=[], help="PG option as name=value")
    parser.add_argument("--target-group", default="coordinators")
    parser.add_argument("--target-host", default="")
    parser.add_argument(
        "--checkpoint-file",
        type=Path,
        default=None,
        help=(
            "Append-only JSONL checkpoint keyed by execution_slot_id. "
            "Completed slots are skipped when the sweep is resumed."
        ),
    )
    parser.add_argument(
        "--hard-timeout-seconds",
        type=int,
        default=0,
        help="Per-query hard timeout passed to run_query_collection.py.",
    )
    parser.add_argument(
        "--timeout-grace-seconds",
        type=int,
        default=30,
        help="Grace period before force-killing timed-out remote explain-sql.",
    )
    parser.add_argument(
        "--cache-policy",
        default="",
        help="Audit label for cache protocol, e.g. mixed_cache_first_observed.",
    )
    parser.add_argument(
        "--order-policy",
        default="",
        help="Audit label for instance execution order, e.g. deterministic_shuffle.",
    )
    parser.add_argument(
        "--shuffle-seed",
        default="",
        help="Deterministic shuffle seed from the corpus renderer.",
    )
    parser.add_argument(
        "--fdw-auto-explain",
        action="store_true",
        help="Enable regional auto_explain instrumentation for each query collection.",
    )
    parser.add_argument(
        "--fdw-auto-explain-region",
        action="append",
        default=[],
        help="Logical region included in auto_explain capture. May be repeated.",
    )
    parser.add_argument(
        "--os-sampler",
        action="store_true",
        help="Collect per-query OS and network interface counters.",
    )
    parser.add_argument(
        "--os-sampler-node-group",
        action="append",
        default=[],
        help=(
            "Additional inventory group sampled during every query window. "
            "May be repeated and only applies with --os-sampler."
        ),
    )
    parser.add_argument(
        "--result-signature",
        action="store_true",
        help="Enable stream-only result signatures subject to --result-signature-scope.",
    )
    parser.add_argument(
        "--result-snapshot-only",
        action="store_true",
        help="Execute only typed result snapshots for bounded correctness recovery.",
    )
    parser.add_argument("--result-snapshot-max-rows", type=int, default=100)
    parser.add_argument(
        "--result-snapshot-max-bytes",
        type=int,
        default=10 * 1024 * 1024,
    )
    parser.add_argument(
        "--result-signature-scope",
        choices=("every_execution", "first_repetition_per_condition"),
        default="every_execution",
        help=(
            "Limit stream-only result signatures to every execution or to "
            "repetition_index=0 for each condition."
        ),
    )
    parser.add_argument(
        "--remote-edge-context",
        action="store_true",
        help=(
            "Collect lightweight before/after route and RTT context for every "
            "regional coordinator to the analytics/GAC target."
        ),
    )
    parser.add_argument(
        "--execution-metadata-json",
        default="{}",
        help="Runtime/network metadata merged into every query execution manifest.",
    )
    parser.add_argument("--no-citus-explain-all-tasks", action="store_true")
    return parser.parse_args()


def collect_result_signature_for_row(
    *,
    enabled: bool,
    scope: str,
    row: dict[str, str],
) -> bool:
    if not enabled:
        return False
    if scope == "every_execution":
        return True
    return str(row.get("repetition_index", "0") or "0") == "0"


def read_instances(path: Path, max_instances: int | None) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if max_instances is not None:
        rows = rows[:max_instances]
    for row in rows:
        if not row.get("instance_id") or not row.get("rendered_sql_path"):
            raise ValueError("instance_manifest.csv must contain instance_id and rendered_sql_path")
    return rows


def resolve_rendered_sql(manifest_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Rendered SQL file not found: {candidate}")

    for base in (manifest_path.parent, *manifest_path.parents):
        resolved = (base / candidate).resolve()
        if resolved.exists():
            return resolved
    raise FileNotFoundError(f"Rendered SQL file not found: {raw_path}")


def run_and_get_path(
    command: list[str],
    *,
    component: str,
    heartbeat_context: str = "",
    heartbeat_interval_seconds: int = 60,
) -> Path:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines: list[str] = []
    assert process.stdout is not None
    started_at = time.monotonic()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    while True:
        events = selector.select(timeout=heartbeat_interval_seconds)
        if events:
            line = process.stdout.readline()
            if line:
                output_lines.append(line)
                stripped = line.strip()
                if stripped:
                    if stripped.startswith("/"):
                        log_event(
                            component,
                            f"artifact -> {short_path(stripped)}",
                        )
                    elif is_prefixed_log_line(stripped):
                        print(stripped, flush=True)
                    else:
                        log_event(component, stripped)
                continue
        if process.poll() is not None:
            for line in process.stdout:
                output_lines.append(line)
                stripped = line.strip()
                if stripped:
                    if stripped.startswith("/"):
                        log_event(
                            component,
                            f"artifact -> {short_path(stripped)}",
                        )
                    elif is_prefixed_log_line(stripped):
                        print(stripped, flush=True)
                    else:
                        log_event(component, stripped)
            break
        if heartbeat_context:
            log_event(
                "HEARTBEAT",
                (
                    f"current query still running "
                    f"elapsed={format_seconds(time.monotonic() - started_at)} "
                    f"{heartbeat_context}"
                ),
            )
    returncode = process.wait()
    output = "".join(output_lines)
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, command, output=output)
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("/"):
            return Path(stripped)
    raise RuntimeError(f"Unable to parse output path from command: {' '.join(command)}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def status_payload(
    *,
    sweep_id: str,
    timestamp: str,
    status: str,
    manifest_path: Path,
    executions: list[dict[str, Any]],
    error: BaseException | None = None,
) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for execution in executions:
        execution_status = str(execution.get("execution_status", "unknown") or "unknown")
        by_status[execution_status] = by_status.get(execution_status, 0) + 1
    payload: dict[str, Any] = {
        "sweep_id": sweep_id,
        "created_at_utc": timestamp,
        "updated_at_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "instance_manifest": str(manifest_path),
        "status": status,
        "completed_query_count": len(executions),
        "query_count_by_status": by_status,
        "timeout_query_count": by_status.get("timeout", 0),
        "failed_query_count": by_status.get("failed", 0),
    }
    if executions:
        payload["completed_queries"] = executions
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)
    return payload


def flag_args(flag: str, values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        result.extend([flag, value])
    return result


def param_var_args(params: Any) -> list[str]:
    if not isinstance(params, dict):
        return []
    result: list[str] = []
    for key, value in params.items():
        if key.startswith("_"):
            continue
        result.extend(["--var", f"{key}={value}"])
    return result


def parse_params(raw_value: str) -> Any:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {"_raw": raw_value}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def load_collection_status(collection_dir: Path) -> dict[str, Any]:
    manifest_path = collection_dir / "execution_manifest.json"
    status_path = collection_dir / "execution_status.json"
    manifest: dict[str, Any] = {}
    status: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
    timeout = manifest.get("timeout") or status.get("timeout") or {}
    execution_status = str(
        manifest.get("execution_status")
        or status.get("status")
        or ("failed" if manifest.get("errors") else "completed")
    )
    return {
        "execution_status": execution_status,
        "timed_out": bool(manifest.get("timed_out") or status.get("timed_out")),
        "hard_timeout_seconds": manifest.get(
            "hard_timeout_seconds", status.get("hard_timeout_seconds", "")
        ),
        "timeout_phase": manifest.get(
            "timeout_phase", status.get("timeout_phase", timeout.get("phase", ""))
        ),
    }


def completed_checkpoint_event(event: dict[str, Any]) -> bool:
    if (
        event.get("status") != "completed"
        or not event.get("execution_slot_id")
    ):
        return False
    collection_dir = Path(str(event.get("collection_dir", "")))
    if not collection_dir.is_dir():
        return False
    if not (
        (collection_dir / "execution_manifest.json").is_file()
        or (collection_dir / "execution_status.json").is_file()
    ):
        return False
    try:
        status = load_collection_status(collection_dir)
    except (OSError, json.JSONDecodeError):
        return False
    return status["execution_status"] == "completed"


def final_sweep_status(executions: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("execution_status", "")) for item in executions}
    if "failed" in statuses:
        return "completed_with_failures"
    if "timeout" in statuses:
        return "completed_with_timeouts"
    return "completed"


def manifest_payload(
    *,
    sweep_id: str,
    timestamp: str,
    label: str,
    status: str,
    manifest_path: Path,
    cache_policy: str,
    order_policy: str,
    shuffle_seed: str,
    global_stats_scope: str,
    global_snapshot_before: Path | None,
    global_snapshot_after: Path | None,
    query_out_root: Path,
    args: argparse.Namespace,
    collect_query_snapshots: bool,
    collect_sweep_snapshots: bool,
    executions: list[dict[str, Any]],
    error: BaseException | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sweep_id": sweep_id,
        "created_at_utc": timestamp,
        "label": label,
        "status": status,
        "instance_manifest": str(manifest_path),
        "cache_policy": cache_policy or "mixed_cache_first_observed",
        "order_policy": order_policy,
        "shuffle_seed": shuffle_seed,
        "global_stats_scope": global_stats_scope,
        "global_snapshot_before_dir": (
            None if global_snapshot_before is None else str(global_snapshot_before)
        ),
        "global_snapshot_after_dir": (
            None if global_snapshot_after is None else str(global_snapshot_after)
        ),
        "query_collection_root": str(query_out_root),
        "execution_policy": {
            "query_execution": "sequential",
            "parallel_queries": False,
            "feature_contract": "core_v1",
            "hard_timeout_seconds": args.hard_timeout_seconds,
            "timeout_status_policy": (
                "record_and_continue" if args.hard_timeout_seconds > 0 else "disabled"
            ),
            "cache_policy": cache_policy or "mixed_cache_first_observed",
            "order_policy": order_policy,
            "shuffle_seed": shuffle_seed,
            "warmup_per_instance": False,
            "explicit_cache_reset": False,
            "repetitions_default": 1,
            "cache_features_in_default_model": False,
            "query_level_os_sampling": args.os_sampler,
            "os_sampler_node_groups": (list(args.os_sampler_node_group) if args.os_sampler else []),
            "remote_edge_context": args.remote_edge_context,
            "result_signature": args.result_signature,
            "result_signature_scope": args.result_signature_scope,
            "result_snapshot_only": args.result_snapshot_only,
            "query_level_global_db_snapshots": collect_query_snapshots,
            "sweep_level_global_db_snapshots": collect_sweep_snapshots,
            "fdw_auto_explain": args.fdw_auto_explain,
            "fdw_auto_explain_regions": list(args.fdw_auto_explain_region),
        },
        "runtime_overrides": {
            "psql_variables": args.var,
            "pg_options": args.pg_option,
            "target_group": args.target_group,
            "target_host": args.target_host,
            "citus_explain_all_tasks": not args.no_citus_explain_all_tasks,
            "fdw_auto_explain": args.fdw_auto_explain,
            "fdw_auto_explain_regions": list(args.fdw_auto_explain_region),
        },
        "executions": executions,
        "query_count_by_status": status_payload(
            sweep_id=sweep_id,
            timestamp=timestamp,
            status=status,
            manifest_path=manifest_path,
            executions=executions,
        )["query_count_by_status"],
    }
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)
    return payload


def main() -> int:
    args = parse_args()
    if args.result_snapshot_only and any(
        (
            args.result_signature,
            args.os_sampler,
            args.fdw_auto_explain,
            args.remote_edge_context,
        )
    ):
        raise ValueError(
            "--result-snapshot-only cannot be combined with collector instrumentation"
        )
    runtime_metadata = json.loads(args.execution_metadata_json)
    if not isinstance(runtime_metadata, dict):
        raise ValueError("--execution-metadata-json must decode to an object")
    global_stats_scope = args.global_stats_scope or "none"
    if args.skip_static_snapshot:
        global_stats_scope = "none"
    manifest_path = args.instance_manifest.resolve()
    all_rows = read_instances(manifest_path, args.max_instances)
    completed_slots: set[str] = set()
    completed_checkpoint_events: dict[str, dict[str, Any]] = {}
    if args.checkpoint_file is not None and args.checkpoint_file.exists():
        for raw_line in args.checkpoint_file.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            event = json.loads(raw_line)
            if completed_checkpoint_event(event):
                slot_id = str(event["execution_slot_id"])
                completed_slots.add(slot_id)
                completed_checkpoint_events[slot_id] = event
    rows = [
        row
        for row in all_rows
        if str(row.get("execution_slot_id", "")) not in completed_slots
    ]
    local_total_work = sum(planned_work_units(row) for row in all_rows)
    local_completed_before_work = sum(
        planned_work_units(row)
        for row in all_rows
        if str(row.get("execution_slot_id", "")) in completed_slots
    )
    local_completed_before_count = len(all_rows) - len(rows)
    initial_segment_completed_slots = int_from_env(
        "PRESSURE_SEGMENT_INITIAL_COMPLETED_SLOTS",
        len(completed_slots),
    )
    initial_segment_completed_work = float_from_env(
        "PRESSURE_SEGMENT_INITIAL_COMPLETED_WORK",
        sum(
            float_value(event.get("planned_work_units"), 1.0)
            for event in completed_checkpoint_events.values()
        ),
    )
    checkpoint_completed_work = sum(
        float_value(event.get("planned_work_units"), 1.0)
        for event in completed_checkpoint_events.values()
    )
    segment_new_completed_count = max(
        0,
        len(completed_slots) - initial_segment_completed_slots,
    )
    segment_new_completed_work = max(
        0.0,
        checkpoint_completed_work - initial_segment_completed_work,
    )
    batch_slot_total = int_from_env(
        "PRESSURE_BATCH_SLOT_TOTAL",
        len(all_rows),
    )
    batch_slot_offset = int_from_env(
        "PRESSURE_BATCH_SLOT_OFFSET",
        local_completed_before_count,
    ) + segment_new_completed_count
    batch_work_total = float_from_env(
        "PRESSURE_BATCH_WORK_TOTAL",
        local_total_work,
    )
    batch_work_offset = float_from_env(
        "PRESSURE_BATCH_WORK_OFFSET",
        local_completed_before_work,
    ) + segment_new_completed_work
    program_slot_total = int_from_env(
        "PRESSURE_PROGRAM_SLOT_TOTAL",
        batch_slot_total,
    )
    program_slot_offset = int_from_env(
        "PRESSURE_PROGRAM_SLOT_OFFSET",
        batch_slot_offset,
    ) + segment_new_completed_count
    program_work_total = float_from_env(
        "PRESSURE_PROGRAM_WORK_TOTAL",
        batch_work_total,
    )
    program_work_offset = float_from_env(
        "PRESSURE_PROGRAM_WORK_OFFSET",
        batch_work_offset,
    ) + segment_new_completed_work
    blocked_program_slots = int_from_env(
        "PRESSURE_PROGRAM_BLOCKED_SLOTS",
        0,
    )
    prior_seconds_per_unit = float_from_env(
        "PRESSURE_SECONDS_PER_WORK_UNIT",
        0.0,
    )
    prior_eta_samples = int_from_env("PRESSURE_ETA_SAMPLE_COUNT", 0)
    initial_remaining_cost_counts = count_dict_from_env(
        "PRESSURE_REMAINING_COST_CLASS_COUNTS"
    )
    initial_remaining_size_counts = count_dict_from_env(
        "PRESSURE_REMAINING_DATASET_SIZE_COUNTS"
    )
    progress_file_text = os.environ.get("PRESSURE_PROGRESS_FILE", "")
    program_progress_file_text = os.environ.get(
        "PRESSURE_PROGRAM_PROGRESS_FILE",
        "",
    )
    progress_file = Path(progress_file_text) if progress_file_text else None
    program_progress_file = (
        Path(program_progress_file_text)
        if program_progress_file_text
        else None
    )
    pressure_program_id = os.environ.get("PRESSURE_PROGRAM_ID", "")
    pressure_batch_id = os.environ.get("PRESSURE_BATCH_ID", "")
    pressure_segment_id = os.environ.get("PRESSURE_SEGMENT_ID", "")
    pressure_program_attempt_id = os.environ.get(
        "PRESSURE_PROGRAM_ATTEMPT_ID",
        "",
    )
    local_seconds_per_unit: list[float] = []
    corpus_progress_offset = int_from_env("CORPUS_PROGRESS_OFFSET", 0)
    corpus_progress_total = int_from_env("CORPUS_PROGRESS_TOTAL", 0)
    corpus_group_index = int_from_env("CORPUS_PROGRESS_GROUP_INDEX", 0)
    corpus_group_count = int_from_env("CORPUS_PROGRESS_GROUP_COUNT", 0)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    sweep_id = f"{timestamp}-{args.label}"
    sweep_dir = (args.out_root / sweep_id).resolve()
    query_out_root = sweep_dir / "query-collections"
    static_out_root = sweep_dir / "global-snapshots"
    sweep_dir.mkdir(parents=True, exist_ok=True)
    status_file = sweep_dir / "query_sweep_status.json"
    log_event(
        "QUERY",
        (
            f"start sweep_id={sweep_id} instances={len(rows)} "
            f"target_group={args.target_group} fdw_auto_explain={args.fdw_auto_explain}"
        ),
    )
    cost_counts: dict[str, int] = {}
    for row in rows:
        cost_class = str(row.get("progress_cost_class", "unknown"))
        cost_counts[cost_class] = cost_counts.get(cost_class, 0) + 1
    dataset_labels = sorted(
        {
            (
                str(row.get("dataset_profile_id", "")),
                str(row.get("dataset_size_class", "")),
            )
            for row in rows
        }
    )
    log_event(
        "PROGRESS",
        (
            f"local slots={local_completed_before_count}/{len(all_rows)} "
            f"weighted={local_completed_before_work:.1f}/"
            f"{local_total_work:.1f} "
            f"cost_classes={json.dumps(cost_counts, sort_keys=True)} "
            f"datasets={dataset_labels}"
        ),
    )
    if corpus_progress_total > 0:
        log_event(
            "QUERY",
            (
                f"corpus progress group={corpus_group_index}/{corpus_group_count} "
                f"offset={corpus_progress_offset} total={corpus_progress_total}"
            ),
        )
    log_event("QUERY", f"artifacts -> {short_path(str(sweep_dir))}")

    executions: list[dict[str, Any]] = []
    write_json(
        status_file,
        status_payload(
            sweep_id=sweep_id,
            timestamp=timestamp,
            status="running",
            manifest_path=manifest_path,
            executions=executions,
        ),
    )

    global_snapshot_before: Path | None = None
    global_snapshot_after: Path | None = None
    collect_sweep_snapshots = not args.skip_static_snapshot and global_stats_scope == "sweep"
    collect_query_snapshots = global_stats_scope == "query"
    if collect_sweep_snapshots:
        log_event("QUERY", "global before snapshot start")
        global_snapshot_before = run_and_get_path(
            [
                sys.executable,
                str(REPO_ROOT / "common-scripts" / "run_sweep_static_snapshot.py"),
                "--label",
                f"{sweep_id}-before",
                "--out-root",
                str(static_out_root),
            ],
            component="SNAPSHOT",
        )
        log_event("QUERY", "global before snapshot done")

    try:
        for execution_index, row in enumerate(rows, start=1):
            query_started_at = time.monotonic()
            local_done_count = (
                local_completed_before_count + execution_index - 1
            )
            completed_pending_work = sum(
                planned_work_units(item)
                for item in rows[: execution_index - 1]
            )
            current_weight = planned_work_units(row)
            rate = estimated_rate(
                local_seconds_per_unit=local_seconds_per_unit,
                prior_seconds_per_unit=prior_seconds_per_unit,
            )
            sample_count = prior_eta_samples + len(
                local_seconds_per_unit
            )
            batch_done_work = (
                batch_work_offset + completed_pending_work
            )
            program_done_work = (
                program_work_offset + completed_pending_work
            )
            eta_seconds = (
                None
                if rate is None
                else max(
                    0.0,
                    program_work_total - program_done_work,
                )
                * rate
            )
            next_heavy = next(
                (
                    item
                    for item in rows[execution_index - 1 :]
                    if str(
                        item.get("progress_cost_class", "")
                    )
                    in {"heavy", "extreme"}
                ),
                None,
            )
            next_heavy_dataset = (
                str(next_heavy.get("dataset_profile_id", "none"))
                if next_heavy
                else "none"
            )
            remaining_costs_before = remaining_counts(
                initial=initial_remaining_cost_counts,
                processed_rows=rows[: execution_index - 1],
                field="progress_cost_class",
            )
            remaining_sizes_before = remaining_counts(
                initial=initial_remaining_size_counts,
                processed_rows=rows[: execution_index - 1],
                field="dataset_size_class",
            )
            heavy_remaining_before = int(
                remaining_costs_before.get("heavy", 0)
            ) + int(remaining_costs_before.get("extreme", 0))
            log_event(
                "PROGRESS",
                (
                    f"LOCAL {progress_bar(local_done_count, len(all_rows))} "
                    f"{local_done_count}/{len(all_rows)} "
                    f"BATCH {progress_bar(batch_done_work, batch_work_total)} "
                    f"{progress_percent(batch_done_work, batch_work_total):.1f}% "
                    f"GLOBAL {progress_bar(program_done_work, program_work_total)} "
                    f"{progress_percent(program_done_work, program_work_total):.1f}% "
                    f"ETA~{format_seconds(eta_seconds)} "
                    f"confidence={progress_confidence(sample_count)} "
                    f"current={row.get('dataset_profile_id', '')}/"
                    f"{row.get('progress_cost_class', 'unknown')} "
                    f"weight={current_weight:.1f} "
                    f"next_heavy={next_heavy_dataset} "
                    f"heavy_remaining={heavy_remaining_before} "
                    "large_remaining="
                    f"{remaining_sizes_before.get('large', 0)} "
                    f"blocked_future_slots={blocked_program_slots}"
                ),
            )
            global_execution_index = corpus_progress_offset + execution_index
            global_prefix = (
                f"global instance {global_execution_index}/{corpus_progress_total} "
                if corpus_progress_total > 0
                else ""
            )
            instance_id = row["instance_id"]
            sql_path = resolve_rendered_sql(manifest_path, row["rendered_sql_path"])
            params = parse_params(row.get("param_json", ""))
            template_id = row.get("template_id", "")
            collect_result_signature = collect_result_signature_for_row(
                enabled=args.result_signature,
                scope=args.result_signature_scope,
                row=row,
            )
            log_event(
                "QUERY",
                (
                    global_prefix + f"instance {execution_index}/{len(rows)} start "
                    f"template={template_id} instance={instance_id} "
                    f"sql={short_path(str(sql_path))}"
                ),
            )
            collection_dir = run_and_get_path(
                [
                    sys.executable,
                    str(REPO_ROOT / "common-scripts" / "run_query_collection.py"),
                    "--sql-file",
                    str(sql_path),
                    "--label",
                    f"{args.label}__{instance_id}",
                    "--out-root",
                    str(query_out_root),
                    "--target-group",
                    args.target_group,
                    "--execution-metadata-json",
                    json.dumps(
                        {
                            field: runtime_metadata.get(field, row.get(field, ""))
                            for field in INSTANCE_METADATA_FIELDS
                        },
                        sort_keys=True,
                    ),
                    *(["--target-host", args.target_host] if args.target_host else []),
                    *(["--no-citus-explain-all-tasks"] if args.no_citus_explain_all_tasks else []),
                    *(["--db-snapshots"] if collect_query_snapshots else []),
                    *(
                        ["--hard-timeout-seconds", str(args.hard_timeout_seconds)]
                        if args.hard_timeout_seconds > 0
                        else []
                    ),
                    *(
                        ["--timeout-grace-seconds", str(args.timeout_grace_seconds)]
                        if args.hard_timeout_seconds > 0
                        else []
                    ),
                    *(["--fdw-auto-explain"] if args.fdw_auto_explain else []),
                    *(
                        item
                        for region in args.fdw_auto_explain_region
                        for item in ("--fdw-auto-explain-region", region)
                    ),
                    *(["--os-sampler"] if args.os_sampler else []),
                    *(
                        item
                        for group in args.os_sampler_node_group
                        for item in ("--os-sampler-node-group", group)
                    ),
                    *(["--result-signature"] if collect_result_signature else []),
                    *(
                        [
                            "--result-snapshot-only",
                            "--result-snapshot-max-rows",
                            str(args.result_snapshot_max_rows),
                            "--result-snapshot-max-bytes",
                            str(args.result_snapshot_max_bytes),
                        ]
                        if args.result_snapshot_only
                        else []
                    ),
                    *(["--remote-edge-context"] if args.remote_edge_context else []),
                    *param_var_args(params),
                    *flag_args("--var", args.var),
                    *flag_args("--pg-option", args.pg_option),
                ],
                component="COLLECT",
                heartbeat_context=(
                    f"dataset={row.get('dataset_profile_id', '')} "
                    f"cost={row.get('progress_cost_class', 'unknown')} "
                    f"weight={current_weight:.1f} "
                    f"GLOBAL={progress_percent(program_done_work, program_work_total):.1f}% "
                    f"ETA~{format_seconds(eta_seconds)}"
                ),
            )
            collection_status = load_collection_status(collection_dir)
            executions.append(
                {
                    "instance_id": instance_id,
                    "template_id": row.get("template_id", ""),
                    **{field: row.get(field, "") for field in INSTANCE_METADATA_FIELDS},
                    "params": params,
                    "expected_shape_tags": row.get("expected_shape_tags", ""),
                    "rendered_sql_path": str(sql_path),
                    "collection_dir": str(collection_dir),
                    "repetition_index": row.get("repetition_index", "0") or "0",
                    "result_signature_requested": collect_result_signature,
                    "result_snapshot_only": args.result_snapshot_only,
                    "run_order": row.get("run_order", str(execution_index)) or str(execution_index),
                    "warmup_run_flag": row.get("warmup_run_flag", "false") or "false",
                    "cache_policy": (
                        row.get("cache_policy") or args.cache_policy or "mixed_cache_first_observed"
                    ),
                    "order_policy": row.get("order_policy") or args.order_policy,
                    "shuffle_seed": row.get("shuffle_seed") or args.shuffle_seed,
                    **collection_status,
                }
            )
            execution_slot_id = str(row.get("execution_slot_id", ""))
            query_elapsed_seconds = time.monotonic() - query_started_at
            if (
                args.checkpoint_file is not None
                and execution_slot_id
                and collection_status["execution_status"] == "completed"
            ):
                # Persist an indexable partial sweep before declaring this slot
                # resumable. A later process may rebuild the index from this
                # manifest even if the sweep is interrupted immediately after.
                write_json_atomic(
                    sweep_dir / "query_sweep_manifest.json",
                    manifest_payload(
                        sweep_id=sweep_id,
                        timestamp=timestamp,
                        label=args.label,
                        status="running",
                        manifest_path=manifest_path,
                        cache_policy=args.cache_policy,
                        order_policy=args.order_policy,
                        shuffle_seed=args.shuffle_seed,
                        global_stats_scope=global_stats_scope,
                        global_snapshot_before=global_snapshot_before,
                        global_snapshot_after=global_snapshot_after,
                        query_out_root=query_out_root,
                        args=args,
                        collect_query_snapshots=collect_query_snapshots,
                        collect_sweep_snapshots=collect_sweep_snapshots,
                        executions=executions,
                    ),
                )
                args.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
                with args.checkpoint_file.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "program_id": pressure_program_id,
                                "batch_id": pressure_batch_id,
                                "segment_id": pressure_segment_id,
                                "program_attempt_id": (
                                    pressure_program_attempt_id
                                ),
                                "execution_slot_id": execution_slot_id,
                                "pair_id": row.get("pair_id", ""),
                                "repeat_id": row.get("repeat_id", ""),
                                "status": "completed",
                                "collection_dir": str(collection_dir),
                                "elapsed_seconds": round(
                                    query_elapsed_seconds,
                                    3,
                                ),
                                "planned_work_units": current_weight,
                                "dataset_profile_id": row.get(
                                    "dataset_profile_id",
                                    "",
                                ),
                                "dataset_size_class": row.get(
                                    "dataset_size_class",
                                    "",
                                ),
                                "progress_cost_class": row.get(
                                    "progress_cost_class",
                                    "",
                                ),
                                "completed_at_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
            if (
                collection_status["execution_status"] == "completed"
                and current_weight > 0
            ):
                local_seconds_per_unit.append(
                    query_elapsed_seconds / current_weight
                )
            processed_work = completed_pending_work + current_weight
            current_rate = estimated_rate(
                local_seconds_per_unit=local_seconds_per_unit,
                prior_seconds_per_unit=prior_seconds_per_unit,
            )
            current_sample_count = prior_eta_samples + len(
                local_seconds_per_unit
            )
            current_program_work = (
                program_work_offset + processed_work
            )
            current_eta = (
                None
                if current_rate is None
                else max(
                    0.0,
                    program_work_total - current_program_work,
                )
                * current_rate
            )
            remaining_costs_after = remaining_counts(
                initial=initial_remaining_cost_counts,
                processed_rows=rows[:execution_index],
                field="progress_cost_class",
            )
            remaining_sizes_after = remaining_counts(
                initial=initial_remaining_size_counts,
                processed_rows=rows[:execution_index],
                field="dataset_size_class",
            )
            live_progress = {
                "status": "running",
                "current_execution_slot_id": execution_slot_id,
                "current_dataset_profile_id": row.get(
                    "dataset_profile_id",
                    "",
                ),
                "current_cost_class": row.get(
                    "progress_cost_class",
                    "",
                ),
                "local": {
                    "processed": (
                        local_completed_before_count + execution_index
                    ),
                    "total": len(all_rows),
                    "work_completed": round(
                        local_completed_before_work + processed_work,
                        3,
                    ),
                    "work_total": round(local_total_work, 3),
                },
                "batch": {
                    "processed": (
                        batch_slot_offset + execution_index
                    ),
                    "total": batch_slot_total,
                    "work_completed": round(
                        batch_work_offset + processed_work,
                        3,
                    ),
                    "work_total": round(batch_work_total, 3),
                },
                "program": {
                    "processed": (
                        program_slot_offset + execution_index
                    ),
                    "total": program_slot_total,
                    "work_completed": round(
                        current_program_work,
                        3,
                    ),
                    "work_total": round(program_work_total, 3),
                    "blocked_future_slots": blocked_program_slots,
                    "remaining_cost_class_counts": (
                        remaining_costs_after
                    ),
                    "remaining_dataset_size_counts": (
                        remaining_sizes_after
                    ),
                },
                "eta_seconds": (
                    None
                    if current_eta is None
                    else round(current_eta, 1)
                ),
                "eta_display": format_seconds(current_eta),
                "eta_confidence": progress_confidence(
                    current_sample_count
                ),
                "eta_sample_count": current_sample_count,
                "seconds_per_work_unit": (
                    None
                    if current_rate is None
                    else round(current_rate, 6)
                ),
                "updated_at_utc": datetime.now(UTC).strftime(
                    "%Y%m%dT%H%M%SZ"
                ),
            }
            if progress_file is not None:
                write_json(progress_file, live_progress)
            if program_progress_file is not None:
                write_json(program_progress_file, live_progress)
            log_event(
                "QUERY",
                (
                    global_prefix + f"instance {execution_index}/{len(rows)} "
                    f"{collection_status['execution_status']} "
                    f"in {format_duration(query_started_at)} "
                    f"GLOBAL={progress_percent(current_program_work, program_work_total):.1f}% "
                    f"ETA~{format_seconds(current_eta)} "
                    f"confidence={progress_confidence(current_sample_count)}"
                ),
            )
            write_json(
                status_file,
                status_payload(
                    sweep_id=sweep_id,
                    timestamp=timestamp,
                    status="running",
                    manifest_path=manifest_path,
                    executions=executions,
                ),
            )

        if collect_sweep_snapshots:
            log_event("QUERY", "global after snapshot start")
            global_snapshot_after = run_and_get_path(
                [
                    sys.executable,
                    str(REPO_ROOT / "common-scripts" / "run_sweep_static_snapshot.py"),
                    "--label",
                    f"{sweep_id}-after",
                    "--out-root",
                    str(static_out_root),
                ],
                component="SNAPSHOT",
            )
            log_event("QUERY", "global after snapshot done")

        write_json(
            sweep_dir / "query_sweep_manifest.json",
            manifest_payload(
                sweep_id=sweep_id,
                timestamp=timestamp,
                label=args.label,
                status=final_sweep_status(executions),
                manifest_path=manifest_path,
                cache_policy=args.cache_policy,
                order_policy=args.order_policy,
                shuffle_seed=args.shuffle_seed,
                global_stats_scope=global_stats_scope,
                global_snapshot_before=global_snapshot_before,
                global_snapshot_after=global_snapshot_after,
                query_out_root=query_out_root,
                args=args,
                collect_query_snapshots=collect_query_snapshots,
                collect_sweep_snapshots=collect_sweep_snapshots,
                executions=executions,
            ),
        )
    except BaseException as exc:
        write_json(
            status_file,
            status_payload(
                sweep_id=sweep_id,
                timestamp=timestamp,
                status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                manifest_path=manifest_path,
                executions=executions,
                error=exc,
            ),
        )
        write_json(
            sweep_dir / "query_sweep_manifest.json",
            manifest_payload(
                sweep_id=sweep_id,
                timestamp=timestamp,
                label=args.label,
                status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                manifest_path=manifest_path,
                cache_policy=args.cache_policy,
                order_policy=args.order_policy,
                shuffle_seed=args.shuffle_seed,
                global_stats_scope=global_stats_scope,
                global_snapshot_before=global_snapshot_before,
                global_snapshot_after=global_snapshot_after,
                query_out_root=query_out_root,
                args=args,
                collect_query_snapshots=collect_query_snapshots,
                collect_sweep_snapshots=collect_sweep_snapshots,
                executions=executions,
                error=exc,
            ),
        )
        log_event("QUERY", f"{type(exc).__name__}: {exc}")
        raise

    final_status = final_sweep_status(executions)
    write_json(
        status_file,
        status_payload(
            sweep_id=sweep_id,
            timestamp=timestamp,
            status=final_status,
            manifest_path=manifest_path,
            executions=executions,
        ),
    )
    print(str(sweep_dir), flush=True)
    log_event(
        "QUERY",
        (f"{final_status} completed={len(executions)} artifact -> {short_path(str(sweep_dir))}"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
