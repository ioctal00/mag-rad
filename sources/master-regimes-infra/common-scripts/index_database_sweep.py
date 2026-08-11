#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

csv.field_size_limit(sys.maxsize)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build normalized index tables for a database sweep output."
    )
    parser.add_argument("--sweep-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def maybe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json(path)


def rel(root: Path, path: Path | str | None) -> str:
    if path is None:
        return ""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(candidate)


def rel_if_exists(root: Path, path: Path | str | None) -> str:
    if path is None:
        return ""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    if not candidate.exists():
        return ""
    return rel(root, candidate)


def json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


CORPUS_METADATA_FIELDS = [
    "corpus_version",
    "batch_id",
    "collection_contract_version",
    "execution_slot_id",
    "pair_id",
    "repeat_id",
    "variant",
    "condition_id",
    "repetition_index",
    "run_order",
    "corpus_id",
    "corpus_cell_id",
    "logical_question_id",
    "execution_strategy",
    "dataset_profile_id",
    "topology_id",
    "intervention_role",
    "intervention_axis",
    "pressure_axis",
    "pressure_level",
    "pressure_pair_key",
    "physical_strategy_id",
    "scenario_level",
    "join_shape_id",
    "coordinator_pressure_kind",
    "coordinator_shape_id",
    "remote_shape_id",
    "edge_stress_scope",
    "transfer_volume_level",
    "network_subblock",
    "mitigation_action",
    "target_metric",
    "dataset_role",
    "expected_regime_targets",
    "execution_class",
    "runtime_sensitivity",
    "required_dataset_capabilities",
    "intervention_roles",
]

QUERY_RUN_DERIVED_PASSTHROUGH_FIELDS = [
    "citus_repartition_observed_v2",
    "os_sampled_node_count",
    "os_sample_count_sum",
    "os_cpu_busy_pct_mean",
    "os_cpu_steal_pct_mean",
    "os_cpu_steal_pct_max",
    "os_net_rx_bytes_sum",
    "os_net_tx_bytes_sum",
    "os_net_rx_packets_sum",
    "os_net_tx_packets_sum",
    "os_net_rx_dropped_sum",
    "os_net_tx_dropped_sum",
    "os_net_rx_errors_sum",
    "os_net_tx_errors_sum",
    "os_tcp_retrans_segs_sum",
    "os_tcp_timeouts_sum",
    "regional_coordinator_tx_bytes_sum",
    "regional_coordinator_tx_packets_sum",
    "analytics_rx_bytes_sum",
    "analytics_rx_packets_sum",
    "worker_rx_bytes_sum",
    "worker_tx_bytes_sum",
    "worker_rx_bytes_cv",
    "worker_tx_bytes_cv",
    "worker_rx_bytes_max_share",
    "worker_tx_bytes_max_share",
    "worker_network_regions_json",
    "os_network_nodes_json",
    "result_signature_status",
    "result_signature_file",
    "result_row_count",
    "result_output_byte_count",
    "result_multiset_sha256",
    "result_ordered_sha256",
    "result_signature_elapsed_seconds",
    "database_result_rows_stored",
]

COORDINATOR_PRESSURE_PASSTHROUGH_FIELDS = [
    "coordinator_main_plan_total_time_ms",
    "coordinator_foreign_scan_time_ms_sum",
    "coordinator_non_foreign_time_ms_proxy",
    "coordinator_non_foreign_time_share_proxy",
    "coordinator_fanin_rows",
    "coordinator_fanin_bytes_estimated",
    "coordinator_final_rows",
    "coordinator_final_bytes_estimated",
    "coordinator_blocking_operator_count",
    "coordinator_blocking_input_rows_sum",
    "coordinator_blocking_input_rows_max",
    "coordinator_blocking_output_rows_sum",
    "coordinator_temp_read_blocks",
    "coordinator_temp_written_blocks",
    "coordinator_spill_present",
    "coordinator_disk_sort_count",
    "coordinator_sort_space_used_kb_max",
    "coordinator_hash_batches_max",
    "coordinator_hashagg_disk_usage_kb_max",
    "coordinator_peak_memory_usage_kb_max",
]
for operator_class in ("sort", "aggregate", "join", "unique", "window", "limit"):
    COORDINATOR_PRESSURE_PASSTHROUGH_FIELDS.extend(
        [
            f"coordinator_{operator_class}_operator_count",
            f"coordinator_{operator_class}_input_rows_sum",
            f"coordinator_{operator_class}_input_rows_max",
            f"coordinator_{operator_class}_output_rows_sum",
            f"coordinator_{operator_class}_time_ms_max",
        ]
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def enrich_query_rows_from_execution_features(
    query_rows: list[dict[str, Any]],
    execution_feature_rows: list[dict[str, Any]],
) -> None:
    features_by_query_run_id = {
        str(row.get("query_run_id", "")): row
        for row in execution_feature_rows
        if row.get("query_run_id")
    }
    for query_row in query_rows:
        feature_row = features_by_query_run_id.get(str(query_row.get("query_run_id", "")))
        if feature_row is None:
            continue
        for field in (
            *QUERY_RUN_DERIVED_PASSTHROUGH_FIELDS,
            *COORDINATOR_PRESSURE_PASSTHROUGH_FIELDS,
        ):
            query_row[field] = feature_row.get(field, "")


def feature_schema_sources(root: Path) -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root.parent / "master-regimes" / "docs" / "feature_schema.yml",
        Path.cwd().parent / "master-regimes" / "docs" / "feature_schema.yml",
    ]
    candidates.extend(sorted((root / "query-sweeps").glob("*/_index/feature_schema.yml")))
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def merged_fieldnames(
    rows: list[dict[str, Any]],
    preferred: list[str],
) -> list[str]:
    seen = set(preferred)
    fieldnames = list(preferred)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    return fieldnames


def query_sweep_index_rows(
    *,
    root: Path,
    database_sweep_id: str,
    query_sweep_id: str,
    dataset_id: str,
    runtime_config_id: str,
    query_sweep_dir: Path,
    table_name: str,
) -> list[dict[str, Any]]:
    index_file = query_sweep_dir / "_index" / table_name
    source_rows = read_csv(index_file)
    rows: list[dict[str, Any]] = []
    for source_row in source_rows:
        row: dict[str, Any] = {
            "database_sweep_id": database_sweep_id,
            "dataset_id": dataset_id,
            "runtime_config_id": runtime_config_id,
            "query_sweep_id": source_row.get("query_sweep_id", query_sweep_id),
            "query_sweep_dir": rel(root, query_sweep_dir),
            "query_sweep_index_dir": rel(root, query_sweep_dir / "_index"),
        }
        row.update(source_row)
        rows.append(row)
    return rows


NETWORK_CONTEXT_FIELDS = [
    "network_profile_id",
    "network_intervention_scope",
    "configured_latency_ms",
    "configured_jitter_ms",
    "configured_loss_percent",
    "configured_bandwidth_mbit",
    "network_intervention_apply_status",
    "network_intervention_reset_status",
    "network_intervention_apply_dir",
    "network_intervention_reset_dir",
    "network_measurement_dir",
    "network_measurement_json",
    "network_profile_json",
]


def network_context(
    *,
    root: Path,
    execution: dict[str, Any],
) -> dict[str, Any]:
    measurement_dir_raw = execution.get("network_measurement_dir", "")
    measurement_dir = Path(measurement_dir_raw) if measurement_dir_raw else None
    measurement_file = (
        measurement_dir / "network_profile_measurement.json"
        if measurement_dir is not None
        else None
    )
    measurement = (
        json.loads(measurement_file.read_text(encoding="utf-8"))
        if measurement_file is not None and measurement_file.exists()
        else {}
    )
    return {
        "network_profile_id": execution.get("network_profile_id", ""),
        "network_intervention_scope": execution.get("network_intervention_scope", ""),
        "configured_latency_ms": execution.get("configured_latency_ms", ""),
        "configured_jitter_ms": execution.get("configured_jitter_ms", ""),
        "configured_loss_percent": execution.get("configured_loss_percent", ""),
        "configured_bandwidth_mbit": execution.get("configured_bandwidth_mbit", ""),
        "network_intervention_apply_status": execution.get("network_intervention_apply_status", ""),
        "network_intervention_reset_status": execution.get("network_intervention_reset_status", ""),
        "network_intervention_apply_dir": rel(
            root, execution.get("network_intervention_apply_dir")
        ),
        "network_intervention_reset_dir": rel(
            root, execution.get("network_intervention_reset_dir")
        ),
        "network_measurement_dir": rel(root, measurement_dir_raw),
        "network_measurement_json": json_text(measurement),
        "network_profile_json": json_text(execution.get("network_profile", {})),
    }


def with_context(
    rows: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    return [{**context, **row} for row in rows]


def _is_true_text(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _is_present(value: Any) -> bool:
    return str(value or "").strip() != ""


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def feature_overview_rows(
    *,
    execution_rows: list[dict[str, Any]],
    structure_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    structure_by_run = {str(row.get("query_run_id", "")): row for row in structure_rows}
    overview_rows: list[dict[str, Any]] = []
    for index, execution in enumerate(execution_rows, start=1):
        query_run_id = str(execution.get("query_run_id", ""))
        structure = structure_by_run.get(query_run_id, {})
        fdw_remote_sql_count = str(execution.get("fdw_remote_sql_count", ""))
        remote_path_applicable = _is_true_text(
            execution.get("main_has_foreign_scan")
        ) or fdw_remote_sql_count not in {"", "0"}
        fan_in_metric_available = _is_present(execution.get("estimated_fanin_bytes"))
        citus_task_metrics_available = _is_present(execution.get("task_count"))
        structure_features_available = _is_present(structure.get("main_plan_node_count"))
        missing_reasons = []
        if not remote_path_applicable:
            missing_reasons.append("no_fdw_remote_path")
        if remote_path_applicable and not fan_in_metric_available:
            missing_reasons.append("fan_in_metric_missing")
        if not citus_task_metrics_available:
            missing_reasons.append("no_citus_task_metrics")
        if not structure_features_available:
            missing_reasons.append("plan_structure_missing")
        overview_rows.append(
            {
                "row_index": index,
                "dataset_id": execution.get("dataset_id", ""),
                "runtime_config_id": execution.get("runtime_config_id", ""),
                "network_profile_id": execution.get("network_profile_id", ""),
                "configured_latency_ms": execution.get("configured_latency_ms", ""),
                "network_intervention_apply_status": execution.get(
                    "network_intervention_apply_status", ""
                ),
                "network_intervention_reset_status": execution.get(
                    "network_intervention_reset_status", ""
                ),
                "corpus_cell_id": execution.get("corpus_cell_id", ""),
                "logical_question_id": execution.get("logical_question_id", ""),
                "execution_strategy": execution.get("execution_strategy", ""),
                "intervention_role": execution.get("intervention_role", ""),
                "intervention_axis": execution.get("intervention_axis", ""),
                "expected_regime_targets": execution.get("expected_regime_targets", ""),
                "execution_class": execution.get("execution_class", ""),
                "template_id": execution.get("template_id", ""),
                "instance_id": execution.get("instance_id", ""),
                "execution_status": execution.get("execution_status", ""),
                "timed_out": execution.get("timed_out", ""),
                "hard_timeout_seconds": execution.get("hard_timeout_seconds", ""),
                "timeout_phase": execution.get("timeout_phase", ""),
                "elapsed_seconds": execution.get("elapsed_seconds", ""),
                "run_order": execution.get("run_order", ""),
                "cache_policy": execution.get("cache_policy", ""),
                "shared_hit_ratio": execution.get("shared_hit_ratio", ""),
                "temp_blks_written_sum": execution.get("temp_blks_written_sum", ""),
                "collection_error_count": execution.get("collection_error_count", ""),
                "fdw_remote_probe_status": execution.get("fdw_remote_probe_status", ""),
                "fdw_remote_sql_count": execution.get("fdw_remote_sql_count", ""),
                "main_has_foreign_scan": execution.get("main_has_foreign_scan", ""),
                "main_has_remote_sql": execution.get("main_has_remote_sql", ""),
                "remote_path_applicable": _bool_text(remote_path_applicable),
                "fan_in_metric_available": _bool_text(fan_in_metric_available),
                "citus_task_metrics_available": _bool_text(citus_task_metrics_available),
                "structure_features_available": _bool_text(structure_features_available),
                "overview_missing_reason": ";".join(missing_reasons),
                "result_width_class": execution.get("result_width_class", ""),
                "estimated_fanin_bytes": execution.get("estimated_fanin_bytes", ""),
                "task_count": execution.get("task_count", ""),
                "task_rows_cv": execution.get("task_rows_cv", ""),
                "worker_rows_cv": execution.get("worker_rows_cv", ""),
                "worker_time_cv": execution.get("worker_time_cv", ""),
                "citus_map_merge_job_count": execution.get("citus_map_merge_job_count", ""),
                "citus_repartition_query": execution.get("citus_repartition_query", ""),
                "citus_tasks_shown_none": execution.get("citus_tasks_shown_none", ""),
                "main_plan_node_count": structure.get("main_plan_node_count", ""),
                "main_plan_max_depth": structure.get("main_plan_max_depth", ""),
                "aggregate_above_foreign_scan": structure.get("aggregate_above_foreign_scan", ""),
                "join_above_foreign_scan": structure.get("join_above_foreign_scan", ""),
                "remote_aggregate_present": structure.get("remote_aggregate_present", ""),
                "remote_join_present": structure.get("remote_join_present", ""),
                "blocking_operator_count": structure.get("blocking_operator_count", ""),
                "dominant_time_node_type": structure.get("dominant_time_node_type", ""),
                "dominant_rows_node_type": structure.get("dominant_rows_node_type", ""),
                "query_run_id": query_run_id,
            }
        )
    return overview_rows


def corpus_cell_rows(
    *,
    database_sweep_id: str,
    query_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cells: dict[str, dict[str, Any]] = {}
    for row in query_rows:
        corpus_cell_id = str(row.get("corpus_cell_id", ""))
        if not corpus_cell_id:
            continue
        cell = cells.setdefault(
            corpus_cell_id,
            {
                "database_sweep_id": database_sweep_id,
                "corpus_id": row.get("corpus_id", ""),
                "corpus_cell_id": corpus_cell_id,
                "logical_question_id": row.get("logical_question_id", ""),
                "execution_strategy": row.get("execution_strategy", ""),
                "dataset_profile_id": row.get("dataset_profile_id", ""),
                "runtime_config_id": row.get("runtime_config_id", ""),
                "topology_id": row.get("topology_id", ""),
                "intervention_role": row.get("intervention_role", ""),
                "intervention_axis": row.get("intervention_axis", ""),
                "expected_regime_targets": row.get("expected_regime_targets", ""),
                "execution_class": row.get("execution_class", ""),
                "runtime_sensitivity": row.get("runtime_sensitivity", ""),
                "required_dataset_capabilities": row.get("required_dataset_capabilities", ""),
                "intervention_roles": row.get("intervention_roles", ""),
                "_query_sweep_ids": set(),
                "_template_ids": set(),
                "_instance_ids": set(),
                "_query_run_ids": set(),
            },
        )
        cell["_query_sweep_ids"].add(str(row.get("query_sweep_id", "")))
        cell["_template_ids"].add(str(row.get("template_id", "")))
        cell["_instance_ids"].add(str(row.get("instance_id", "")))
        cell["_query_run_ids"].add(str(row.get("query_run_id", "")))

    result: list[dict[str, Any]] = []
    for cell in cells.values():
        result.append(
            {key: value for key, value in cell.items() if not key.startswith("_")}
            | {
                "query_sweep_ids": ",".join(sorted(cell["_query_sweep_ids"] - {""})),
                "template_ids": ",".join(sorted(cell["_template_ids"] - {""})),
                "instance_ids": ",".join(sorted(cell["_instance_ids"] - {""})),
                "query_run_count": len(cell["_query_run_ids"] - {""}),
            }
        )
    return sorted(result, key=lambda item: str(item["corpus_cell_id"]))


def plan_task_summary(plan_file: Path) -> dict[str, str]:
    if not plan_file.exists() or not plan_file.is_file():
        return {
            "task_count": "",
            "tasks_shown": "",
            "tasks_materialized": "",
            "plan_parse_error": "plan file missing"
            if not plan_file.exists()
            else "plan path is not a file",
        }
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {
            "task_count": "",
            "tasks_shown": "",
            "tasks_materialized": "",
            "plan_parse_error": str(error),
        }

    stack: list[Any] = [plan]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if "Task Count" in value or "Tasks Shown" in value or "Tasks" in value:
                tasks = value.get("Tasks") or []
                return {
                    "task_count": value.get("Task Count", ""),
                    "tasks_shown": value.get("Tasks Shown", ""),
                    "tasks_materialized": len(tasks) if isinstance(tasks, list) else "",
                    "plan_parse_error": "",
                }
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return {
        "task_count": "",
        "tasks_shown": "",
        "tasks_materialized": "",
        "plan_parse_error": "",
    }


def phase_snapshot_rows(
    *,
    root: Path,
    database_sweep_id: str,
    query_sweep_id: str,
    dataset_id: str,
    runtime_config_id: str,
    phase: str,
    snapshot_dir: Path | None,
) -> list[dict[str, Any]]:
    if snapshot_dir is None or not snapshot_dir.exists():
        return []

    rows: list[dict[str, Any]] = []
    for node_dir in sorted((snapshot_dir / "nodes").glob("*")):
        if not node_dir.is_dir():
            continue
        for run_dir in sorted(node_dir.iterdir()):
            snapshots_dir = run_dir / "snapshots"
            rows.append(
                {
                    "database_sweep_id": database_sweep_id,
                    "query_sweep_id": query_sweep_id,
                    "dataset_id": dataset_id,
                    "runtime_config_id": runtime_config_id,
                    "phase": phase,
                    "node_name": node_dir.name,
                    "snapshot_run_dir": rel(root, run_dir),
                    "snapshots_dir": rel(root, snapshots_dir),
                    "snapshot_file_count": len(list(snapshots_dir.glob("*")))
                    if snapshots_dir.exists()
                    else 0,
                }
            )
    return rows


def hardware_snapshot_rows(
    *,
    root: Path,
    database_sweep_id: str,
    snapshot_dir: Path | None,
) -> list[dict[str, Any]]:
    if snapshot_dir is None or not snapshot_dir.exists():
        return []
    manifest = maybe_load_json(snapshot_dir / "hardware_snapshot_manifest.json")
    snapshot_id = str(manifest.get("snapshot_id", snapshot_dir.name))
    rows: list[dict[str, Any]] = []
    for node_name, artifact_dir in sorted(manifest.get("local_artifacts", {}).items()):
        node_dir = snapshot_dir / str(artifact_dir)
        summary_file = node_dir / "hardware_summary.json"
        summary = maybe_load_json(summary_file)
        cpu = summary.get("cpu", {}) if isinstance(summary.get("cpu"), dict) else {}
        memory = summary.get("memory", {}) if isinstance(summary.get("memory"), dict) else {}
        storage = summary.get("storage", {}) if isinstance(summary.get("storage"), dict) else {}
        rows.append(
            {
                "database_sweep_id": database_sweep_id,
                "hardware_snapshot_id": snapshot_id,
                "node_name": node_name,
                "hostname": summary.get("hostname", ""),
                "kernel": summary.get("kernel", ""),
                "cpu_model": cpu.get("model_name", ""),
                "logical_cpus": cpu.get("logical_cpus", ""),
                "physical_cores": cpu.get("physical_cores", ""),
                "sockets": cpu.get("sockets", ""),
                "cores_per_socket": cpu.get("cores_per_socket", ""),
                "threads_per_core": cpu.get("threads_per_core", ""),
                "cpu_mhz": cpu.get("cpu_mhz", ""),
                "cpu_max_mhz": cpu.get("cpu_max_mhz", ""),
                "hypervisor_vendor": cpu.get("hypervisor_vendor", ""),
                "ram_total_bytes": memory.get("total_bytes", ""),
                "ram_available_bytes": memory.get("available_bytes", ""),
                "ram_speed_values_mt_s": ",".join(
                    str(item) for item in memory.get("speed_values_mt_s", [])
                ),
                "ram_speed_source": memory.get("speed_source", ""),
                "disk_count": storage.get("disk_count", ""),
                "disk_total_bytes": storage.get("disk_total_bytes", ""),
                "storage_classes": ",".join(
                    str(item) for item in storage.get("storage_classes", [])
                ),
                "root_storage_class": storage.get("root_storage_class", ""),
                "postgres_storage_class": storage.get("postgres_storage_class", ""),
                "summary_file": rel(root, summary_file),
                "raw_file": rel(root, node_dir / "hardware_raw.json"),
            }
        )
    return rows


def first_remote_manifest(
    collection_dir: Path,
    collection_manifest: dict[str, Any],
) -> dict[str, Any]:
    coordinator = str(collection_manifest.get("coordinator", ""))
    artifact = collection_manifest.get("local_artifacts", {}).get(coordinator)
    if not artifact:
        return {}
    return maybe_load_json(collection_dir / artifact / "execution_manifest.json")


def query_params_json(query_execution: dict[str, Any]) -> str:
    if "params" in query_execution:
        return json_text(query_execution["params"])
    raw_value = str(query_execution.get("param_json", ""))
    if not raw_value:
        return "{}"
    try:
        return json_text(json.loads(raw_value))
    except json.JSONDecodeError:
        return json_text({"_raw": raw_value})


def build_index(sweep_dir: Path, out_dir: Path) -> dict[str, int]:
    root = sweep_dir.resolve()
    database_manifest = load_json(root / "database_sweep_manifest.json")
    database_sweep_id = str(database_manifest["sweep_id"])
    feature_schema_file = ""

    dataset_rows: list[dict[str, Any]] = []
    dataset_capability_rows: list[dict[str, Any]] = []
    runtime_rows: list[dict[str, Any]] = []
    query_rows: list[dict[str, Any]] = []
    node_rows: list[dict[str, Any]] = []
    global_snapshot_rows: list[dict[str, Any]] = []
    execution_feature_rows: list[dict[str, Any]] = []
    query_binding_rows: list[dict[str, Any]] = []
    query_node_rows: list[dict[str, Any]] = []
    plan_file_rows: list[dict[str, Any]] = []
    plan_node_rows: list[dict[str, Any]] = []
    plan_edge_rows: list[dict[str, Any]] = []
    plan_structure_rows: list[dict[str, Any]] = []
    fdw_remote_plan_rows: list[dict[str, Any]] = []
    region_fragment_rows: list[dict[str, Any]] = []
    worker_task_fragment_rows: list[dict[str, Any]] = []
    remote_edge_observation_rows: list[dict[str, Any]] = []
    instance_summary_rows: list[dict[str, Any]] = []
    result_validation_rows: list[dict[str, Any]] = []
    hardware_rows = hardware_snapshot_rows(
        root=root,
        database_sweep_id=database_sweep_id,
        snapshot_dir=Path(str(database_manifest["hardware_snapshot_dir"]))
        if database_manifest.get("hardware_snapshot_dir")
        else None,
    )
    indexed_dataset_load_dirs: set[str] = set()
    indexed_result_validation_dirs: set[str] = set()

    for execution in database_manifest.get("executions", []):
        dataset_id = str(execution.get("dataset_id", ""))
        runtime_config_id = str(execution.get("runtime_config_id", ""))
        dataset_load_dir = Path(str(execution.get("dataset_load_dir", "")))
        query_sweep_dir = Path(str(execution.get("query_sweep_dir", "")))
        dataset_load_manifest = maybe_load_json(dataset_load_dir / "dataset_load_manifest.json")
        query_sweep_manifest = load_json(query_sweep_dir / "query_sweep_manifest.json")
        query_sweep_id = str(query_sweep_manifest["sweep_id"])
        capability_audit = maybe_load_json(dataset_load_dir / "capability_audit.json")
        audit_path = dataset_load_dir / "capability_audit.json"
        parameter_values_path = dataset_load_dir / "dataset_parameter_values.json"
        load_dir_key = str(dataset_load_dir.resolve())
        correctness_raw = str(execution.get("correctness_validation_dir", ""))
        correctness_dir = Path(correctness_raw) if correctness_raw else Path()
        correctness_key = str(correctness_dir.resolve()) if correctness_raw else ""
        if (
            correctness_key
            and correctness_key not in indexed_result_validation_dirs
            and correctness_dir.exists()
        ):
            indexed_result_validation_dirs.add(correctness_key)
            for row in read_csv(correctness_dir / "result_equivalence.csv"):
                result_validation_rows.append(
                    {
                        "database_sweep_id": database_sweep_id,
                        "dataset_id": dataset_id,
                        "validation_dir": rel(root, correctness_dir),
                        **row,
                    }
                )

        index_context = {
            "root": root,
            "database_sweep_id": database_sweep_id,
            "query_sweep_id": query_sweep_id,
            "dataset_id": dataset_id,
            "runtime_config_id": runtime_config_id,
            "query_sweep_dir": query_sweep_dir,
        }
        net_ctx = network_context(root=root, execution=execution)
        execution_feature_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="query_runs.csv", **index_context),
                net_ctx,
            )
        )
        query_binding_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="query_bindings.csv", **index_context),
                net_ctx,
            )
        )
        query_node_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="query_nodes.csv", **index_context),
                net_ctx,
            )
        )
        plan_file_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="plan_files.csv", **index_context),
                net_ctx,
            )
        )
        plan_node_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="plan_nodes.csv", **index_context),
                net_ctx,
            )
        )
        plan_edge_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="plan_edges.csv", **index_context),
                net_ctx,
            )
        )
        plan_structure_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="plan_structure_features.csv", **index_context),
                net_ctx,
            )
        )
        fdw_remote_plan_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="fdw_remote_plans.csv", **index_context),
                net_ctx,
            )
        )
        region_fragment_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="region_fragments.csv", **index_context),
                net_ctx,
            )
        )
        worker_task_fragment_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="worker_task_fragments.csv", **index_context),
                net_ctx,
            )
        )
        remote_edge_observation_rows.extend(
            with_context(
                query_sweep_index_rows(
                    table_name="remote_edge_observations.csv",
                    **index_context,
                ),
                net_ctx,
            )
        )
        instance_summary_rows.extend(
            with_context(
                query_sweep_index_rows(table_name="instance_summary_features.csv", **index_context),
                net_ctx,
            )
        )

        dataset_rows.append(
            {
                "database_sweep_id": database_sweep_id,
                "dataset_id": dataset_id,
                "dataset_load_id": dataset_load_manifest.get("load_id", dataset_load_dir.name),
                "profile_dataset_id": dataset_load_manifest.get("dataset_id", ""),
                "region": dataset_load_manifest.get("region", database_manifest.get("region", "")),
                "dataset_profile": rel(root, execution.get("dataset_profile")),
                "dataset_load_dir": rel(root, dataset_load_dir),
                "capability_audit_file": rel_if_exists(root, audit_path),
                "dataset_parameter_values_file": rel_if_exists(root, parameter_values_path),
                "capability_audit_status": capability_audit.get("status", ""),
                "datagen_env_json": json_text(dataset_load_manifest.get("datagen_env", {})),
            }
        )
        if load_dir_key not in indexed_dataset_load_dirs:
            indexed_dataset_load_dirs.add(load_dir_key)
            tenant_skew = (
                capability_audit.get("tenant_skew", {})
                if isinstance(capability_audit.get("tenant_skew"), dict)
                else {}
            )
            shard_distribution = (
                capability_audit.get("shard_distribution", {})
                if isinstance(capability_audit.get("shard_distribution"), dict)
                else {}
            )
            parameter_values = (
                capability_audit.get("dataset_parameter_values", {})
                if isinstance(capability_audit.get("dataset_parameter_values"), dict)
                else {}
            )
            dataset_capability_rows.append(
                {
                    "database_sweep_id": database_sweep_id,
                    "dataset_id": dataset_id,
                    "dataset_load_id": dataset_load_manifest.get("load_id", dataset_load_dir.name),
                    "profile_dataset_id": dataset_load_manifest.get("dataset_id", ""),
                    "region": dataset_load_manifest.get(
                        "region", database_manifest.get("region", "")
                    ),
                    "dataset_load_dir": rel(root, dataset_load_dir),
                    "capability_audit_file": rel_if_exists(root, audit_path),
                    "dataset_parameter_values_file": rel_if_exists(root, parameter_values_path),
                    "status": capability_audit.get("status", ""),
                    "warnings_json": json_text(capability_audit.get("warnings", [])),
                    "declared_distribution_json": json_text(
                        capability_audit.get("declared_distribution", {})
                    ),
                    "declared_capabilities_json": json_text(
                        capability_audit.get("declared_capabilities", {})
                    ),
                    "measured_capabilities_json": json_text(
                        capability_audit.get("measured_capabilities", {})
                    ),
                    "table_counts_json": json_text(capability_audit.get("table_counts", {})),
                    "tenant_count": tenant_skew.get("tenant_count", ""),
                    "events_total": tenant_skew.get("events_total", ""),
                    "events_cv": tenant_skew.get("events_cv", ""),
                    "max_to_mean_ratio": tenant_skew.get("max_to_mean_ratio", ""),
                    "top1_event_share": tenant_skew.get("top1_event_share", ""),
                    "top5_event_share": tenant_skew.get("top5_event_share", ""),
                    "tenant_parameter_count": parameter_values.get("tenant_count", ""),
                    "hot_tenant_parameter_count": parameter_values.get("hot_tenant_count", ""),
                    "shard_distribution_status": shard_distribution.get("status", ""),
                    "shard_distribution_row_count": shard_distribution.get("row_count", ""),
                }
            )

        before_dir = query_sweep_manifest.get("global_snapshot_before_dir")
        after_dir = query_sweep_manifest.get("global_snapshot_after_dir")
        runtime_rows.append(
            {
                "database_sweep_id": database_sweep_id,
                "query_sweep_id": query_sweep_id,
                "dataset_id": dataset_id,
                "runtime_config_id": runtime_config_id,
                "query_sweep_dir": rel(root, query_sweep_dir),
                "query_sweep_status": query_sweep_manifest.get("status", ""),
                "global_stats_scope": query_sweep_manifest.get("global_stats_scope", ""),
                "global_snapshot_before_dir": rel(root, before_dir),
                "global_snapshot_after_dir": rel(root, after_dir),
                "runtime_intervention_axis": execution.get("runtime_intervention_axis", ""),
                "runtime_expected_effect": execution.get("runtime_expected_effect", ""),
                **net_ctx,
                "pg_options_json": json_text(execution.get("pg_options", {})),
                "psql_variables_json": json_text(execution.get("psql_variables", {})),
                "fdw_server_options_json": json_text(execution.get("fdw_server_options", {})),
                "query_count": len(query_sweep_manifest.get("executions", [])),
                "query_count_by_status_json": json_text(
                    query_sweep_manifest.get("query_count_by_status", {})
                ),
            }
        )

        global_snapshot_rows.extend(
            phase_snapshot_rows(
                root=root,
                database_sweep_id=database_sweep_id,
                query_sweep_id=query_sweep_id,
                dataset_id=dataset_id,
                runtime_config_id=runtime_config_id,
                phase="before",
                snapshot_dir=Path(before_dir) if before_dir else None,
            )
        )
        global_snapshot_rows.extend(
            phase_snapshot_rows(
                root=root,
                database_sweep_id=database_sweep_id,
                query_sweep_id=query_sweep_id,
                dataset_id=dataset_id,
                runtime_config_id=runtime_config_id,
                phase="after",
                snapshot_dir=Path(after_dir) if after_dir else None,
            )
        )

        for query_execution in query_sweep_manifest.get("executions", []):
            collection_dir = Path(str(query_execution["collection_dir"]))
            collection_manifest = load_json(collection_dir / "execution_manifest.json")
            remote_manifest = first_remote_manifest(collection_dir, collection_manifest)
            coordinator = str(collection_manifest.get("coordinator", ""))
            coordinator_artifact = collection_manifest.get("local_artifacts", {}).get(coordinator)
            coordinator_dir = (
                collection_dir / coordinator_artifact if coordinator_artifact else None
            )
            plan_file = (
                coordinator_dir / str(remote_manifest.get("plan_file", ""))
                if coordinator_dir is not None
                else Path()
            )
            plan_summary = plan_task_summary(plan_file)
            timing = remote_manifest.get("timing", {})
            query_run_id = str(collection_manifest["execution_id"])
            timeout_payload = collection_manifest.get("timeout") or {}

            query_rows.append(
                {
                    "database_sweep_id": database_sweep_id,
                    "query_sweep_id": query_sweep_id,
                    "query_run_id": query_run_id,
                    "execution_status": collection_manifest.get(
                        "execution_status", query_execution.get("execution_status", "")
                    ),
                    "timed_out": collection_manifest.get(
                        "timed_out", query_execution.get("timed_out", "")
                    ),
                    "hard_timeout_seconds": collection_manifest.get(
                        "hard_timeout_seconds",
                        query_execution.get("hard_timeout_seconds", ""),
                    ),
                    "timeout_phase": collection_manifest.get(
                        "timeout_phase",
                        query_execution.get("timeout_phase", timeout_payload.get("phase", "")),
                    ),
                    "dataset_id": dataset_id,
                    "runtime_config_id": runtime_config_id,
                    **net_ctx,
                    **{field: query_execution.get(field, "") for field in CORPUS_METADATA_FIELDS},
                    "instance_id": query_execution.get("instance_id", ""),
                    "template_id": query_execution.get("template_id", ""),
                    "param_json": query_params_json(query_execution),
                    "expected_shape_tags": query_execution.get("expected_shape_tags", ""),
                    "collection_dir": rel(root, collection_dir),
                    "source_sql_file": query_execution.get("rendered_sql_path", ""),
                    "query_sql_file": rel(root, collection_dir / "input" / "query.sql"),
                    "query_bindings_file": rel(
                        root,
                        collection_dir / "input" / "query_bindings.json",
                    ),
                    "coordinator_node": coordinator,
                    "created_at_utc": collection_manifest.get("created_at_utc", ""),
                    "elapsed_seconds": timing.get("elapsed_seconds", ""),
                    "query_started_at_unix": timing.get("query_started_at_unix", ""),
                    "query_finished_at_unix": timing.get("query_finished_at_unix", ""),
                    "plan_json_file": rel(root, plan_file),
                    "explain_text_file": rel(
                        root,
                        coordinator_dir / str(remote_manifest.get("explain_text_file", ""))
                        if coordinator_dir is not None
                        else None,
                    ),
                    "explain_text_sql_file": rel(
                        root,
                        coordinator_dir / str(remote_manifest.get("explain_text_sql_file", ""))
                        if coordinator_dir is not None
                        else None,
                    ),
                    "explain_analyze_json_sql_file": rel(
                        root,
                        coordinator_dir
                        / str(remote_manifest.get("explain_analyze_json_sql_file", ""))
                        if coordinator_dir is not None
                        else None,
                    ),
                    "task_count": plan_summary["task_count"],
                    "tasks_shown": plan_summary["tasks_shown"],
                    "tasks_materialized": plan_summary["tasks_materialized"],
                    "plan_parse_error": plan_summary["plan_parse_error"],
                    "pg_options_json": json_text(collection_manifest.get("pg_options", [])),
                    "psql_variables_json": json_text(collection_manifest.get("variables", [])),
                    "error_count": len(collection_manifest.get("errors", [])),
                }
            )

            for node_name, artifact_dir in sorted(
                collection_manifest.get("local_artifacts", {}).items()
            ):
                node_dir = collection_dir / artifact_dir
                metadata = maybe_load_json(node_dir / "metadata.json")
                snapshots_dir = node_dir / "snapshots"
                node_rows.append(
                    {
                        "database_sweep_id": database_sweep_id,
                        "query_sweep_id": query_sweep_id,
                        "query_run_id": query_run_id,
                        "dataset_id": dataset_id,
                        "runtime_config_id": runtime_config_id,
                        "instance_id": query_execution.get("instance_id", ""),
                        "node_name": node_name,
                        "node_role": metadata.get("node_role")
                        or metadata.get("bench_node_role", ""),
                        "node_artifact_dir": rel(root, node_dir),
                        "remote_run_dir": collection_manifest.get("node_run_dirs", {}).get(
                            node_name, ""
                        ),
                        "os_samples_file": rel_if_exists(
                            root,
                            node_dir / "metrics" / "os_samples.jsonl",
                        ),
                        "os_summary_file": rel_if_exists(
                            root,
                            node_dir / "metrics" / "os_summary.json",
                        ),
                        "metadata_file": rel_if_exists(root, node_dir / "metadata.json"),
                        "snapshot_file_count": len(list(snapshots_dir.glob("*")))
                        if snapshots_dir.exists()
                        else 0,
                    }
                )

    enrich_query_rows_from_execution_features(query_rows, execution_feature_rows)
    corpus_rows = corpus_cell_rows(
        database_sweep_id=database_sweep_id,
        query_rows=query_rows,
    )
    write_csv(
        out_dir / "corpus_cells.csv",
        corpus_rows,
        [
            "database_sweep_id",
            "corpus_id",
            "corpus_cell_id",
            "logical_question_id",
            "execution_strategy",
            "dataset_profile_id",
            "runtime_config_id",
            "topology_id",
            "intervention_role",
            "intervention_axis",
            "expected_regime_targets",
            "execution_class",
            "runtime_sensitivity",
            "required_dataset_capabilities",
            "intervention_roles",
            "query_sweep_ids",
            "template_ids",
            "instance_ids",
            "query_run_count",
        ],
    )
    write_csv(
        out_dir / "dataset_runs.csv",
        dataset_rows,
        [
            "database_sweep_id",
            "dataset_id",
            "dataset_load_id",
            "profile_dataset_id",
            "region",
            "dataset_profile",
            "dataset_load_dir",
            "capability_audit_file",
            "dataset_parameter_values_file",
            "capability_audit_status",
            "datagen_env_json",
        ],
    )
    write_csv(
        out_dir / "dataset_capability_audits.csv",
        dataset_capability_rows,
        [
            "database_sweep_id",
            "dataset_id",
            "dataset_load_id",
            "profile_dataset_id",
            "region",
            "dataset_load_dir",
            "capability_audit_file",
            "dataset_parameter_values_file",
            "status",
            "warnings_json",
            "declared_distribution_json",
            "declared_capabilities_json",
            "measured_capabilities_json",
            "table_counts_json",
            "tenant_count",
            "events_total",
            "events_cv",
            "max_to_mean_ratio",
            "top1_event_share",
            "top5_event_share",
            "tenant_parameter_count",
            "hot_tenant_parameter_count",
            "shard_distribution_status",
            "shard_distribution_row_count",
        ],
    )
    write_csv(
        out_dir / "runtime_sweeps.csv",
        runtime_rows,
        [
            "database_sweep_id",
            "query_sweep_id",
            "dataset_id",
            "runtime_config_id",
            "query_sweep_dir",
            "query_sweep_status",
            "global_stats_scope",
            "global_snapshot_before_dir",
            "global_snapshot_after_dir",
            "runtime_intervention_axis",
            "runtime_expected_effect",
            *NETWORK_CONTEXT_FIELDS,
            "pg_options_json",
            "psql_variables_json",
            "fdw_server_options_json",
            "query_count",
            "query_count_by_status_json",
        ],
    )
    write_csv(
        out_dir / "result_validations.csv",
        result_validation_rows,
        [
            "database_sweep_id",
            "dataset_id",
            "query_id",
            "expected_citus_strategy",
            "baseline_status",
            "eu_status",
            "us_status",
            "baseline_result_hash",
            "eu_result_hash",
            "us_result_hash",
            "schema_hash",
            "comparison_status",
            "tolerance_policy",
            "database_result_rows_persisted",
            "validation_dir",
        ],
    )
    write_csv(
        out_dir / "query_runs.csv",
        query_rows,
        [
            "database_sweep_id",
            "query_sweep_id",
            "query_run_id",
            "execution_status",
            "timed_out",
            "hard_timeout_seconds",
            "timeout_phase",
            "dataset_id",
            "runtime_config_id",
            *NETWORK_CONTEXT_FIELDS,
            *CORPUS_METADATA_FIELDS,
            "instance_id",
            "template_id",
            "param_json",
            "expected_shape_tags",
            "collection_dir",
            "source_sql_file",
            "query_sql_file",
            "query_bindings_file",
            "coordinator_node",
            "created_at_utc",
            "elapsed_seconds",
            "query_started_at_unix",
            "query_finished_at_unix",
            "plan_json_file",
            "explain_text_file",
            "explain_text_sql_file",
            "explain_analyze_json_sql_file",
            "task_count",
            "tasks_shown",
            "tasks_materialized",
            "plan_parse_error",
            *QUERY_RUN_DERIVED_PASSTHROUGH_FIELDS,
            *COORDINATOR_PRESSURE_PASSTHROUGH_FIELDS,
            "pg_options_json",
            "psql_variables_json",
            "error_count",
        ],
    )
    write_csv(
        out_dir / "node_artifacts.csv",
        node_rows,
        [
            "database_sweep_id",
            "query_sweep_id",
            "query_run_id",
            "dataset_id",
            "runtime_config_id",
            "instance_id",
            "node_name",
            "node_role",
            "node_artifact_dir",
            "remote_run_dir",
            "os_samples_file",
            "os_summary_file",
            "metadata_file",
            "snapshot_file_count",
        ],
    )
    write_csv(
        out_dir / "global_snapshots.csv",
        global_snapshot_rows,
        [
            "database_sweep_id",
            "query_sweep_id",
            "dataset_id",
            "runtime_config_id",
            "phase",
            "node_name",
            "snapshot_run_dir",
            "snapshots_dir",
            "snapshot_file_count",
        ],
    )
    write_csv(
        out_dir / "hardware_nodes.csv",
        hardware_rows,
        [
            "database_sweep_id",
            "hardware_snapshot_id",
            "node_name",
            "hostname",
            "kernel",
            "cpu_model",
            "logical_cpus",
            "physical_cores",
            "sockets",
            "cores_per_socket",
            "threads_per_core",
            "cpu_mhz",
            "cpu_max_mhz",
            "hypervisor_vendor",
            "ram_total_bytes",
            "ram_available_bytes",
            "ram_speed_values_mt_s",
            "ram_speed_source",
            "disk_count",
            "disk_total_bytes",
            "storage_classes",
            "root_storage_class",
            "postgres_storage_class",
            "summary_file",
            "raw_file",
        ],
    )
    index_context_fields = [
        "database_sweep_id",
        "dataset_id",
        "runtime_config_id",
        *NETWORK_CONTEXT_FIELDS,
        "query_sweep_id",
        "query_sweep_dir",
        "query_sweep_index_dir",
    ]
    query_context_fields = [
        "database_sweep_id",
        "dataset_id",
        "runtime_config_id",
        *NETWORK_CONTEXT_FIELDS,
        *CORPUS_METADATA_FIELDS,
        "query_sweep_id",
        "query_sweep_dir",
        "query_sweep_index_dir",
    ]
    write_csv(
        out_dir / "execution_features.csv",
        execution_feature_rows,
        merged_fieldnames(
            execution_feature_rows,
            query_context_fields
            + [
                "query_run_id",
                "execution_status",
                "timed_out",
                "hard_timeout_seconds",
                "timeout_phase",
                "instance_id",
                "template_id",
                "sql_normalized_hash",
                "rendered_sql_hash",
                "plan_fingerprint",
                "remote_plan_fingerprint",
                "elapsed_seconds",
            ],
        ),
    )
    write_csv(
        out_dir / "query_bindings.csv",
        query_binding_rows,
        merged_fieldnames(
            query_binding_rows,
            index_context_fields + ["query_run_id", "instance_id", "template_id"],
        ),
    )
    write_csv(
        out_dir / "query_nodes.csv",
        query_node_rows,
        merged_fieldnames(
            query_node_rows,
            index_context_fields + ["query_run_id", "node_name", "node_role"],
        ),
    )
    write_csv(
        out_dir / "plan_files.csv",
        plan_file_rows,
        merged_fieldnames(
            plan_file_rows,
            index_context_fields + ["query_run_id", "plan_id", "plan_scope"],
        ),
    )
    write_csv(
        out_dir / "plan_nodes.csv",
        plan_node_rows,
        merged_fieldnames(
            plan_node_rows,
            index_context_fields
            + [
                "query_run_id",
                "plan_id",
                "plan_scope",
                "node_id",
                "parent_node_id",
                "child_index",
                "depth",
                "node_path",
                "node_type",
            ],
        ),
    )
    write_csv(
        out_dir / "plan_edges.csv",
        plan_edge_rows,
        merged_fieldnames(
            plan_edge_rows,
            index_context_fields
            + [
                "query_run_id",
                "plan_id",
                "plan_scope",
                "parent_node_id",
                "child_node_id",
                "parent_node_type",
                "child_node_type",
                "child_index",
            ],
        ),
    )
    write_csv(
        out_dir / "plan_structure_features.csv",
        plan_structure_rows,
        merged_fieldnames(
            plan_structure_rows,
            index_context_fields
            + [
                "query_run_id",
                "main_plan_node_count",
                "main_plan_max_depth",
                "remote_plan_leaf_count_sum",
            ],
        ),
    )
    write_csv(
        out_dir / "fdw_remote_plans.csv",
        fdw_remote_plan_rows,
        merged_fieldnames(
            fdw_remote_plan_rows,
            index_context_fields + ["query_run_id", "remote_sql_hash", "remote_plan_fingerprint"],
        ),
    )
    write_csv(
        out_dir / "region_fragments.csv",
        region_fragment_rows,
        merged_fieldnames(
            region_fragment_rows,
            index_context_fields
            + [
                "query_run_id",
                "instance_id",
                "template_id",
                "remote_plan_id",
                "region_id",
                "cluster_id",
                "source_type",
                "parse_status",
                "remote_plan_fingerprint",
            ],
        ),
    )
    write_csv(
        out_dir / "worker_task_fragments.csv",
        worker_task_fragment_rows,
        merged_fieldnames(
            worker_task_fragment_rows,
            index_context_fields
            + [
                "query_run_id",
                "instance_id",
                "template_id",
                "plan_id",
                "remote_sql_id",
                "fdw_region",
                "task_index",
                "worker_node",
                "worker_task_plan_fingerprint",
                "worker_task_root_node_type",
            ],
        ),
    )
    write_csv(
        out_dir / "remote_edge_observations.csv",
        remote_edge_observation_rows,
        merged_fieldnames(
            remote_edge_observation_rows,
            index_context_fields
            + [
                "query_run_id",
                "edge_id",
                "source_cluster_id",
                "destination_gac_id",
            ],
        ),
    )
    write_csv(
        out_dir / "instance_summary_features.csv",
        instance_summary_rows,
        merged_fieldnames(
            instance_summary_rows,
            index_context_fields + ["instance_id", "template_id", "execution_count"],
        ),
    )
    feature_overview = feature_overview_rows(
        execution_rows=execution_feature_rows,
        structure_rows=plan_structure_rows,
    )
    write_csv(
        out_dir / "feature_overview.csv",
        feature_overview,
        [
            "row_index",
            "dataset_id",
            "runtime_config_id",
            "network_profile_id",
            "configured_latency_ms",
            "network_intervention_apply_status",
            "network_intervention_reset_status",
            "corpus_cell_id",
            "logical_question_id",
            "execution_strategy",
            "intervention_role",
            "intervention_axis",
            "expected_regime_targets",
            "execution_class",
            "template_id",
            "instance_id",
            "execution_status",
            "timed_out",
            "hard_timeout_seconds",
            "timeout_phase",
            "elapsed_seconds",
            "collection_error_count",
            "fdw_remote_probe_status",
            "fdw_remote_sql_count",
            "main_has_foreign_scan",
            "main_has_remote_sql",
            "remote_path_applicable",
            "fan_in_metric_available",
            "citus_task_metrics_available",
            "structure_features_available",
            "overview_missing_reason",
            "result_width_class",
            "estimated_fanin_bytes",
            "task_count",
            "task_rows_cv",
            "worker_rows_cv",
            "worker_time_cv",
            "citus_map_merge_job_count",
            "citus_repartition_query",
            "citus_tasks_shown_none",
            "main_plan_node_count",
            "main_plan_max_depth",
            "aggregate_above_foreign_scan",
            "join_above_foreign_scan",
            "remote_aggregate_present",
            "remote_join_present",
            "blocking_operator_count",
            "dominant_time_node_type",
            "dominant_rows_node_type",
            "query_run_id",
        ],
    )
    for schema_source in feature_schema_sources(root):
        (out_dir / "feature_schema.yml").write_text(
            schema_source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        feature_schema_file = "feature_schema.yml"
        break

    counts = {
        "dataset_runs": len(dataset_rows),
        "corpus_cells": len(corpus_rows),
        "dataset_capability_audits": len(dataset_capability_rows),
        "runtime_sweeps": len(runtime_rows),
        "query_runs": len(query_rows),
        "node_artifacts": len(node_rows),
        "global_snapshots": len(global_snapshot_rows),
        "hardware_nodes": len(hardware_rows),
        "execution_features": len(execution_feature_rows),
        "query_bindings": len(query_binding_rows),
        "query_nodes": len(query_node_rows),
        "plan_files": len(plan_file_rows),
        "plan_nodes": len(plan_node_rows),
        "plan_edges": len(plan_edge_rows),
        "plan_structure_features": len(plan_structure_rows),
        "fdw_remote_plans": len(fdw_remote_plan_rows),
        "region_fragments": len(region_fragment_rows),
        "worker_task_fragments": len(worker_task_fragment_rows),
        "remote_edge_observations": len(remote_edge_observation_rows),
        "instance_summary_features": len(instance_summary_rows),
        "feature_overview": len(feature_overview),
        "result_validations": len(result_validation_rows),
    }
    (out_dir / "index_manifest.json").write_text(
        json.dumps(
            {
                "database_sweep_id": database_sweep_id,
                "database_sweep_dir": str(root),
                "tables": counts,
                "region_fragment_count": len(region_fragment_rows),
                "worker_task_fragment_count": len(worker_task_fragment_rows),
                "remote_edge_observation_count": len(remote_edge_observation_rows),
                "primary_table": "query_runs.csv",
                "feature_schema_file": feature_schema_file,
                "feature_schema_contract": "master_regimes_feature_schema_v1"
                if feature_schema_file
                else "",
                "join_keys": {
                    "dataset_runs.csv": ["database_sweep_id", "dataset_id"],
                    "corpus_cells.csv": ["database_sweep_id", "corpus_cell_id"],
                    "dataset_capability_audits.csv": [
                        "database_sweep_id",
                        "dataset_id",
                        "dataset_load_id",
                    ],
                    "runtime_sweeps.csv": [
                        "database_sweep_id",
                        "query_sweep_id",
                        "dataset_id",
                        "runtime_config_id",
                    ],
                    "result_validations.csv": [
                        "database_sweep_id",
                        "dataset_id",
                        "query_id",
                    ],
                    "query_runs.csv": ["database_sweep_id", "query_sweep_id", "query_run_id"],
                    "execution_features.csv": [
                        "database_sweep_id",
                        "query_sweep_id",
                        "query_run_id",
                    ],
                    "node_artifacts.csv": ["query_run_id", "node_name"],
                    "global_snapshots.csv": ["query_sweep_id", "phase", "node_name"],
                    "hardware_nodes.csv": ["database_sweep_id", "node_name"],
                    "query_bindings.csv": ["query_run_id"],
                    "query_nodes.csv": ["query_run_id", "node_name"],
                    "plan_files.csv": ["query_run_id", "plan_id"],
                    "plan_nodes.csv": ["query_run_id", "plan_id", "node_id"],
                    "plan_edges.csv": [
                        "query_run_id",
                        "plan_id",
                        "parent_node_id",
                        "child_node_id",
                    ],
                    "plan_structure_features.csv": ["query_run_id"],
                    "fdw_remote_plans.csv": ["query_run_id", "remote_sql_hash"],
                    "region_fragments.csv": ["query_run_id", "region_id", "remote_plan_id"],
                    "worker_task_fragments.csv": [
                        "query_run_id",
                        "fdw_region",
                        "task_index",
                        "worker_node",
                    ],
                    "remote_edge_observations.csv": [
                        "query_run_id",
                        "edge_id",
                    ],
                    "instance_summary_features.csv": ["database_sweep_id", "instance_id"],
                    "feature_overview.csv": ["row_index", "query_run_id"],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "README.md").write_text(
        "# Database Sweep Index\n\n"
        "`query_runs.csv` is the sweep manifest fact table. "
        "`execution_features.csv` is the consolidated query-run feature table "
        "copied from each nested query-sweep `_index`, with `database_sweep_id`, "
        "`dataset_id`, `runtime_config_id`, and `query_sweep_id` attached.\n\n"
        "`dataset_capability_audits.csv` is one row per dataset load. It "
        "summarizes row counts, tenant skew, hot tenant shares and declared vs "
        "measured dataset capabilities from `dataset-loads/<load-id>/`. "
        "`dataset_parameter_values_file` points to the tenant/hot-tenant "
        "parameter pool that workload instances can use without hand-picking "
        "values.\n\n"
        "`result_validations.csv` contains the STATS-CEB baseline/EU/US "
        "correctness contract when that adapter is active. It stores hashes and "
        "statuses only; database result rows are never persisted.\n\n"
        "`feature_overview.csv` is a compact human QA table. It intentionally "
        "omits long paths, JSON blobs and fingerprints; use it for quick reading, "
        "not as the canonical source of truth. Blank numeric cells in this file "
        "mean missing or not-applicable, not zero. Use the `*_available`, "
        "`*_applicable`, and `overview_missing_reason` columns to distinguish "
        "expected blanks from collection problems.\n\n"
        "Use `plan_structure_features.csv` for one-row-per-query-run plan "
        "structure features. Use `plan_nodes.csv` and `plan_edges.csv` when the "
        "plan tree must be reconstructed. `region_fragments.csv`, "
        "`worker_task_fragments.csv`, and `remote_edge_observations.csv` are "
        "child evidence tables for N+1 GAC/FDW plans and edge context; they may "
        "have many rows per query run and must be aggregated "
        "back through `remote_region_*` and `worker_task_*` features before "
        "clustering. Join by `query_run_id` for query-level tables, and by "
        "`database_sweep_id` plus `node_name` for static hardware context in "
        "`hardware_nodes.csv`.\n",
        encoding="utf-8",
    )
    return counts


def main() -> int:
    args = parse_args()
    sweep_dir = args.sweep_dir.resolve()
    out_dir = args.out_dir.resolve() if args.out_dir else sweep_dir / "_index"
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = build_index(sweep_dir, out_dir)
    print(json.dumps({"index_dir": str(out_dir), "tables": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
