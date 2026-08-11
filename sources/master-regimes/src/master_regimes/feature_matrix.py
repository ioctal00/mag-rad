from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .config import load_yaml, write_yaml

IDENTITY_COLUMNS = [
    "condition_id",
    "database_sweep_id",
    "dataset_id",
    "runtime_config_id",
    "corpus_id",
    "corpus_cell_id",
    "logical_question_id",
    "execution_strategy",
    "query_sweep_id",
    "query_run_id",
    "instance_id",
    "template_id",
]

QUALITY_COLUMNS = [
    "execution_status",
    "timed_out",
    "collection_error_count",
    "remote_error_count",
    "fdw_remote_probe_status",
    "warmup_run_flag",
]

RAW_CONTEXT_COLUMNS = [
    "sql_normalized_hash",
    "rendered_sql_hash",
    "plan_fingerprint",
    "remote_plan_fingerprint",
    "remote_plan_fingerprints_json",
    "param_json",
    "expected_shape_tags",
    "collection_dir",
    "source_sql_file",
    "query_sql_file",
    "query_bindings_file",
    "coordinator_node",
    "created_at_utc",
    "query_started_at_unix",
    "query_finished_at_unix",
    "repetition_index",
    "run_order",
    "warmup_run_flag",
    "cache_policy",
    "same_instance_previous_execution_gap_seconds",
    "psql_variables_json",
    "pg_options_json",
    "work_mem",
    "fetch_size",
    "fdw_server_options_json",
    "network_profile_json",
    "network_profile_id",
    "network_intervention_scope",
    "network_intervention_apply_status",
    "network_intervention_reset_status",
    "network_intervention_apply_dir",
    "network_intervention_reset_dir",
    "configured_latency_ms",
    "configured_jitter_ms",
    "configured_loss_percent",
    "configured_bandwidth_mbit",
    "os_sampled_node_count",
    "os_sample_count_sum",
    "os_cpu_busy_pct_mean",
    "os_net_rx_bytes_sum",
    "os_net_tx_bytes_sum",
    "os_net_rx_packets_sum",
    "os_net_tx_packets_sum",
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
    "pressure_axis",
    "pressure_level",
    "pressure_pair_key",
    "physical_strategy_id",
    "scenario_level",
    "join_shape_id",
    "coordinator_pressure_kind",
    "coordinator_shape_id",
    "mitigation_action",
    "target_metric",
    "dataset_role",
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
    "coordinator_sort_operator_count",
    "coordinator_sort_input_rows_sum",
    "coordinator_sort_input_rows_max",
    "coordinator_sort_output_rows_sum",
    "coordinator_sort_time_ms_max",
    "coordinator_aggregate_operator_count",
    "coordinator_aggregate_input_rows_sum",
    "coordinator_aggregate_input_rows_max",
    "coordinator_aggregate_output_rows_sum",
    "coordinator_aggregate_time_ms_max",
    "coordinator_join_operator_count",
    "coordinator_join_input_rows_sum",
    "coordinator_join_input_rows_max",
    "coordinator_join_output_rows_sum",
    "coordinator_join_time_ms_max",
    "coordinator_unique_operator_count",
    "coordinator_unique_input_rows_sum",
    "coordinator_unique_input_rows_max",
    "coordinator_unique_output_rows_sum",
    "coordinator_unique_time_ms_max",
    "coordinator_window_operator_count",
    "coordinator_window_input_rows_sum",
    "coordinator_window_input_rows_max",
    "coordinator_window_output_rows_sum",
    "coordinator_window_time_ms_max",
    "coordinator_limit_operator_count",
    "coordinator_limit_input_rows_sum",
    "coordinator_limit_input_rows_max",
    "coordinator_limit_output_rows_sum",
    "coordinator_limit_time_ms_max",
    "citus_top_task_count",
    "citus_map_merge_job_count",
    "citus_dependent_map_task_count_sum",
    "citus_dependent_merge_task_count_sum",
    "citus_repartition_fanout_ratio",
    "citus_plan_locality_class",
    "remote_citus_tasks_shown_none_count",
    "remote_citus_task_list_available_count",
    "remote_citus_tuple_bytes_unsupported_count",
    "remote_citus_map_merge_job_count_sum",
    "remote_citus_dependent_map_task_count_sum",
    "remote_citus_dependent_merge_task_count_sum",
    "remote_citus_repartition_fanout_ratio_max",
    "remote_citus_router_single_task_count",
    "remote_citus_reference_join_candidate_count",
    "remote_citus_colocated_join_candidate_count",
    "remote_citus_repartition_mapmerge_count",
    "remote_citus_plan_locality_classes",
    "remote_citus_dominant_plan_locality_class",
    "citus_repartition_observed_v2",
    "worker_task_tuple_bytes_sum",
    "worker_task_tuple_bytes_cv",
    "worker_task_tuple_bytes_max_share",
    "worker_task_tuple_bytes_isf",
    "worker_task_tuple_bytes_isf_normalized",
    "worker_task_tuple_bytes_skew_applicable",
    "worker_task_tuple_bytes_skew_applicable_region_count",
    "worker_task_nonzero_scan_count",
    "worker_task_nonzero_scan_share",
    "worker_task_active_scan_rows_isf",
    "worker_task_active_scan_rows_isf_normalized",
    "worker_task_active_scan_skew_applicable",
    "worker_task_active_scan_skew_applicable_region_count",
    "worker_task_scan_skew_applicable",
    "worker_task_scan_skew_applicable_region_count",
    "worker_task_actual_time_isf",
    "worker_task_actual_time_isf_normalized",
    "worker_task_worker_count",
    "worker_task_count_cv",
    "worker_task_count_max_share",
    "worker_task_count_isf",
    "worker_task_count_isf_normalized",
    "worker_rows_cv",
    "worker_rows_max_share",
    "worker_rows_isf",
    "worker_rows_isf_normalized",
    "worker_time_cv",
    "worker_time_max_share",
    "worker_time_isf",
    "worker_time_isf_normalized",
    "worker_scan_rows_sum",
    "worker_scan_rows_worker_count",
    "worker_scan_rows_cv",
    "worker_scan_rows_cv_normalized",
    "worker_scan_rows_max_share",
    "worker_scan_rows_isf",
    "worker_scan_rows_isf_normalized",
    "worker_scan_rows_skew_applicable",
    "worker_scan_rows_skew_applicable_region_count",
    "worker_task_within_region_worker_scan_rows_cv_max",
    "worker_task_within_region_worker_scan_rows_cv_mean",
    "worker_task_within_region_worker_scan_rows_max_share_max",
    "worker_task_within_region_worker_scan_rows_isf_max",
    "worker_task_within_region_worker_scan_rows_isf_normalized_max",
    "worker_task_within_region_scan_rows_isf_normalized_max",
    "worker_task_within_region_active_scan_rows_isf_normalized_max",
    "worker_task_within_region_tuple_bytes_isf_normalized_max",
]

FDW_PUSHDOWN_FIDELITY_CONTRACT = "fdw_pushdown_fidelity_v1"

REMOTE_SCOPES = {"fdw_remote", "fdw_auto_explain_remote", "citus_task_remote"}
TOPOLOGY_ORDER = {
    "eu_only": 0,
    "eu_us": 1,
    "multi_region": 2,
}
WORKER_NODE_COUNT_FEATURES = {
    "Seq Scan": "worker_node_count_seq_scan",
    "Index Scan": "worker_node_count_index_scan",
    "Index Only Scan": "worker_node_count_index_only_scan",
    "Bitmap Heap Scan": "worker_node_count_bitmap_heap_scan",
    "Bitmap Index Scan": "worker_node_count_bitmap_index_scan",
    "Hash Join": "worker_node_count_hash_join",
    "Merge Join": "worker_node_count_merge_join",
    "Nested Loop": "worker_node_count_nested_loop",
    "Sort": "worker_node_count_sort",
    "Incremental Sort": "worker_node_count_incremental_sort",
    "HashAggregate": "worker_node_count_hash_aggregate",
    "GroupAggregate": "worker_node_count_group_aggregate",
    "Aggregate": "worker_node_count_aggregate",
    "Materialize": "worker_node_count_materialize",
    "Memoize": "worker_node_count_memoize",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _schema_path(index_dir: Path, explicit_schema: Path | None) -> Path:
    if explicit_schema is not None:
        return explicit_schema.resolve()
    local = index_dir / "feature_schema.yml"
    if local.exists():
        return local
    return _repo_root() / "docs" / "feature_schema.yml"


def _schema_entries(schema: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key in ("columns", "column_patterns"):
        values = schema.get(key, [])
        if isinstance(values, list):
            result.extend(entry for entry in values if isinstance(entry, dict))
    return result


def _all_fields(rows: list[dict[str, Any]]) -> list[str]:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                seen.add(field)
                fields.append(field)
    return fields


def _group_by_query_run(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        query_run_id = str(row.get("query_run_id", ""))
        if query_run_id:
            groups[query_run_id].append(row)
    return groups


def _one_by_query_run(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        query_run_id = str(row.get("query_run_id", ""))
        if query_run_id and query_run_id not in result:
            result[query_run_id] = row
    return result


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _int_or_none(value: Any) -> int | None:
    try:
        return int(float(value))
    except TypeError, ValueError:
        return None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _bool_number(value: bool) -> int:
    return 1 if value else 0


def _is_blank(value: Any) -> bool:
    return value in ("", None)


def _blank_if_none(value: Any) -> Any:
    return "" if value is None else value


def _safe_divide(numerator: Any, denominator: Any) -> float | None:
    left = _float_or_none(numerator)
    right = _float_or_none(denominator)
    if left is None or right is None or right <= 0:
        return None
    return left / right


def _safe_divide_floor(numerator: Any, denominator: Any, *, floor: float = 1.0) -> float | None:
    left = _float_or_none(numerator)
    right = _float_or_none(denominator)
    if left is None or right is None:
        return None
    return left / max(right, floor)


def _safe_log_ratio(value: Any) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None or numeric <= 0:
        return None
    return math.log(numeric)


def _first_number(row: dict[str, Any], fields: list[str]) -> float | None:
    for field in fields:
        value = _float_or_none(row.get(field))
        if value is not None:
            return value
    return None


def _set_number(row: dict[str, Any], field: str, value: float | None) -> None:
    if value is not None:
        row[field] = value


def _dataset_profile_slug(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"-v[0-9]+$", "", text)
    return text


def _dataset_profile_path_for_slug(slug: str) -> Path | None:
    if not slug:
        return None
    profile_path = _repo_root() / "datasets" / "profiles" / f"{slug}.yml"
    return profile_path if profile_path.exists() else None


def _dataset_profile_path(row: dict[str, Any]) -> Path | None:
    for field in ("dataset_profile_id", "dataset_id"):
        slug = _dataset_profile_slug(row.get(field))
        profile_path = _dataset_profile_path_for_slug(slug)
        if profile_path is not None:
            return profile_path
    return None


def _dataset_shard_count(row: dict[str, Any]) -> float | None:
    profile_path = _dataset_profile_path(row)
    if profile_path is not None:
        profile = load_yaml(profile_path)
        distribution = profile.get("distribution", {}) if isinstance(profile, dict) else {}
        shard_count = _float_or_none(distribution.get("shard_count"))
        if shard_count is not None and shard_count > 0:
            return shard_count
    for fallback_field in (
        "dataset_shard_count",
        "remote_region_task_count_mean",
        "remote_region_task_count_min",
        "remote_region_task_count_max",
    ):
        shard_count = _float_or_none(row.get(fallback_field))
        if shard_count is not None and shard_count > 0:
            return shard_count
    return None


def _topology_defaults(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    topology_id = str(row.get("topology_id") or row.get("topology") or "").strip()
    observed_or_configured_region_count = _first_number(
        row,
        [
            "configured_region_count",
            "remote_region_count",
            "remote_region_observed_count",
            "remote_region_nonzero_count",
        ],
    )
    configured_worker_count_per_region = _first_number(
        row,
        ["configured_worker_count_per_region", "worker_count_per_region"],
    )
    if observed_or_configured_region_count is not None and observed_or_configured_region_count > 0:
        # Keep the feature layer N-region friendly. Named topology ids describe
        # current deployments, but observed/configured region count is the
        # stronger evidence when future runs contain 3+ regional clusters.
        worker_count = configured_worker_count_per_region or 2.0
        return (
            observed_or_configured_region_count,
            worker_count,
            observed_or_configured_region_count * worker_count,
        )
    if topology_id == "eu_us_gac":
        return 2.0, 2.0, 4.0
    if topology_id in {"eu_gac", "eu_only", "eu-vps-single", "eu_vps_single"}:
        return 1.0, 2.0, 2.0
    return None, None, None


def _isf_from_max_share(
    row: dict[str, Any],
    max_share_field: str,
    count_field: str,
) -> float | None:
    max_share = _float_or_none(row.get(max_share_field))
    count = _float_or_none(row.get(count_field))
    if max_share is None or count is None or count <= 0:
        return None
    return max_share * count


def _normalized_isf(isf: Any, count: Any) -> float | None:
    value = _float_or_none(isf)
    unit_count = _float_or_none(count)
    if value is None or unit_count is None or unit_count <= 0:
        return None
    if unit_count == 1:
        return 0.0
    return max(0.0, min(1.0, (value - 1.0) / (unit_count - 1.0)))


def _normalized_population_cv(cv: Any, count: Any) -> float | None:
    value = _float_or_none(cv)
    unit_count = _float_or_none(count)
    if value is None or unit_count is None or unit_count <= 0:
        return None
    if unit_count == 1:
        return 0.0
    return max(0.0, min(1.0, value / math.sqrt(unit_count - 1.0)))


def _rows_estimate_error_log(row: dict[str, Any]) -> float | None:
    actual_rows = _float_or_none(row.get("actual_rows"))
    plan_rows = _float_or_none(row.get("plan_rows"))
    if actual_rows is None or plan_rows is None:
        return None
    return math.log((actual_rows + 1.0) / (plan_rows + 1.0))


def _largest_abs_signed(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values, key=lambda value: (abs(value), value))


def _node_type_slug(value: Any) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", str(value or ""))
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Unknown"


def _is_join(node_type: str) -> bool:
    return "Join" in node_type or node_type == "Nested Loop"


def _is_hash(node_type: str) -> bool:
    return "Hash" in node_type


def _is_aggregate(node_type: str) -> bool:
    return "Aggregate" in node_type


def _is_sort(node_type: str) -> bool:
    return node_type in {"Sort", "Incremental Sort"} or "Sort" in node_type


def _actual_rows(row: dict[str, Any]) -> float | None:
    rows = _float_or_none(row.get("actual_rows"))
    loops = _float_or_none(row.get("actual_loops"))
    if rows is None:
        return None
    return rows * (loops if loops is not None else 1.0)


def _actual_time(row: dict[str, Any]) -> float | None:
    time = _float_or_none(row.get("actual_total_time"))
    loops = _float_or_none(row.get("actual_loops"))
    if time is None:
        return None
    return time * (loops if loops is not None else 1.0)


def _root_node(nodes: list[dict[str, str]]) -> dict[str, str] | None:
    if not nodes:
        return None
    return sorted(
        nodes,
        key=lambda row: (
            _int_or_none(row.get("depth")) if _int_or_none(row.get("depth")) is not None else 9999,
            str(row.get("node_path", "")),
            str(row.get("node_id", "")),
        ),
    )[0]


def _max_numeric(rows: list[dict[str, str]], field: str) -> float | str:
    values = [
        value for value in (_float_or_none(row.get(field)) for row in rows) if value is not None
    ]
    return max(values) if values else ""


def _sum_numeric(rows: list[dict[str, str]], field: str) -> float | str:
    values = [
        value for value in (_float_or_none(row.get(field)) for row in rows) if value is not None
    ]
    return sum(values) if values else ""


def _estimate_bytes(rows: float | None, width: float | None) -> float | None:
    if rows is None or width is None:
        return None
    return rows * width


_QUERY_SWEEP_DIR_RESOLVE_CACHE: dict[tuple[str, str], Path | None] = {}


def _logical_corpus_root(index_dir: Path | None) -> Path | None:
    if index_dir is None:
        return None
    resolved = index_dir.resolve()
    parts = resolved.parts
    if "_logical-runs" not in parts:
        return None
    logical_idx = parts.index("_logical-runs")
    if logical_idx == 0:
        return None
    return Path(*parts[:logical_idx])


def _resolve_query_sweep_dir_from_logical_index(
    index_dir: Path | None,
    query_sweep_dir: Any,
) -> Path | None:
    corpus_root = _logical_corpus_root(index_dir)
    text = str(query_sweep_dir or "").strip()
    if corpus_root is None or not text:
        return None
    key = (str(corpus_root), text)
    if key in _QUERY_SWEEP_DIR_RESOLVE_CACHE:
        return _QUERY_SWEEP_DIR_RESOLVE_CACHE[key]
    matches = list(corpus_root.glob(f"*/database-sweeps/*/{text}"))
    resolved = matches[0] if matches else None
    _QUERY_SWEEP_DIR_RESOLVE_CACHE[key] = resolved
    return resolved


def _resolve_artifact_path(
    index_dir: Path | None,
    value: Any,
    *,
    row: dict[str, Any] | None = None,
) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    candidates: list[Path] = []
    if index_dir is not None:
        candidates.extend([index_dir / path, index_dir.parent / path])
        query_sweep_dir = str((row or {}).get("query_sweep_dir") or "").strip()
        if query_sweep_dir:
            candidates.append(index_dir.parent / query_sweep_dir / path)
            resolved_query_sweep_dir = _resolve_query_sweep_dir_from_logical_index(
                index_dir,
                query_sweep_dir,
            )
            if resolved_query_sweep_dir is not None:
                candidates.append(resolved_query_sweep_dir / path)
    candidates.append(path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def _load_plan_json_root(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and isinstance(first.get("Plan"), dict):
            return first["Plan"]
    if isinstance(payload, dict) and isinstance(payload.get("Plan"), dict):
        return payload["Plan"]
    if isinstance(payload, dict) and isinstance(payload.get("Node Type"), str):
        return payload
    return None


def _walk_json_plan(
    node: dict[str, Any],
    ancestors: tuple[dict[str, Any], ...] = (),
):
    yield node, ancestors
    children = node.get("Plans")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                yield from _walk_json_plan(child, ancestors + (node,))


_FILTER_TOKEN_STOPWORDS = {
    "and",
    "or",
    "not",
    "null",
    "true",
    "false",
    "is",
    "in",
    "like",
    "operator",
    "pg_catalog",
    "now",
    "interval",
    "text",
    "int",
    "integer",
    "bigint",
    "double",
    "precision",
    "numeric",
    "timestamp",
    "date",
    "time",
    "public",
}


def _sql_clause(sql: Any, keyword: str) -> str:
    text = str(sql or "")
    match = re.search(rf"\b{re.escape(keyword)}\b", text, flags=re.IGNORECASE)
    if match is None:
        return ""
    remainder = text[match.end() :]
    end_match = re.search(
        r"\b(group\s+by|order\s+by|limit|offset|fetch|having|union|returning)\b",
        remainder,
        flags=re.IGNORECASE,
    )
    if end_match is not None:
        remainder = remainder[: end_match.start()]
    return remainder.lower()


def _filter_column_tokens(filter_text: Any) -> set[str]:
    text = str(filter_text or "").lower()
    if not text:
        return set()
    dotted = {
        match.group(1) for match in re.finditer(r"\b[a-z_][a-z0-9_]*\.([a-z_][a-z0-9_]*)", text)
    }
    tokens = set(dotted)
    for token in re.findall(r"\b[a-z_][a-z0-9_]*\b", text):
        if token in _FILTER_TOKEN_STOPWORDS:
            continue
        if token.startswith("events") or token.startswith("fdw_"):
            continue
        tokens.add(token)
    return tokens


def _json_plan_pushdown_aggregates(
    plan_nodes: list[dict[str, str]],
    *,
    index_dir: Path | None = None,
) -> dict[str, Any]:
    main_files: list[tuple[str, dict[str, str]]] = []
    seen_files: set[str] = set()
    for row in plan_nodes:
        if row.get("plan_scope") != "main":
            continue
        file_name = str(row.get("plan_json_file") or "")
        if file_name and file_name not in seen_files:
            main_files.append((file_name, row))
            seen_files.add(file_name)

    result: dict[str, Any] = {}
    foreign_scan_count = 0
    filter_present_count = 0
    filter_pushdown_match_count = 0
    local_filter_after_remote_count = 0
    remote_sql_count = 0
    remote_sql_where_count = 0
    remote_sql_group_by_count = 0
    remote_sql_order_by_count = 0
    remote_sql_limit_count = 0
    aggregate_above_foreign_count = 0
    sort_above_foreign_count = 0
    limit_above_foreign_count = 0
    async_remote_scan_count = 0

    for file_name, file_row in main_files:
        root = _load_plan_json_root(_resolve_artifact_path(index_dir, file_name, row=file_row))
        if root is None:
            continue
        for node, ancestors in _walk_json_plan(root):
            if str(node.get("Node Type") or "") != "Foreign Scan":
                continue
            foreign_scan_count += 1
            if bool(node.get("Async Capable")):
                async_remote_scan_count += 1
            ancestor_types = [str(parent.get("Node Type") or "") for parent in ancestors]
            if any(_is_aggregate(node_type) for node_type in ancestor_types):
                aggregate_above_foreign_count += 1
            if any(_is_sort(node_type) for node_type in ancestor_types):
                sort_above_foreign_count += 1
            if any(node_type == "Limit" for node_type in ancestor_types):
                limit_above_foreign_count += 1

            remote_sql = str(node.get("Remote SQL") or "")
            if remote_sql:
                remote_sql_count += 1
                lower_remote_sql = remote_sql.lower()
                if re.search(r"\bwhere\b", lower_remote_sql):
                    remote_sql_where_count += 1
                if re.search(r"\bgroup\s+by\b", lower_remote_sql):
                    remote_sql_group_by_count += 1
                if re.search(r"\border\s+by\b", lower_remote_sql):
                    remote_sql_order_by_count += 1
                if re.search(r"\blimit\b", lower_remote_sql):
                    remote_sql_limit_count += 1

            filter_text = str(node.get("Filter") or "")
            if not filter_text:
                continue
            filter_present_count += 1
            filter_tokens = _filter_column_tokens(filter_text)
            where_clause = _sql_clause(remote_sql, "where")
            if filter_tokens and where_clause:
                missing_tokens = {token for token in filter_tokens if token not in where_clause}
            else:
                missing_tokens = filter_tokens
            if missing_tokens:
                local_filter_after_remote_count += 1
            else:
                filter_pushdown_match_count += 1

    if not foreign_scan_count:
        return result

    remote_aggregate_count = sum(
        1
        for row in plan_nodes
        if row.get("plan_scope") in REMOTE_SCOPES and _is_aggregate(str(row.get("node_type") or ""))
    )
    result.update(
        {
            "fdw_foreign_scan_count": foreign_scan_count,
            "foreign_scan_filter_present_count": filter_present_count,
            "foreign_scan_filter_pushdown_match_count": filter_pushdown_match_count,
            "fdw_local_filter_after_remote_count": local_filter_after_remote_count,
            "fdw_local_filter_after_remote_flag": _bool_number(local_filter_after_remote_count > 0),
            "remote_sql_where_present_count": remote_sql_where_count,
            "remote_sql_group_by_present_count": remote_sql_group_by_count,
            "remote_sql_order_by_present_count": remote_sql_order_by_count,
            "remote_sql_limit_present_count": remote_sql_limit_count,
            "remote_sql_pushdown_filter_ratio": _blank_if_none(
                _safe_divide(filter_pushdown_match_count, filter_present_count)
            ),
            "aggregate_above_foreign_scan_count": aggregate_above_foreign_count,
            "sort_above_foreign_scan_count": sort_above_foreign_count,
            "limit_above_foreign_scan_count": limit_above_foreign_count,
            "aggregate_pushdown_missed_flag": _bool_number(
                aggregate_above_foreign_count > 0
                and remote_aggregate_count == 0
                and remote_sql_group_by_count == 0
            ),
            "sort_pushdown_missed_flag": _bool_number(
                sort_above_foreign_count > 0 and remote_sql_order_by_count == 0
            ),
            "limit_pushdown_missed_flag": _bool_number(
                limit_above_foreign_count > 0 and remote_sql_limit_count == 0
            ),
            "async_remote_scan_present": _bool_number(async_remote_scan_count > 0),
            "async_remote_scan_count": async_remote_scan_count,
            "serial_remote_region_scan_count": (
                foreign_scan_count if async_remote_scan_count == 0 and remote_sql_count > 1 else 0
            ),
        }
    )
    if remote_sql_count and "fdw_remote_sql_count" not in result:
        result["fdw_remote_sql_count_from_plan"] = remote_sql_count
    return result


def _node_class_error(nodes: list[dict[str, str]], class_name: str) -> float | None:
    def matches(row: dict[str, str]) -> bool:
        node_type = str(row.get("node_type", ""))
        if class_name == "foreign_scan":
            return node_type == "Foreign Scan"
        if class_name == "aggregate":
            return _is_aggregate(node_type)
        if class_name == "join":
            return _is_join(node_type)
        if class_name == "sort":
            return _is_sort(node_type)
        return False

    values = [
        value
        for value in (_rows_estimate_error_log(row) for row in nodes if matches(row))
        if value is not None
    ]
    return _largest_abs_signed(values)


def _plan_node_aggregates(
    plan_nodes: list[dict[str, str]],
    *,
    index_dir: Path | None = None,
) -> dict[str, Any]:
    main_nodes = [row for row in plan_nodes if row.get("plan_scope") == "main"]
    remote_nodes = [row for row in plan_nodes if row.get("plan_scope") in REMOTE_SCOPES]
    task_nodes = [row for row in plan_nodes if row.get("plan_scope") == "citus_task_remote"]
    main_root = _root_node(main_nodes)
    remote_roots = [row for row in remote_nodes if str(row.get("depth", "")) in {"", "0"}]
    if not remote_roots:
        remote_roots = [
            row for row in remote_nodes if str(row.get("parent_node_id", "")) in {"", "0", "None"}
        ]

    result: dict[str, Any] = {}
    main_type_counts = Counter(_node_type_slug(row.get("node_type")) for row in main_nodes)
    for node_type, count in sorted(main_type_counts.items()):
        result[f"main_node_type_count_{node_type}"] = count

    if main_root is not None:
        result.update(
            {
                "main_root_actual_total_time_ms": _blank_if_none(
                    _float_or_none(main_root.get("actual_total_time"))
                ),
                "main_root_actual_rows": _blank_if_none(_actual_rows(main_root)),
                "main_root_plan_rows": _blank_if_none(_float_or_none(main_root.get("plan_rows"))),
                "main_total_cost": _blank_if_none(_float_or_none(main_root.get("total_cost"))),
                "final_rows": _blank_if_none(_actual_rows(main_root)),
                "root_rows_estimate_error_log": _rows_estimate_error_log(main_root)
                if _rows_estimate_error_log(main_root) is not None
                else "",
            }
        )

    node_types = [str(row.get("node_type", "")) for row in main_nodes]
    result.update(
        {
            "has_custom_scan": _bool_number(
                any(node_type == "Custom Scan" for node_type in node_types)
            ),
            "has_join": _bool_number(any(_is_join(node_type) for node_type in node_types)),
            "has_sort": _bool_number(any(_is_sort(node_type) for node_type in node_types)),
            "has_hash": _bool_number(any(_is_hash(node_type) for node_type in node_types)),
            "has_aggregate": _bool_number(
                any(_is_aggregate(node_type) for node_type in node_types)
            ),
            "has_limit": _bool_number(any(node_type == "Limit" for node_type in node_types)),
            "has_materialize": _bool_number(
                any(node_type == "Materialize" for node_type in node_types)
            ),
            "join_node_count": sum(1 for node_type in node_types if _is_join(node_type)),
            "hash_join_count": sum(1 for node_type in node_types if "Hash Join" in node_type),
            "merge_join_count": sum(1 for node_type in node_types if "Merge Join" in node_type),
            "nested_loop_count": sum(1 for node_type in node_types if node_type == "Nested Loop"),
        }
    )

    foreign_scan_nodes = [row for row in main_nodes if row.get("node_type") == "Foreign Scan"]
    foreign_scan_time = sum(
        value for value in (_actual_time(row) for row in foreign_scan_nodes) if value is not None
    )
    root_time = _actual_time(main_root) if main_root is not None else None
    if root_time and root_time > 0:
        foreign_scan_time_ratio = foreign_scan_time / root_time
        result["remote_path_share"] = foreign_scan_time_ratio
        result["foreign_scan_time_to_root_ratio"] = foreign_scan_time_ratio
        result["finalize_share"] = max(0.0, (root_time - foreign_scan_time) / root_time)

    foreign_rows = [
        value for value in (_actual_rows(row) for row in foreign_scan_nodes) if value is not None
    ]
    remote_root_rows = [
        value for value in (_actual_rows(row) for row in remote_roots) if value is not None
    ]
    root_rows = _actual_rows(main_root) if main_root is not None else None
    fanin_rows = sum(foreign_rows) if foreign_rows else None
    remote_rows = sum(remote_root_rows) if remote_root_rows else None
    if fanin_rows is not None:
        result["global_fanin_rows"] = fanin_rows
    if root_rows is not None:
        if fanin_rows is not None:
            result["global_fanin_ratio"] = fanin_rows / max(root_rows, 1.0)
        if remote_rows is not None:
            result["remote_to_final_rows_ratio"] = remote_rows / max(root_rows, 1.0)

    root_width = _float_or_none(main_root.get("plan_width")) if main_root is not None else None
    foreign_widths = [
        value
        for value in (_float_or_none(row.get("plan_width")) for row in foreign_scan_nodes)
        if value is not None
    ]
    remote_widths = [
        value
        for value in (_float_or_none(row.get("plan_width")) for row in remote_roots)
        if value is not None
    ]
    fanin_bytes = [
        value
        for value in (
            _estimate_bytes(_actual_rows(row), _float_or_none(row.get("plan_width")))
            for row in foreign_scan_nodes
        )
        if value is not None
    ]
    result_bytes = _estimate_bytes(root_rows, root_width)
    remote_output_bytes = [
        value
        for value in (
            _estimate_bytes(_actual_rows(row), _float_or_none(row.get("plan_width")))
            for row in remote_roots
        )
        if value is not None
    ]
    if root_width is not None:
        result["main_root_plan_width"] = root_width
        if root_width <= 64:
            result["result_width_class"] = "narrow"
        elif root_width <= 512:
            result["result_width_class"] = "medium"
        else:
            result["result_width_class"] = "wide"
    if foreign_widths:
        result["foreign_scan_plan_width_sum"] = sum(foreign_widths)
        result["foreign_scan_plan_width_max"] = max(foreign_widths)
    if remote_widths:
        result["remote_root_plan_width_sum"] = sum(remote_widths)
        result["remote_root_plan_width_max"] = max(remote_widths)
    if foreign_widths and remote_widths:
        result["projection_width_expansion_ratio"] = _blank_if_none(
            _safe_divide(sum(foreign_widths), sum(remote_widths))
        )
    if result_bytes is not None:
        result["estimated_result_bytes"] = result_bytes
    if remote_output_bytes:
        result["estimated_remote_output_bytes"] = sum(remote_output_bytes)
    if fanin_bytes:
        result["estimated_fanin_bytes"] = sum(fanin_bytes)
    if fanin_bytes and result_bytes is not None:
        result["legacy_fanin_to_result_bytes_proxy"] = sum(fanin_bytes) / max(result_bytes, 1.0)

    estimate_errors = [
        value
        for value in (_rows_estimate_error_log(row) for row in main_nodes)
        if value is not None
    ]
    if estimate_errors:
        result["rows_estimate_error_max_abs_log"] = max(abs(value) for value in estimate_errors)
        result["rows_estimate_error_mean_abs_log"] = sum(
            abs(value) for value in estimate_errors
        ) / len(estimate_errors)
    for class_name in ("foreign_scan", "aggregate", "join", "sort"):
        key = f"{class_name}_rows_estimate_error_log"
        if key not in result or _is_blank(result.get(key)):
            value = _node_class_error(main_nodes, class_name)
            if value is not None:
                result[key] = value
    remote_root_errors = [
        value
        for value in (_rows_estimate_error_log(row) for row in remote_roots)
        if value is not None
    ]
    remote_root_error = _largest_abs_signed(remote_root_errors)
    if remote_root_error is not None:
        result["remote_root_rows_estimate_error_log"] = remote_root_error

    result.update(
        {
            "remote_plan_node_count_sum": len(remote_nodes) if remote_nodes else "",
            "remote_plan_max_depth": _max_numeric(remote_nodes, "depth"),
            "remote_has_custom_scan": _bool_number(
                any(row.get("node_type") == "Custom Scan" for row in remote_nodes)
            )
            if remote_nodes
            else "",
            "remote_has_sort": _bool_number(
                any(_is_sort(str(row.get("node_type", ""))) for row in remote_nodes)
            )
            if remote_nodes
            else "",
            "remote_has_hash_join": _bool_number(
                any("Hash Join" in str(row.get("node_type", "")) for row in remote_nodes)
            )
            if remote_nodes
            else "",
            "remote_actual_rows_sum": _sum_numeric(remote_nodes, "actual_rows"),
        }
    )

    main_temp_read = _sum_numeric(main_nodes, "temp_read_blocks")
    main_temp_written = _sum_numeric(main_nodes, "temp_written_blocks")
    remote_temp_read = _sum_numeric(remote_nodes, "temp_read_blocks")
    remote_temp_written = _sum_numeric(remote_nodes, "temp_written_blocks")
    temp_read = _sum_numeric(main_nodes + remote_nodes, "temp_read_blocks")
    temp_written = _sum_numeric(main_nodes + remote_nodes, "temp_written_blocks")
    main_spill_blocks = (main_temp_read if main_temp_read != "" else 0.0) + (
        main_temp_written if main_temp_written != "" else 0.0
    )
    remote_spill_blocks = (remote_temp_read if remote_temp_read != "" else 0.0) + (
        remote_temp_written if remote_temp_written != "" else 0.0
    )
    temp_sum = (temp_read if temp_read != "" else 0.0) + (
        temp_written if temp_written != "" else 0.0
    )
    external_sort_count = sum(
        1
        for row in main_nodes + remote_nodes
        if str(row.get("sort_space_type", "")).lower() == "disk"
        or "external" in str(row.get("sort_method", "")).lower()
    )
    hash_batches = [
        value
        for value in (_float_or_none(row.get("hash_batches")) for row in main_nodes + remote_nodes)
        if value is not None
    ]
    hash_batches_max = max(hash_batches) if hash_batches else 1.0
    spill_flag = temp_sum > 0 or external_sort_count > 0 or hash_batches_max > 1
    result.update(
        {
            "main_spill_blocks_sum": (
                main_spill_blocks if main_temp_read != "" or main_temp_written != "" else ""
            ),
            "remote_spill_blocks_sum": (
                remote_spill_blocks if remote_temp_read != "" or remote_temp_written != "" else ""
            ),
            "temp_blocks_sum": temp_sum if temp_read != "" or temp_written != "" else "",
            "spill_flag": _bool_number(spill_flag),
            "external_sort_count": external_sort_count,
            "sort_space_used_max": _max_numeric(main_nodes + remote_nodes, "sort_space_used"),
            "hash_batches_max": hash_batches_max,
            "peak_memory_usage_max": _max_numeric(main_nodes + remote_nodes, "peak_memory_usage"),
            "memory_pressure_score_v1": (
                math.log1p(temp_sum)
                + external_sort_count
                + math.log1p(max(hash_batches_max - 1, 0))
            ),
        }
    )

    if task_nodes:
        task_indexes = {
            str(row.get("citus_task_index", ""))
            for row in task_nodes
            if row.get("citus_task_index", "")
        }
        result.setdefault("task_count", len(task_indexes) if task_indexes else "")

    result.update(_json_plan_pushdown_aggregates(plan_nodes, index_dir=index_dir))
    return result


def _add_flow_proxy_features(row: dict[str, Any]) -> None:
    """Derive compact flow features after plan, region and worker aggregates merge."""
    wan_rows = _first_number(
        row,
        [
            "remote_region_actual_rows_sum",
            "remote_actual_rows_sum",
            "global_fanin_rows",
        ],
    )
    wan_bytes = _first_number(
        row,
        [
            "remote_region_tuple_bytes_sum",
            "estimated_remote_output_bytes",
            "estimated_fanin_bytes",
        ],
    )
    final_rows = _first_number(row, ["final_rows", "main_root_actual_rows"])
    final_bytes = _first_number(row, ["estimated_result_bytes"])
    foreign_scan_rows = _first_number(row, ["global_fanin_rows"])
    regional_rows = _first_number(
        row,
        [
            "worker_task_scan_actual_rows_sum",
            "worker_task_actual_rows_sum",
            "remote_region_actual_rows_sum",
            "remote_actual_rows_sum",
        ],
    )

    row_width_proxy = _safe_divide(wan_bytes, wan_rows)
    regional_bytes = None
    if regional_rows is not None and row_width_proxy is not None:
        regional_bytes = regional_rows * row_width_proxy

    _set_number(row, "wan_output_rows", wan_rows)
    _set_number(row, "wan_output_bytes_proxy", wan_bytes)
    _set_number(row, "regional_reduction_input_rows_proxy", regional_rows)
    _set_number(row, "regional_reduction_input_bytes_proxy", regional_bytes)
    _set_number(
        row,
        "remote_to_foreign_scan_rows_ratio",
        _safe_divide_floor(wan_rows, foreign_scan_rows),
    )
    _set_number(
        row,
        "foreign_scan_to_final_rows_ratio",
        _safe_divide_floor(foreign_scan_rows, final_rows),
    )
    _set_number(
        row,
        "post_fdw_filter_reduction_ratio",
        _safe_divide_floor(wan_rows, foreign_scan_rows),
    )

    drf_rows = _safe_divide(regional_rows, wan_rows)
    drf_bytes = _safe_divide(regional_bytes, wan_bytes)
    _set_number(row, "drf_rows_proxy", drf_rows)
    _set_number(row, "drf_bytes_proxy", drf_bytes)
    _set_number(row, "regional_input_to_wan_rows_ratio", drf_rows)
    _set_number(row, "log_drf_rows_proxy", _safe_log_ratio(drf_rows))
    _set_number(row, "log_drf_bytes_proxy", _safe_log_ratio(drf_bytes))
    _set_number(
        row,
        "wan_output_to_final_rows_ratio",
        _safe_divide_floor(wan_rows, final_rows),
    )
    _set_number(
        row,
        "wan_output_to_client_rows_ratio",
        _safe_divide_floor(wan_rows, final_rows),
    )
    _set_number(row, "wan_output_to_final_bytes_ratio", _safe_divide(wan_bytes, final_bytes))

    global_group_count = final_rows
    _set_number(row, "global_group_count_proxy", global_group_count)
    _set_number(row, "global_group_density", _safe_divide(global_group_count, wan_rows))
    _set_number(
        row,
        "global_group_merge_ratio",
        _safe_divide_floor(wan_rows, global_group_count),
    )

    _set_number(
        row,
        "remote_region_rows_isf",
        _isf_from_max_share(
            row,
            "remote_region_actual_rows_max_share",
            "remote_region_nonzero_count",
        ),
    )
    remote_region_isf_observed = _first_number(
        row,
        [
            "remote_region_actual_rows_imbalance_ratio",
            "remote_region_rows_isf",
        ],
    )
    remote_region_unit_count = _first_number(
        row,
        [
            "remote_region_rows_available_count",
            "remote_region_observed_count",
        ],
    )
    _set_number(
        row,
        "remote_region_rows_isf_observed",
        remote_region_isf_observed,
    )
    _set_number(
        row,
        "remote_region_rows_isf_normalized",
        _normalized_isf(remote_region_isf_observed, remote_region_unit_count),
    )
    _set_number(
        row,
        "remote_region_bytes_isf",
        _isf_from_max_share(
            row,
            "remote_region_tuple_bytes_max_share",
            "remote_region_nonzero_count",
        ),
    )

    task_count = _first_number(row, ["worker_task_plan_count", "task_count"])
    if task_count is not None:
        _set_number(
            row,
            "worker_task_scan_rows_isf",
            _isf_from_max_share(
                row,
                "worker_task_scan_actual_rows_max_share",
                "worker_task_plan_count",
            )
            or _isf_from_max_share(row, "worker_task_scan_actual_rows_max_share", "task_count"),
        )
        _set_number(
            row,
            "worker_task_root_rows_isf",
            _isf_from_max_share(row, "worker_task_actual_rows_max_share", "worker_task_plan_count")
            or _isf_from_max_share(row, "worker_task_actual_rows_max_share", "task_count"),
        )
        _set_number(
            row,
            "worker_task_scan_rows_isf_normalized",
            _normalized_isf(
                row.get("worker_task_scan_rows_isf"),
                row.get("worker_task_plan_count") or row.get("task_count"),
            ),
        )

    region_count = _float_or_none(row.get("worker_task_region_count")) or _float_or_none(
        row.get("remote_region_nonzero_count")
    )
    within_region_max_share = _float_or_none(
        row.get("worker_task_within_region_scan_rows_max_share_max")
    )
    if task_count is not None and region_count is not None and region_count > 0:
        _set_number(
            row,
            "worker_task_within_region_scan_rows_isf_max",
            (within_region_max_share * (task_count / region_count))
            if within_region_max_share is not None
            else None,
        )

    row["fdw_pushdown_fidelity_contract"] = FDW_PUSHDOWN_FIDELITY_CONTRACT
    fidelity_components: list[float] = []
    miss_reason_codes: list[str] = []
    filter_count = _float_or_none(row.get("foreign_scan_filter_present_count"))
    filter_ratio = _float_or_none(row.get("remote_sql_pushdown_filter_ratio"))
    if filter_count is not None and filter_count > 0 and filter_ratio is not None:
        fidelity_components.append(max(0.0, min(1.0, filter_ratio)))
        if _truthy(row.get("fdw_local_filter_after_remote_flag")):
            miss_reason_codes.append("local_filter_after_remote")
    if _float_or_none(row.get("aggregate_above_foreign_scan_count")):
        fidelity_components.append(
            0.0 if _truthy(row.get("aggregate_pushdown_missed_flag")) else 1.0
        )
        if _truthy(row.get("aggregate_pushdown_missed_flag")):
            miss_reason_codes.append("aggregate_not_pushdowned")
    if _float_or_none(row.get("sort_above_foreign_scan_count")):
        fidelity_components.append(0.0 if _truthy(row.get("sort_pushdown_missed_flag")) else 1.0)
        if _truthy(row.get("sort_pushdown_missed_flag")):
            miss_reason_codes.append("sort_not_pushdowned")
    if _float_or_none(row.get("limit_above_foreign_scan_count")):
        fidelity_components.append(0.0 if _truthy(row.get("limit_pushdown_missed_flag")) else 1.0)
        if _truthy(row.get("limit_pushdown_missed_flag")):
            miss_reason_codes.append("limit_not_pushdowned")
    width_expansion = _float_or_none(row.get("projection_width_expansion_ratio"))
    if width_expansion is not None and width_expansion > 0:
        fidelity_components.append(min(1.0, 1.0 / width_expansion))
        if width_expansion > 1.0:
            miss_reason_codes.append("projection_width_expansion")

    _set_number(row, "pushdown_fidelity_component_count", len(fidelity_components))
    row["pushdown_miss_reason_codes"] = ",".join(dict.fromkeys(miss_reason_codes))
    if fidelity_components:
        score = statistics.fmean(fidelity_components)
        _set_number(row, "pushdown_fidelity_score", score)
        _set_number(row, "pushdown_miss_score", 1.0 - score)
        row["pushdown_fidelity_evidence_status"] = "available"
    elif _float_or_none(row.get("fdw_foreign_scan_count")):
        row["pushdown_fidelity_evidence_status"] = "no_scored_components"
    else:
        row["pushdown_fidelity_evidence_status"] = "not_applicable_no_fdw"


def _add_topology_normalized_features(row: dict[str, Any]) -> None:
    """Derive ratio-first topology and spill features for clustering inputs."""
    configured_shard_count = _dataset_shard_count(row)
    configured_region_count, worker_count_per_region, total_worker_count = _topology_defaults(row)

    _set_number(row, "configured_shard_count", configured_shard_count)
    _set_number(row, "configured_region_count", configured_region_count)
    _set_number(row, "configured_worker_count_per_region", worker_count_per_region)
    _set_number(row, "configured_worker_count_total", total_worker_count)

    legacy_repartition = _truthy(row.get("citus_repartition_query"))
    remote_repartition_count = _float_or_none(row.get("remote_citus_repartition_mapmerge_count"))
    remote_locality_classes = {
        item.strip()
        for item in str(row.get("remote_citus_plan_locality_classes", "")).split(",")
        if item.strip()
    }
    row["citus_repartition_observed_v2"] = int(
        legacy_repartition
        or bool(remote_repartition_count and remote_repartition_count > 0)
        or "repartition_mapmerge" in remote_locality_classes
    )

    observed_region_count = _first_number(
        row,
        ["remote_region_nonzero_count", "remote_region_observed_count", "remote_region_count"],
    )
    if observed_region_count is None or observed_region_count <= 0:
        observed_region_count = 1.0
    _set_number(row, "observed_region_count_for_task_scope", observed_region_count)

    task_count = _first_number(
        row,
        ["worker_task_plan_count", "task_count", "remote_region_task_count_sum"],
    )
    if task_count is not None:
        _set_number(
            row,
            "task_count_to_shard_count_ratio",
            _safe_divide(task_count, configured_shard_count),
        )
        configured_region_shard_slots = (
            configured_shard_count * configured_region_count
            if configured_shard_count is not None
            and configured_region_count is not None
            and configured_region_count > 0
            else None
        )
        observed_region_shard_slots = (
            configured_shard_count * observed_region_count
            if configured_shard_count is not None and observed_region_count > 0
            else None
        )
        _set_number(row, "configured_region_shard_slots", configured_region_shard_slots)
        _set_number(row, "observed_region_shard_slots", observed_region_shard_slots)
        _set_number(
            row,
            "task_count_to_configured_region_shard_slots_ratio",
            _safe_divide(task_count, configured_region_shard_slots),
        )
        active_task_share = _safe_divide(task_count, observed_region_shard_slots)
        _set_number(row, "task_count_to_observed_region_shard_slots_ratio", active_task_share)
        _set_number(row, "active_task_share", active_task_share)
        _set_number(row, "tasks_per_worker_ratio", _safe_divide(task_count, total_worker_count))

    temp_blocks = _float_or_none(row.get("temp_blocks_sum"))
    temp_bytes = temp_blocks * 8192.0 if temp_blocks is not None else None
    wan_rows = _float_or_none(row.get("wan_output_rows"))
    wan_bytes = _float_or_none(row.get("wan_output_bytes_proxy"))
    final_rows = _first_number(
        row,
        ["global_group_count_proxy", "final_rows", "main_root_actual_rows"],
    )
    regional_input_rows = _float_or_none(row.get("regional_reduction_input_rows_proxy"))

    spill_bytes_to_wan_bytes = _safe_divide(temp_bytes, wan_bytes)
    _set_number(row, "temp_bytes_to_wan_bytes_ratio", spill_bytes_to_wan_bytes)
    _set_number(row, "spill_bytes_to_wan_bytes_ratio", spill_bytes_to_wan_bytes)
    _set_number(row, "temp_blocks_per_wan_row", _safe_divide(temp_blocks, wan_rows))
    _set_number(
        row,
        "temp_blocks_per_final_row",
        _safe_divide_floor(temp_blocks, final_rows),
    )
    _set_number(
        row,
        "temp_blocks_per_regional_input_row",
        _safe_divide(temp_blocks, regional_input_rows),
    )
    wan_mb = wan_bytes / (1024.0 * 1024.0) if wan_bytes is not None else None
    _set_number(row, "spill_per_wan_mb", _safe_divide(temp_blocks, wan_mb))
    spill_present = _truthy(row.get("spill_flag"))
    row["spill_present"] = int(spill_present)
    hash_batches = _float_or_none(row.get("hash_batches_max"))
    _set_number(
        row,
        "hash_batch_excess",
        max((hash_batches or 1.0) - 1.0, 0.0),
    )


def _remote_plan_aggregates(rows: list[dict[str, str]]) -> dict[str, Any]:
    ok_rows = [row for row in rows if str(row.get("status", "")).lower() in {"", "ok"}]
    regions = {str(row.get("fdw_region", "")) for row in ok_rows if row.get("fdw_region", "")}
    return {
        "fdw_remote_plan_count": len(ok_rows) if rows else "",
        "regions_touched": len(regions) if regions else "",
    }


def _cv_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    if mean == 0.0:
        return 0.0 if std == 0.0 else None
    return std / mean


def _split_region_list(value: Any) -> list[str]:
    if value in ("", None):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in text.split(",") if item.strip()]


def _expected_remote_regions(row: dict[str, Any]) -> list[str]:
    for field in (
        "fdw_auto_explain_regions",
        "expected_remote_regions",
        "remote_expected_regions",
    ):
        regions = _split_region_list(row.get(field))
        if regions:
            return regions
    return []


def _remote_region_aggregates(
    rows: list[dict[str, str]],
    *,
    expected_regions: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not rows and not expected_regions:
        return result

    observed_regions = {
        str(row.get("region_id", "")) for row in rows if str(row.get("region_id", "")).strip()
    }
    expected_unique = sorted({region for region in expected_regions or [] if region})
    expected_count = len(expected_unique)
    observed_count = len(observed_regions)
    if expected_count or observed_count:
        result["remote_region_count"] = expected_count if expected_count else observed_count
    result["remote_region_observed_count"] = len(observed_regions)
    result["remote_region_missing_count"] = (
        max(expected_count - observed_count, 0) if expected_count else 0
    )
    result["remote_region_evidence_completeness"] = (
        observed_count / expected_count if expected_count else 1.0
    )
    result["remote_region_parse_success_count"] = sum(
        1 for row in rows if str(row.get("parse_status", "")).lower() == "ok"
    )
    result["remote_region_parse_partial_count"] = sum(
        1 for row in rows if str(row.get("parse_status", "")).lower() == "partial"
    )

    def populate(prefix: str, values: list[float]) -> None:
        if not values:
            return
        total = sum(values)
        mean = statistics.fmean(values)
        min_value = min(values)
        max_value = max(values)
        result[f"{prefix}_sum"] = total
        result[f"{prefix}_min"] = min_value
        result[f"{prefix}_max"] = max_value
        result[f"{prefix}_mean"] = mean
        result[f"{prefix}_cv"] = _cv_or_none(values)
        result[f"{prefix}_max_share"] = max_value / total if total > 0 else ""
        result[f"{prefix}_imbalance_ratio"] = max_value / mean if mean > 0 else ""
        result[f"{prefix}_min_max_ratio"] = min_value / max_value if max_value > 0 else ""
        result[f"{prefix}_active_share"] = sum(1 for value in values if value > 0.0) / len(values)

    rows_by_region: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        region_id = str(row.get("region_id", ""))
        if region_id:
            rows_by_region[region_id].append(row)

    def region_sums(column: str) -> list[float]:
        values: list[float] = []
        for region_rows in rows_by_region.values():
            region_values = [
                value
                for value in (_float_or_none(row.get(column)) for row in region_rows)
                if value is not None
            ]
            if region_values:
                values.append(sum(region_values))
        return values

    actual_rows = region_sums("remote_actual_rows")
    actual_times = region_sums("remote_actual_total_time_ms")
    tuple_bytes = region_sums("remote_tuple_bytes_proxy")
    task_counts = region_sums("remote_citus_task_count")
    result["remote_region_rows_available_count"] = len(actual_rows)
    result["remote_region_time_available_count"] = len(actual_times)
    result["remote_region_task_count_available_count"] = len(task_counts)
    result["remote_region_zero_row_count"] = sum(1 for value in actual_rows if value == 0.0)
    result["remote_region_nonzero_count"] = sum(1 for value in actual_rows if value > 0.0)
    populate("remote_region_actual_rows", actual_rows)
    populate("remote_region_actual_time", actual_times)
    populate("remote_region_tuple_bytes", tuple_bytes)
    populate("remote_region_task_count", task_counts)

    def truthy_count(column: str) -> int:
        return sum(1 for row in rows if str(row.get(column, "")).lower() == "true")

    def false_count(column: str) -> int:
        return sum(1 for row in rows if str(row.get(column, "")).lower() == "false")

    result["remote_citus_tasks_shown_none_count"] = truthy_count("remote_citus_tasks_shown_none")
    result["remote_citus_task_list_available_count"] = truthy_count(
        "remote_citus_task_list_available"
    )
    result["remote_citus_tuple_bytes_unsupported_count"] = false_count(
        "remote_citus_tuple_bytes_supported"
    )
    for output, column, reducer in (
        (
            "remote_citus_map_merge_job_count_sum",
            "remote_citus_map_merge_job_count",
            sum,
        ),
        (
            "remote_citus_dependent_map_task_count_sum",
            "remote_citus_dependent_map_task_count_sum",
            sum,
        ),
        (
            "remote_citus_dependent_merge_task_count_sum",
            "remote_citus_dependent_merge_task_count_sum",
            sum,
        ),
        (
            "remote_citus_repartition_fanout_ratio_max",
            "remote_citus_repartition_fanout_ratio",
            max,
        ),
    ):
        values = [
            value
            for value in (_float_or_none(row.get(column)) for row in rows)
            if value is not None
        ]
        if values:
            result[output] = reducer(values)
    result["remote_citus_router_single_task_count"] = truthy_count(
        "remote_citus_router_single_task"
    )
    result["remote_citus_reference_join_candidate_count"] = truthy_count(
        "remote_citus_reference_join_candidate"
    )
    result["remote_citus_colocated_join_candidate_count"] = truthy_count(
        "remote_citus_colocated_join_candidate"
    )
    result["remote_citus_repartition_mapmerge_count"] = truthy_count(
        "remote_citus_repartition_mapmerge"
    )
    locality_classes = [
        str(row.get("remote_citus_plan_locality_class", ""))
        for row in rows
        if str(row.get("remote_citus_plan_locality_class", "")).strip()
    ]
    if locality_classes:
        counts = Counter(locality_classes)
        result["remote_citus_plan_locality_classes"] = ",".join(sorted(counts))
        result["remote_citus_dominant_plan_locality_class"] = counts.most_common(1)[0][0]

    region_plan_signatures: list[str] = []
    for region_rows in rows_by_region.values():
        fingerprints = sorted(
            {
                str(row.get("remote_plan_fingerprint", ""))
                for row in region_rows
                if str(row.get("remote_plan_fingerprint", "")).strip()
            }
        )
        if fingerprints:
            region_plan_signatures.append("|".join(fingerprints))
    if region_plan_signatures:
        counts = Counter(region_plan_signatures)
        result["remote_region_plan_fingerprint_count"] = len(counts)
        result["remote_region_plan_fingerprint_all_same"] = _bool_number(len(counts) == 1)
        result["remote_region_dominant_plan_fingerprint_share"] = max(counts.values()) / len(
            region_plan_signatures
        )
    return result


def _json_counter_from_rows(rows: list[dict[str, str]], column: str) -> Counter[str]:
    result: Counter[str] = Counter()
    for row in rows:
        try:
            value = json.loads(str(row.get(column) or "{}"))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            for key, count in value.items():
                numeric = _float_or_none(count)
                if numeric is not None:
                    result[str(key)] += numeric
    return result


def _worker_scan_class(node_type: str) -> str:
    if node_type in {"Seq Scan", "Parallel Seq Scan"}:
        return "seq_scan"
    if node_type in {"Index Scan", "Index Only Scan"}:
        return "index_scan"
    if node_type in {"Bitmap Heap Scan", "Bitmap Index Scan", "BitmapAnd", "BitmapOr"}:
        return "bitmap_scan"
    if "Scan" in node_type:
        return "other_scan"
    return ""


def _worker_is_join(node_type: str) -> bool:
    return "Join" in node_type or node_type == "Nested Loop"


def _worker_is_aggregate(node_type: str) -> bool:
    return "Aggregate" in node_type


def _worker_is_sort(node_type: str) -> bool:
    return "Sort" in node_type


def _worker_is_blocking(node_type: str) -> bool:
    return (
        _worker_is_aggregate(node_type)
        or _worker_is_sort(node_type)
        or node_type in {"Materialize", "Hash", "Unique", "WindowAgg"}
    )


def _worker_is_materialization(node_type: str) -> bool:
    return node_type in {"Materialize", "Memoize"}


def _worker_is_parallel(node_type: str) -> bool:
    return "Parallel" in node_type or node_type in {"Gather", "Gather Merge"}


def _worker_is_bitmap(node_type: str) -> bool:
    return node_type in {"Bitmap Heap Scan", "Bitmap Index Scan", "BitmapAnd", "BitmapOr"}


def _worker_is_index_access(node_type: str) -> bool:
    return node_type in {"Index Scan", "Index Only Scan", "Bitmap Index Scan"}


def _worker_is_sequential_access(node_type: str) -> bool:
    return node_type in {"Seq Scan", "Parallel Seq Scan"}


def _worker_is_spill_capable(node_type: str) -> bool:
    return _worker_is_blocking(node_type) or node_type in {"Hash Join", "Merge Join"}


def _count_worker_node_types(
    node_type_counts: Counter[str],
    predicate: Any,
) -> float:
    return float(
        sum(count for node_type, count in node_type_counts.items() if predicate(node_type))
    )


def _worker_task_aggregates(rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        return {}

    result: dict[str, Any] = {"worker_task_plan_count": len(rows)}

    def numeric(column: str) -> list[float]:
        return [
            value
            for value in (_float_or_none(row.get(column)) for row in rows)
            if value is not None
        ]

    def populate_distribution(prefix: str, values: list[float]) -> None:
        if not values:
            return
        total = sum(values)
        max_share = max(values) / total if total > 0 else ""
        result[f"{prefix}_sum"] = total
        result[f"{prefix}_min"] = min(values)
        result[f"{prefix}_max"] = max(values)
        result[f"{prefix}_cv"] = _cv_or_none(values)
        result[f"{prefix}_max_share"] = max_share
        if max_share != "":
            result[f"{prefix}_isf"] = max_share * len(values)

    actual_rows = numeric("worker_task_actual_rows")
    scan_actual_rows = numeric("worker_task_scan_actual_rows_sum")
    actual_times = numeric("worker_task_actual_time_ms")
    tuple_bytes = numeric("tuple_data_received_bytes")
    populate_distribution("worker_task_actual_rows", actual_rows)
    populate_distribution("worker_task_scan_actual_rows", scan_actual_rows)
    populate_distribution("worker_task_actual_time", actual_times)
    populate_distribution("worker_task_tuple_bytes", tuple_bytes)
    if scan_actual_rows:
        nonzero_scan_count = sum(value > 0 for value in scan_actual_rows)
        result["worker_task_nonzero_scan_count"] = nonzero_scan_count
        result["worker_task_nonzero_scan_share"] = (
            nonzero_scan_count / len(scan_actual_rows)
        )
        active_scan_rows = [value for value in scan_actual_rows if value > 0]
        if len(active_scan_rows) >= 2:
            active_scan_sum = sum(active_scan_rows)
            active_scan_max_share = max(active_scan_rows) / active_scan_sum
            active_scan_isf = active_scan_max_share * len(active_scan_rows)
            result["worker_task_active_scan_rows_isf"] = active_scan_isf
            result["worker_task_active_scan_rows_isf_normalized"] = (
                _blank_if_none(
                    _normalized_isf(active_scan_isf, len(active_scan_rows))
                )
            )
    time_isf = _float_or_none(result.get("worker_task_actual_time_isf"))
    if time_isf is not None:
        result["worker_task_actual_time_isf_normalized"] = _blank_if_none(
            _normalized_isf(time_isf, len(actual_times))
        )
    tuple_bytes_isf = _float_or_none(result.get("worker_task_tuple_bytes_isf"))
    if tuple_bytes_isf is not None:
        result["worker_task_tuple_bytes_isf_normalized"] = _blank_if_none(
            _normalized_isf(tuple_bytes_isf, len(tuple_bytes))
        )

    worker_scan_rows: dict[str, float] = defaultdict(float)
    worker_scan_observations: dict[str, int] = defaultdict(int)
    worker_task_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        worker = str(row.get("worker_node", "")).strip()
        if not worker:
            continue
        worker_task_counts[worker] += 1
        scan_rows = _float_or_none(row.get("worker_task_scan_actual_rows_sum"))
        if scan_rows is not None:
            worker_scan_rows[worker] += scan_rows
            worker_scan_observations[worker] += 1
    if worker_task_counts:
        task_count_values = list(worker_task_counts.values())
        task_count_total = sum(task_count_values)
        task_count_max_share = (
            max(task_count_values) / task_count_total if task_count_total > 0 else ""
        )
        task_count_isf = (
            task_count_max_share * len(task_count_values)
            if task_count_max_share != ""
            else ""
        )
        result["worker_task_worker_count"] = len(task_count_values)
        result["worker_task_count_cv"] = _cv_or_none(task_count_values)
        result["worker_task_count_max_share"] = task_count_max_share
        result["worker_task_count_isf"] = task_count_isf
        result["worker_task_count_isf_normalized"] = _blank_if_none(
            _normalized_isf(_float_or_none(task_count_isf), len(task_count_values))
        )
    if worker_task_counts and all(
        worker_scan_observations[worker] == task_count
        for worker, task_count in worker_task_counts.items()
    ):
        ordered_workers = sorted(worker_task_counts)
        worker_values = [worker_scan_rows[worker] for worker in ordered_workers]
        worker_count = len(worker_values)
        worker_total = sum(worker_values)
        worker_cv = _cv_or_none(worker_values)
        worker_max_share = max(worker_values) / worker_total if worker_total > 0 else 0.0
        worker_isf = worker_max_share * worker_count if worker_count else None
        result["worker_scan_rows_sum"] = worker_total
        result["worker_scan_rows_worker_count"] = worker_count
        result["worker_scan_rows_cv"] = _blank_if_none(worker_cv)
        result["worker_scan_rows_max_share"] = worker_max_share
        result["worker_scan_rows_isf"] = _blank_if_none(worker_isf)
        result["worker_scan_rows_cv_normalized"] = _blank_if_none(
            _normalized_population_cv(worker_cv, worker_count)
        )
        result["worker_scan_rows_isf_normalized"] = _blank_if_none(
            _normalized_isf(worker_isf, worker_count)
        )

    scan_counts = _json_counter_from_rows(rows, "worker_task_scan_type_counts_json")
    scan_total = sum(scan_counts.values())
    if scan_counts:
        result["worker_task_scan_type_counts_json"] = json.dumps(
            dict(sorted(scan_counts.items())),
            sort_keys=True,
            separators=(",", ":"),
        )
        result["worker_task_index_scan_share"] = scan_counts.get("index_scan", 0.0) / scan_total
        result["worker_task_seq_scan_share"] = scan_counts.get("seq_scan", 0.0) / scan_total
        result["worker_task_bitmap_scan_share"] = scan_counts.get("bitmap_scan", 0.0) / scan_total

    node_type_counts = _json_counter_from_rows(rows, "worker_task_node_type_counts_json")
    if node_type_counts:
        result["worker_task_node_type_counts_json"] = json.dumps(
            dict(sorted(node_type_counts.items())),
            sort_keys=True,
            separators=(",", ":"),
        )
        selected_node_count = 0.0
        for node_type, feature_name in WORKER_NODE_COUNT_FEATURES.items():
            value = float(node_type_counts.get(node_type, 0.0))
            result[feature_name] = value
            selected_node_count += value
        total_node_count = float(sum(node_type_counts.values()))
        result["worker_node_count_other"] = max(0.0, total_node_count - selected_node_count)

    unknown_sets: set[str] = set()
    for row in rows:
        try:
            value = json.loads(str(row.get("worker_task_node_type_unknown_set_json") or "[]"))
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            unknown_sets.update(str(item) for item in value)
    unknown_count = sum(numeric("worker_task_node_type_unknown_count"))
    if unknown_count:
        result["worker_task_node_type_unknown_count"] = unknown_count
    if unknown_sets:
        result["worker_task_node_type_unknown_set_json"] = json.dumps(
            sorted(unknown_sets),
            sort_keys=True,
            separators=(",", ":"),
        )

    node_counts = numeric("worker_task_node_count")
    depths = numeric("worker_task_plan_max_depth")
    if node_counts:
        result["worker_task_node_count_sum"] = sum(node_counts)
    if depths:
        result["worker_task_plan_max_depth_max"] = max(depths)
        result["worker_task_plan_max_depth_mean"] = statistics.fmean(depths)

    for output, column in (
        ("worker_task_join_node_count", "worker_task_join_node_count"),
        ("worker_task_aggregate_node_count", "worker_task_aggregate_node_count"),
        ("worker_task_sort_node_count", "worker_task_sort_node_count"),
        ("worker_task_blocking_node_count", "worker_task_blocking_node_count"),
        ("worker_task_scan_node_count", "worker_task_scan_node_count"),
        ("worker_task_materialization_node_count", "worker_task_materialization_node_count"),
        ("worker_task_parallel_node_count", "worker_task_parallel_node_count"),
        ("worker_task_bitmap_node_count", "worker_task_bitmap_node_count"),
        ("worker_task_index_access_node_count", "worker_task_index_access_node_count"),
        ("worker_task_sequential_access_node_count", "worker_task_sequential_access_node_count"),
        ("worker_task_spill_capable_node_count", "worker_task_spill_capable_node_count"),
        ("worker_task_spill_count", "worker_task_spill_count"),
    ):
        value = sum(numeric(column))
        if value or output not in result:
            result[output] = value

    if node_type_counts:
        fallback_counts = {
            "worker_task_scan_node_count": _count_worker_node_types(
                node_type_counts, _worker_scan_class
            ),
            "worker_task_join_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_join
            ),
            "worker_task_aggregate_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_aggregate
            ),
            "worker_task_sort_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_sort
            ),
            "worker_task_blocking_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_blocking
            ),
            "worker_task_materialization_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_materialization
            ),
            "worker_task_parallel_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_parallel
            ),
            "worker_task_bitmap_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_bitmap
            ),
            "worker_task_index_access_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_index_access
            ),
            "worker_task_sequential_access_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_sequential_access
            ),
            "worker_task_spill_capable_node_count": _count_worker_node_types(
                node_type_counts, _worker_is_spill_capable
            ),
        }
        for output, value in fallback_counts.items():
            if result.get(output, "") in ("", 0, 0.0):
                result[output] = value

    for output, column in (
        ("worker_task_shared_hit_sum", "worker_task_shared_hit_blocks"),
        ("worker_task_shared_read_sum", "worker_task_shared_read_blocks"),
        ("worker_task_temp_read_sum", "worker_task_temp_read_blocks"),
        ("worker_task_temp_written_sum", "worker_task_temp_written_blocks"),
    ):
        values = numeric(column)
        if values:
            result[output] = sum(values)
    worker_temp_read = _float_or_none(result.get("worker_task_temp_read_sum"))
    worker_temp_written = _float_or_none(result.get("worker_task_temp_written_sum"))
    if worker_temp_read is not None or worker_temp_written is not None:
        result["worker_task_spill_blocks_sum"] = (worker_temp_read or 0.0) + (
            worker_temp_written or 0.0
        )

    for output, column in (
        ("worker_task_has_join", "worker_task_has_join"),
        ("worker_task_has_aggregate", "worker_task_has_aggregate"),
        ("worker_task_has_sort", "worker_task_has_sort"),
        ("worker_task_has_blocking_operator", "worker_task_has_blocking_operator"),
        ("worker_task_has_parallel_operator", "worker_task_has_parallel_operator"),
        ("worker_task_has_hash", "worker_task_has_hash"),
        ("worker_task_has_materialize", "worker_task_has_materialize"),
    ):
        result[output] = 1 if any(_truthy(row.get(column)) for row in rows) else 0

    if node_type_counts:
        result["worker_task_has_join"] = int(result.get("worker_task_join_node_count", 0) != 0)
        result["worker_task_has_aggregate"] = int(
            result.get("worker_task_aggregate_node_count", 0) != 0
        )
        result["worker_task_has_sort"] = int(result.get("worker_task_sort_node_count", 0) != 0)
        result["worker_task_has_blocking_operator"] = int(
            result.get("worker_task_blocking_node_count", 0) != 0
        )
        result["worker_task_has_parallel_operator"] = int(
            result.get("worker_task_parallel_node_count", 0) != 0
        )
        result["worker_task_has_hash"] = int(
            any("Hash" in node_type for node_type in node_type_counts)
        )
        result["worker_task_has_materialize"] = int(
            result.get("worker_task_materialization_node_count", 0) != 0
        )

    fingerprints = [
        str(row.get("worker_task_plan_fingerprint", ""))
        for row in rows
        if str(row.get("worker_task_plan_fingerprint", "")).strip()
    ]
    if fingerprints:
        counts = Counter(fingerprints)
        result["worker_task_plan_fingerprint_count"] = len(counts)
        result["worker_task_plan_fingerprint_dominant_share"] = max(counts.values()) / len(
            fingerprints
        )

    rows_by_region: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        region = str(row.get("fdw_region") or "__unknown__")
        rows_by_region[region].append(row)
    if rows_by_region:
        result["worker_task_region_count"] = len(rows_by_region)
        result["worker_task_region_task_count_cv"] = _cv_or_none(
            [float(len(region_rows)) for region_rows in rows_by_region.values()]
        )

        region_row_sums: list[float] = []
        region_scan_row_sums: list[float] = []
        within_region_rows_cvs: list[float] = []
        within_region_scan_rows_cvs: list[float] = []
        within_region_rows_max_shares: list[float] = []
        within_region_scan_rows_max_shares: list[float] = []
        within_region_scan_rows_isfs: list[float] = []
        within_region_scan_rows_isfs_normalized: list[float] = []
        within_region_active_scan_rows_isfs_normalized: list[float] = []
        within_region_tuple_bytes_isfs_normalized: list[float] = []
        within_region_worker_scan_rows_cvs: list[float] = []
        within_region_worker_scan_rows_max_shares: list[float] = []
        within_region_worker_scan_rows_isfs: list[float] = []
        within_region_worker_scan_rows_isfs_normalized: list[float] = []
        task_skew_applicable_region_count = 0
        active_task_skew_applicable_region_count = 0
        tuple_bytes_skew_applicable_region_count = 0
        worker_skew_applicable_region_count = 0
        within_region_plan_fingerprint_counts: list[float] = []
        for region_rows in rows_by_region.values():
            region_actual_rows = [
                value
                for value in (
                    _float_or_none(row.get("worker_task_actual_rows")) for row in region_rows
                )
                if value is not None
            ]
            if region_actual_rows:
                row_sum = sum(region_actual_rows)
                region_row_sums.append(row_sum)
                cv = _cv_or_none(region_actual_rows)
                if cv is not None:
                    within_region_rows_cvs.append(cv)
                if row_sum > 0:
                    within_region_rows_max_shares.append(max(region_actual_rows) / row_sum)
            region_scan_actual_rows = [
                value
                for value in (
                    _float_or_none(row.get("worker_task_scan_actual_rows_sum"))
                    for row in region_rows
                )
                if value is not None
            ]
            if region_scan_actual_rows:
                scan_row_sum = sum(region_scan_actual_rows)
                region_scan_row_sums.append(scan_row_sum)
                if len(region_scan_actual_rows) >= 2 and scan_row_sum > 0:
                    task_skew_applicable_region_count += 1
                scan_cv = _cv_or_none(region_scan_actual_rows)
                if scan_cv is not None:
                    within_region_scan_rows_cvs.append(scan_cv)
                if scan_row_sum > 0:
                    scan_max_share = max(region_scan_actual_rows) / scan_row_sum
                    within_region_scan_rows_max_shares.append(scan_max_share)
                    within_region_scan_rows_isfs.append(
                        scan_max_share * len(region_scan_actual_rows)
                    )
                    normalized_task_isf = _normalized_isf(
                        scan_max_share * len(region_scan_actual_rows),
                        len(region_scan_actual_rows),
                    )
                    if normalized_task_isf is not None:
                        within_region_scan_rows_isfs_normalized.append(
                            normalized_task_isf
                        )
                active_region_scan_rows = [
                    value for value in region_scan_actual_rows if value > 0
                ]
                if len(active_region_scan_rows) >= 2:
                    active_task_skew_applicable_region_count += 1
                    active_scan_sum = sum(active_region_scan_rows)
                    active_scan_max_share = (
                        max(active_region_scan_rows) / active_scan_sum
                    )
                    normalized_active_task_isf = _normalized_isf(
                        active_scan_max_share * len(active_region_scan_rows),
                        len(active_region_scan_rows),
                    )
                    if normalized_active_task_isf is not None:
                        within_region_active_scan_rows_isfs_normalized.append(
                            normalized_active_task_isf
                        )
            region_tuple_bytes = [
                value
                for value in (
                    _float_or_none(row.get("tuple_data_received_bytes"))
                    for row in region_rows
                )
                if value is not None
            ]
            if region_tuple_bytes:
                region_tuple_bytes_sum = sum(region_tuple_bytes)
                if len(region_tuple_bytes) >= 2 and region_tuple_bytes_sum > 0:
                    tuple_bytes_skew_applicable_region_count += 1
                    tuple_bytes_max_share = (
                        max(region_tuple_bytes) / region_tuple_bytes_sum
                    )
                    normalized_tuple_bytes_isf = _normalized_isf(
                        tuple_bytes_max_share * len(region_tuple_bytes),
                        len(region_tuple_bytes),
                    )
                    if normalized_tuple_bytes_isf is not None:
                        within_region_tuple_bytes_isfs_normalized.append(
                            normalized_tuple_bytes_isf
                        )
            region_worker_task_counts: dict[str, int] = defaultdict(int)
            region_worker_scan_rows: dict[str, float] = defaultdict(float)
            region_worker_scan_observations: dict[str, int] = defaultdict(int)
            for row in region_rows:
                worker = str(row.get("worker_node", "")).strip()
                if not worker:
                    continue
                region_worker_task_counts[worker] += 1
                scan_rows = _float_or_none(
                    row.get("worker_task_scan_actual_rows_sum")
                )
                if scan_rows is not None:
                    region_worker_scan_rows[worker] += scan_rows
                    region_worker_scan_observations[worker] += 1
            region_worker_complete = bool(region_worker_task_counts) and all(
                region_worker_scan_observations[worker] == task_count
                for worker, task_count in region_worker_task_counts.items()
            )
            if region_worker_complete:
                region_worker_values = [
                    region_worker_scan_rows[worker]
                    for worker in sorted(region_worker_task_counts)
                ]
                region_worker_total = sum(region_worker_values)
                if len(region_worker_values) >= 2 and region_worker_total > 0:
                    worker_skew_applicable_region_count += 1
                    worker_cv = _cv_or_none(region_worker_values)
                    if worker_cv is not None:
                        within_region_worker_scan_rows_cvs.append(worker_cv)
                    worker_max_share = max(region_worker_values) / region_worker_total
                    worker_isf = worker_max_share * len(region_worker_values)
                    within_region_worker_scan_rows_max_shares.append(
                        worker_max_share
                    )
                    within_region_worker_scan_rows_isfs.append(worker_isf)
                    normalized_worker_isf = _normalized_isf(
                        worker_isf,
                        len(region_worker_values),
                    )
                    if normalized_worker_isf is not None:
                        within_region_worker_scan_rows_isfs_normalized.append(
                            normalized_worker_isf
                        )
            region_fingerprints = {
                str(row.get("worker_task_plan_fingerprint", ""))
                for row in region_rows
                if str(row.get("worker_task_plan_fingerprint", "")).strip()
            }
            if region_fingerprints:
                within_region_plan_fingerprint_counts.append(float(len(region_fingerprints)))

        if region_row_sums:
            region_total = sum(region_row_sums)
            result["worker_task_region_rows_cv"] = _cv_or_none(region_row_sums)
            result["worker_task_region_rows_max_share"] = (
                max(region_row_sums) / region_total if region_total > 0 else ""
            )
        if region_scan_row_sums:
            region_scan_total = sum(region_scan_row_sums)
            result["worker_task_region_scan_rows_cv"] = _cv_or_none(region_scan_row_sums)
            result["worker_task_region_scan_rows_max_share"] = (
                max(region_scan_row_sums) / region_scan_total if region_scan_total > 0 else ""
            )
        if within_region_rows_cvs:
            result["worker_task_within_region_rows_cv_max"] = max(within_region_rows_cvs)
            result["worker_task_within_region_rows_cv_mean"] = statistics.fmean(
                within_region_rows_cvs
            )
        if within_region_scan_rows_cvs:
            result["worker_task_within_region_scan_rows_cv_max"] = max(within_region_scan_rows_cvs)
            result["worker_task_within_region_scan_rows_cv_mean"] = statistics.fmean(
                within_region_scan_rows_cvs
            )
        if within_region_rows_max_shares:
            result["worker_task_within_region_rows_max_share_max"] = max(
                within_region_rows_max_shares
            )
        if within_region_scan_rows_max_shares:
            result["worker_task_within_region_scan_rows_max_share_max"] = max(
                within_region_scan_rows_max_shares
            )
        if within_region_scan_rows_isfs:
            result["worker_task_within_region_scan_rows_isf_max"] = max(
                within_region_scan_rows_isfs
            )
        if within_region_scan_rows_isfs_normalized:
            result[
                "worker_task_within_region_scan_rows_isf_normalized_max"
            ] = max(within_region_scan_rows_isfs_normalized)
        if within_region_active_scan_rows_isfs_normalized:
            result[
                "worker_task_within_region_active_scan_rows_isf_normalized_max"
            ] = max(within_region_active_scan_rows_isfs_normalized)
        if within_region_tuple_bytes_isfs_normalized:
            result[
                "worker_task_within_region_tuple_bytes_isf_normalized_max"
            ] = max(within_region_tuple_bytes_isfs_normalized)
        result["worker_task_scan_skew_applicable_region_count"] = (
            task_skew_applicable_region_count
        )
        result["worker_task_scan_skew_applicable"] = int(
            task_skew_applicable_region_count > 0
        )
        result["worker_task_active_scan_skew_applicable_region_count"] = (
            active_task_skew_applicable_region_count
        )
        result["worker_task_active_scan_skew_applicable"] = int(
            active_task_skew_applicable_region_count > 0
        )
        result["worker_task_tuple_bytes_skew_applicable_region_count"] = (
            tuple_bytes_skew_applicable_region_count
        )
        result["worker_task_tuple_bytes_skew_applicable"] = int(
            tuple_bytes_skew_applicable_region_count > 0
        )
        result["worker_scan_rows_skew_applicable_region_count"] = (
            worker_skew_applicable_region_count
        )
        result["worker_scan_rows_skew_applicable"] = int(
            worker_skew_applicable_region_count > 0
        )
        if within_region_worker_scan_rows_cvs:
            result["worker_task_within_region_worker_scan_rows_cv_max"] = max(
                within_region_worker_scan_rows_cvs
            )
            result["worker_task_within_region_worker_scan_rows_cv_mean"] = (
                statistics.fmean(within_region_worker_scan_rows_cvs)
            )
        if within_region_worker_scan_rows_max_shares:
            result[
                "worker_task_within_region_worker_scan_rows_max_share_max"
            ] = max(within_region_worker_scan_rows_max_shares)
        if within_region_worker_scan_rows_isfs:
            result["worker_task_within_region_worker_scan_rows_isf_max"] = max(
                within_region_worker_scan_rows_isfs
            )
        if within_region_worker_scan_rows_isfs_normalized:
            result[
                "worker_task_within_region_worker_scan_rows_isf_normalized_max"
            ] = max(within_region_worker_scan_rows_isfs_normalized)
        if within_region_plan_fingerprint_counts:
            result["worker_task_within_region_plan_fingerprint_count_max"] = max(
                within_region_plan_fingerprint_counts
            )
            result["worker_task_within_region_plan_fingerprint_count_mean"] = statistics.fmean(
                within_region_plan_fingerprint_counts
            )
    return result


def _merge_rows(
    *,
    execution_rows: list[dict[str, str]],
    query_rows: list[dict[str, str]],
    structure_rows: list[dict[str, str]],
    plan_nodes_by_run: dict[str, list[dict[str, str]]],
    remote_plans_by_run: dict[str, list[dict[str, str]]],
    region_fragments_by_run: dict[str, list[dict[str, str]]],
    worker_task_fragments_by_run: dict[str, list[dict[str, str]]],
    index_dir: Path | None = None,
) -> list[dict[str, Any]]:
    base_rows = execution_rows or query_rows
    structure_by_run = _one_by_query_run(structure_rows)
    query_by_run = _one_by_query_run(query_rows)
    merged: list[dict[str, Any]] = []
    for base in base_rows:
        query_run_id = str(base.get("query_run_id", ""))
        if not query_run_id:
            continue
        row: dict[str, Any] = {}
        row.update(query_by_run.get(query_run_id, {}))
        row.update(base)
        row.update(structure_by_run.get(query_run_id, {}))
        derived = _plan_node_aggregates(
            plan_nodes_by_run.get(query_run_id, []),
            index_dir=index_dir,
        )
        for key, value in derived.items():
            if _is_blank(row.get(key)):
                row[key] = value
        remote = _remote_plan_aggregates(remote_plans_by_run.get(query_run_id, []))
        for key, value in remote.items():
            if _is_blank(row.get(key)):
                row[key] = value
        regions = _remote_region_aggregates(
            region_fragments_by_run.get(query_run_id, []),
            expected_regions=_expected_remote_regions(row),
        )
        for key, value in regions.items():
            if _is_blank(row.get(key)):
                row[key] = value
        worker_tasks = _worker_task_aggregates(worker_task_fragments_by_run.get(query_run_id, []))
        for key, value in worker_tasks.items():
            if _is_blank(row.get(key)):
                row[key] = value
        _add_flow_proxy_features(row)
        _add_topology_normalized_features(row)
        merged.append(row)
    return merged


def _field_matches_pattern(field: str, pattern: str) -> bool:
    regex = "^" + re.escape(pattern).replace("\\*", ".*") + "$"
    return re.match(regex, field) is not None


def _selected_feature_names(
    *,
    schema: dict[str, Any],
    fields: list[str],
    matrix: str,
    topology: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    field_set = set(fields)
    selected: list[str] = []
    selected_entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in _schema_entries(schema):
        if entry.get("model_role") != "input":
            continue
        requires_topology = entry.get("requires_topology")
        if not _topology_satisfies(topology=topology, requires_topology=requires_topology):
            continue
        include = bool(entry.get("included_in_default_model") is True)
        if matrix == "m1":
            include = include or bool(entry.get("structural_feature") is True)
        if not include:
            continue

        if isinstance(entry.get("name"), str):
            source_column = str(entry.get("source_column") or entry["name"])
            output_name = str(entry["name"])
            if source_column in field_set and output_name not in seen:
                selected.append(output_name)
                selected_entries.append({**entry, "_source_column": source_column})
                seen.add(output_name)
        elif isinstance(entry.get("pattern"), str):
            pattern = str(entry["pattern"])
            for field in fields:
                if _field_matches_pattern(field, pattern) and field not in seen:
                    selected.append(field)
                    selected_entries.append({**entry, "_source_column": field, "name": field})
                    seen.add(field)
    return selected, selected_entries


def _topology_satisfies(*, topology: str, requires_topology: Any) -> bool:
    if requires_topology in ("", None):
        return True
    if isinstance(requires_topology, list):
        return any(
            _topology_satisfies(topology=topology, requires_topology=item)
            for item in requires_topology
        )
    required = str(requires_topology)
    if required not in TOPOLOGY_ORDER or topology not in TOPOLOGY_ORDER:
        return required == topology
    return TOPOLOGY_ORDER[topology] >= TOPOLOGY_ORDER[required]


def _context_columns(schema: dict[str, Any], fields: list[str]) -> list[str]:
    field_set = set(fields)
    selected: list[str] = []
    seen: set[str] = set()
    for field in IDENTITY_COLUMNS:
        if field in field_set and field not in seen:
            selected.append(field)
            seen.add(field)
    for field in QUALITY_COLUMNS:
        if field in field_set and field not in seen:
            selected.append(field)
            seen.add(field)
    for field in RAW_CONTEXT_COLUMNS:
        if field in field_set and field not in seen:
            selected.append(field)
            seen.add(field)
    for entry in _schema_entries(schema):
        role = str(entry.get("model_role", ""))
        if role == "input":
            continue
        candidates: list[str] = []
        if isinstance(entry.get("name"), str):
            candidates.append(str(entry.get("source_column") or entry["name"]))
        elif isinstance(entry.get("pattern"), str):
            candidates.extend(
                field for field in fields if _field_matches_pattern(field, str(entry["pattern"]))
            )
        for field in candidates:
            if field in field_set and field not in seen:
                selected.append(field)
                seen.add(field)
    return selected


def _normalize_value(value: Any) -> Any:
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return _bool_number(value)
    text = str(value)
    lower = text.lower()
    if lower == "true":
        return 1
    if lower == "false":
        return 0
    numeric = _float_or_none(text)
    if numeric is not None:
        return numeric
    return text


def _plan_parsed(row: dict[str, Any]) -> bool:
    if row.get("main_plan_node_count") not in ("", None):
        return True
    if str(row.get("main_plan_parse_error", "")).strip():
        return False
    return row.get("main_plan_json_file") not in ("", None)


def _feature_value(row: dict[str, Any], entry: dict[str, Any]) -> Any:
    source_column = str(entry.get("_source_column") or entry.get("name") or "")
    value = row.get(source_column, "")
    if value not in ("", None):
        return value
    null_policy = str(entry.get("null_policy", ""))
    if null_policy in {
        "missing_node_type_count_means_zero_after_plan_parse",
        "missing_transition_count_means_zero_after_plan_parse",
    } and _plan_parsed(row):
        return 0
    return ""


def _slug_value(value: Any) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", str(value or "unknown"))
    return "_".join(part.lower() for part in parts) or "unknown"


def _materialize_matrix(
    rows: list[dict[str, Any]],
    feature_entries: list[dict[str, Any]],
    *,
    include_query_run_id: bool = True,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[str]]:
    base_fields = ["query_run_id"] if include_query_run_id else []
    expanded_fields: list[str] = []
    categorical_expansions: list[dict[str, Any]] = []
    non_numeric_inputs: list[str] = []
    prepared_values: dict[str, list[Any]] = {}

    for entry in feature_entries:
        feature_name = str(entry["name"])
        values = [_normalize_value(_feature_value(row, entry)) for row in rows]
        non_blank = [value for value in values if value != ""]
        is_numeric = all(isinstance(value, int | float) for value in non_blank)
        if is_numeric:
            expanded_fields.append(feature_name)
            prepared_values[feature_name] = values
            continue

        non_numeric_inputs.append(feature_name)
        categories = sorted({str(value) for value in non_blank})
        for category in categories:
            expanded_name = f"{feature_name}__{_slug_value(category)}"
            expanded_fields.append(expanded_name)
            prepared_values[expanded_name] = [
                1 if str(value) == category else ("" if value == "" else 0) for value in values
            ]
            categorical_expansions.append(
                {
                    "source_feature": feature_name,
                    "expanded_feature": expanded_name,
                    "category": category,
                }
            )

    output_rows: list[dict[str, Any]] = []
    for index, source_row in enumerate(rows):
        row: dict[str, Any] = {}
        if include_query_run_id:
            row["query_run_id"] = source_row.get("query_run_id", "")
        for field in expanded_fields:
            row[field] = prepared_values[field][index]
        output_rows.append(row)
    return output_rows, base_fields + expanded_fields, categorical_expansions, non_numeric_inputs


def _write_feature_catalog(path: Path, entries: list[dict[str, Any]], fields: list[str]) -> None:
    rows = []
    selected = set(fields)
    for entry in entries:
        name = str(entry.get("name") or entry.get("pattern") or "")
        source = str(entry.get("_source_column") or entry.get("source_column") or name)
        is_selected = (
            name in selected
            or source in selected
            or any(field.startswith(name + "__") for field in fields)
        )
        if is_selected:
            rows.append(
                {
                    "feature": name,
                    "source_column": source,
                    "source_table": entry.get("source_table", ""),
                    "feature_scope": entry.get("feature_scope", ""),
                    "feature_reliability": entry.get("feature_reliability", ""),
                    "model_role": entry.get("model_role", ""),
                    "included_in_default_model": entry.get("included_in_default_model", ""),
                    "structural_feature": entry.get("structural_feature", ""),
                    "proxy_of": entry.get("proxy_of", ""),
                    "null_policy": entry.get("null_policy", ""),
                }
            )
    _write_csv(
        path,
        rows,
        [
            "feature",
            "source_column",
            "source_table",
            "feature_scope",
            "feature_reliability",
            "model_role",
            "included_in_default_model",
            "structural_feature",
            "proxy_of",
            "null_policy",
        ],
    )


def _matrix_quality_rows(
    *,
    matrix_name: str,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> list[dict[str, Any]]:
    result = []
    for field in fieldnames:
        if field == "query_run_id":
            continue
        values = [row.get(field, "") for row in rows]
        non_blank = [value for value in values if value not in ("", None)]
        numeric_count = sum(1 for value in non_blank if _float_or_none(value) is not None)
        zero_count = sum(1 for value in non_blank if _float_or_none(value) == 0)
        result.append(
            {
                "matrix": matrix_name,
                "feature": field,
                "row_count": len(rows),
                "non_null_count": len(non_blank),
                "null_count": len(rows) - len(non_blank),
                "null_fraction": (len(rows) - len(non_blank)) / len(rows) if rows else "",
                "numeric_count": numeric_count,
                "zero_count": zero_count,
                "distinct_non_null_count": len({str(value) for value in non_blank}),
            }
        )
    return result


def _numeric_sample(rows: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _float_or_none(row.get(field))
        if value is not None:
            values.append(value)
    return sorted(values)


def _log_excess_unit(value: Any, *, baseline: float = 0.0, critical_excess: float) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    excess = numeric - baseline
    if excess <= 0:
        return 0.0
    return min(math.log1p(excess) / math.log1p(critical_excess), 1.0)


def _linear_excess_unit(
    value: Any,
    *,
    baseline: float = 0.0,
    critical_excess: float,
) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    excess = numeric - baseline
    if excess <= 0:
        return 0.0
    return min(excess / critical_excess, 1.0)


def _max_number(values: list[Any]) -> float | None:
    numeric_values = [
        value for value in (_float_or_none(item) for item in values) if value is not None
    ]
    return max(numeric_values) if numeric_values else None


def _band_from_score(score: Any) -> str:
    numeric = _float_or_none(score)
    if numeric is None:
        return ""
    if numeric >= 0.95:
        return "critical"
    if numeric >= 0.80:
        return "high"
    if numeric >= 0.50:
        return "medium"
    return "low"


def _clipped_unit(value: Any) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    return max(0.0, min(numeric, 1.0))


def _build_execution_severity_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build topology-relative observed-intensity outputs.

    These columns are intentionally separate from the clustering matrices. They
    use flow/resource ratios, topology signals and runtime budgets to describe
    how strongly measured execution characteristics are expressed in the
    current experimental deployment. This is not a full
    hardware-capacity severity model and it intentionally does not rank the
    query against the observed corpus.
    """

    output_rows: list[dict[str, Any]] = []
    for source in rows:
        elapsed = _first_number(source, ["elapsed_seconds", "execution_time_seconds"])
        timeout = _float_or_none(source.get("hard_timeout_seconds"))
        temp_blocks = _float_or_none(source.get("temp_blocks_sum"))
        temp_bytes = temp_blocks * 8192.0 if temp_blocks is not None else None
        wan_bytes = _float_or_none(source.get("wan_output_bytes_proxy"))
        regional_bytes = _float_or_none(source.get("regional_reduction_input_bytes_proxy"))

        configured_slots_ratio = _float_or_none(
            source.get("task_count_to_configured_region_shard_slots_ratio")
        )
        observed_slots_ratio = _float_or_none(
            source.get("task_count_to_observed_region_shard_slots_ratio")
        )
        timeout_utilization = _safe_divide(elapsed, timeout)

        wan_fetch_intensity = _max_number(
            [
                _log_excess_unit(
                    source.get("remote_to_final_rows_ratio"),
                    baseline=1.0,
                    critical_excess=100000.0,
                ),
                _log_excess_unit(
                    source.get("wan_output_to_final_rows_ratio"),
                    baseline=1.0,
                    critical_excess=100000.0,
                ),
                _log_excess_unit(
                    source.get("global_fanin_ratio"),
                    baseline=1.0,
                    critical_excess=100000.0,
                ),
            ]
        )
        memory_spill_intensity = _max_number(
            [
                _log_excess_unit(
                    source.get("temp_bytes_to_wan_bytes_ratio"),
                    baseline=0.0,
                    critical_excess=4.0,
                ),
                _log_excess_unit(
                    source.get("temp_blocks_per_wan_row"),
                    baseline=0.0,
                    critical_excess=0.1,
                ),
                _log_excess_unit(
                    source.get("temp_blocks_per_regional_input_row"),
                    baseline=0.0,
                    critical_excess=0.1,
                ),
                _log_excess_unit(
                    source.get("spill_per_wan_mb"),
                    baseline=0.0,
                    critical_excess=8192.0,
                ),
                _log_excess_unit(
                    source.get("memory_pressure_score_v1"),
                    baseline=0.0,
                    critical_excess=32.0,
                ),
            ]
        )
        imbalance_intensity = _max_number(
            [
                _linear_excess_unit(
                    source.get("remote_region_rows_isf"),
                    baseline=1.0,
                    critical_excess=1.0,
                ),
                _linear_excess_unit(
                    source.get("remote_region_bytes_isf"),
                    baseline=1.0,
                    critical_excess=1.0,
                ),
                _linear_excess_unit(
                    source.get("worker_task_scan_rows_isf"),
                    baseline=1.0,
                    critical_excess=3.0,
                ),
                _linear_excess_unit(
                    source.get("worker_task_root_rows_isf"),
                    baseline=1.0,
                    critical_excess=3.0,
                ),
                _linear_excess_unit(
                    source.get("worker_task_within_region_scan_rows_isf_max"),
                    baseline=1.0,
                    critical_excess=3.0,
                ),
            ]
        )
        capacity_intensity = _max_number(
            [
                _linear_excess_unit(
                    source.get("active_task_share"),
                    baseline=1.0,
                    critical_excess=3.0,
                ),
                _log_excess_unit(
                    source.get("tasks_per_worker_ratio"),
                    baseline=8.0,
                    critical_excess=56.0,
                ),
                _linear_excess_unit(
                    source.get("task_count_to_shard_count_ratio"),
                    baseline=1.0,
                    critical_excess=3.0,
                ),
                _linear_excess_unit(
                    configured_slots_ratio,
                    baseline=1.0,
                    critical_excess=3.0,
                ),
                _linear_excess_unit(
                    observed_slots_ratio,
                    baseline=1.0,
                    critical_excess=3.0,
                ),
            ]
        )
        timeout_relative = (
            min(timeout_utilization, 1.0) if timeout_utilization is not None else None
        )
        deployment_relative_intensity = _max_number(
            [
                wan_fetch_intensity,
                memory_spill_intensity,
                imbalance_intensity,
                capacity_intensity,
                timeout_relative,
            ]
        )
        severity_score = deployment_relative_intensity

        basis = []
        for label, value in (
            ("wan_fetch_intensity", wan_fetch_intensity),
            ("memory_spill_intensity", memory_spill_intensity),
            ("imbalance_intensity", imbalance_intensity),
            ("capacity_intensity", capacity_intensity),
            ("timeout_utilization", timeout_relative),
        ):
            if value is not None:
                basis.append(label)

        output_rows.append(
            {
                "query_run_id": source.get("query_run_id", ""),
                "dataset_id": source.get("dataset_id", ""),
                "runtime_config_id": source.get("runtime_config_id", ""),
                "template_id": source.get("template_id", ""),
                "instance_id": source.get("instance_id", ""),
                "severity_contract": "deployment_relative_pressure_proxy_v2",
                "severity_model_role": "posthoc_audit_not_clustering_input",
                "severity_score": _blank_if_none(severity_score),
                "severity_band": _band_from_score(severity_score),
                "deployment_relative_intensity_score": _blank_if_none(
                    deployment_relative_intensity
                ),
                "wan_fetch_intensity_score": _blank_if_none(wan_fetch_intensity),
                "memory_spill_intensity_score": _blank_if_none(memory_spill_intensity),
                "imbalance_intensity_score": _blank_if_none(imbalance_intensity),
                "capacity_intensity_score": _blank_if_none(capacity_intensity),
                "corpus_relative_severity_score": "",
                "sum_pressure_score": _blank_if_none(
                    _max_number([wan_fetch_intensity, memory_spill_intensity])
                ),
                "tail_pressure_score": _blank_if_none(imbalance_intensity),
                "capacity_relative_severity_score": _blank_if_none(capacity_intensity),
                "timeout_relative_severity_score": _blank_if_none(timeout_relative),
                "severity_basis": ",".join(basis),
                "execution_time_seconds": _blank_if_none(elapsed),
                "execution_time_corpus_percentile": "",
                "hard_timeout_seconds": _blank_if_none(timeout),
                "timeout_utilization_ratio": _blank_if_none(timeout_utilization),
                "wan_output_rows": _blank_if_none(source.get("wan_output_rows")),
                "wan_output_bytes": _blank_if_none(wan_bytes),
                "wan_output_mb": _blank_if_none(
                    wan_bytes / (1024.0 * 1024.0) if wan_bytes is not None else None
                ),
                "wan_output_bytes_corpus_percentile": "",
                "remote_region_tuple_bytes_sum": _blank_if_none(
                    source.get("remote_region_tuple_bytes_sum")
                ),
                "remote_region_tuple_bytes_corpus_percentile": "",
                "regional_reduction_input_rows_proxy": _blank_if_none(
                    source.get("regional_reduction_input_rows_proxy")
                ),
                "regional_reduction_input_bytes_proxy": _blank_if_none(regional_bytes),
                "regional_reduction_input_mb_proxy": _blank_if_none(
                    regional_bytes / (1024.0 * 1024.0) if regional_bytes is not None else None
                ),
                "drf_rows_proxy": _blank_if_none(source.get("drf_rows_proxy")),
                "drf_bytes_proxy": _blank_if_none(source.get("drf_bytes_proxy")),
                "temp_blocks_sum": _blank_if_none(temp_blocks),
                "temp_mb": _blank_if_none(
                    temp_bytes / (1024.0 * 1024.0) if temp_bytes is not None else None
                ),
                "temp_blocks_corpus_percentile": "",
                "remote_region_rows_isf": _blank_if_none(source.get("remote_region_rows_isf")),
                "remote_region_rows_isf_corpus_percentile": "",
                "worker_task_scan_rows_isf": _blank_if_none(
                    source.get("worker_task_scan_rows_isf")
                ),
                "worker_task_scan_rows_isf_corpus_percentile": "",
                "worker_task_within_region_scan_rows_isf_max": _blank_if_none(
                    source.get("worker_task_within_region_scan_rows_isf_max")
                ),
                "worker_task_within_region_scan_rows_isf_corpus_percentile": "",
                "active_task_share": _blank_if_none(source.get("active_task_share")),
                "active_task_share_corpus_percentile": "",
                "tasks_per_worker_ratio": _blank_if_none(source.get("tasks_per_worker_ratio")),
                "tasks_per_worker_ratio_corpus_percentile": "",
                "task_count_to_configured_region_shard_slots_ratio": _blank_if_none(
                    configured_slots_ratio
                ),
                "task_count_to_configured_region_shard_slots_corpus_percentile": "",
                "task_count_to_observed_region_shard_slots_ratio": _blank_if_none(
                    observed_slots_ratio
                ),
                "task_count_to_observed_region_shard_slots_corpus_percentile": "",
            }
        )

    fields = [
        "query_run_id",
        "dataset_id",
        "runtime_config_id",
        "template_id",
        "instance_id",
        "severity_contract",
        "severity_model_role",
        "severity_score",
        "severity_band",
        "deployment_relative_intensity_score",
        "wan_fetch_intensity_score",
        "memory_spill_intensity_score",
        "imbalance_intensity_score",
        "capacity_intensity_score",
        "corpus_relative_severity_score",
        "sum_pressure_score",
        "tail_pressure_score",
        "capacity_relative_severity_score",
        "timeout_relative_severity_score",
        "severity_basis",
        "execution_time_seconds",
        "execution_time_corpus_percentile",
        "hard_timeout_seconds",
        "timeout_utilization_ratio",
        "wan_output_rows",
        "wan_output_bytes",
        "wan_output_mb",
        "wan_output_bytes_corpus_percentile",
        "remote_region_tuple_bytes_sum",
        "remote_region_tuple_bytes_corpus_percentile",
        "regional_reduction_input_rows_proxy",
        "regional_reduction_input_bytes_proxy",
        "regional_reduction_input_mb_proxy",
        "drf_rows_proxy",
        "drf_bytes_proxy",
        "temp_blocks_sum",
        "temp_mb",
        "temp_blocks_corpus_percentile",
        "remote_region_rows_isf",
        "remote_region_rows_isf_corpus_percentile",
        "worker_task_scan_rows_isf",
        "worker_task_scan_rows_isf_corpus_percentile",
        "worker_task_within_region_scan_rows_isf_max",
        "worker_task_within_region_scan_rows_isf_corpus_percentile",
        "active_task_share",
        "active_task_share_corpus_percentile",
        "tasks_per_worker_ratio",
        "tasks_per_worker_ratio_corpus_percentile",
        "task_count_to_configured_region_shard_slots_ratio",
        "task_count_to_configured_region_shard_slots_corpus_percentile",
        "task_count_to_observed_region_shard_slots_ratio",
        "task_count_to_observed_region_shard_slots_corpus_percentile",
    ]
    return output_rows, fields


def _build_dataset_diagnosis_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_dataset: dict[str, dict[str, Any]] = {}
    for row in rows:
        dataset_id = str(row.get("dataset_id") or row.get("dataset_profile_id") or "").strip()
        if not dataset_id or dataset_id in by_dataset:
            continue
        profile_path = _dataset_profile_path(row)
        profile = load_yaml(profile_path) if profile_path is not None else {}
        scale = profile.get("scale", {}) if isinstance(profile, dict) else {}
        distribution = profile.get("distribution", {}) if isinstance(profile, dict) else {}
        capabilities = profile.get("capabilities", {}) if isinstance(profile, dict) else {}
        regions = profile.get("regions", {}) if isinstance(profile, dict) else {}
        if isinstance(capabilities, dict):
            true_capabilities = [
                key
                for key, value in capabilities.items()
                if isinstance(key, str) and _truthy(value)
            ]
            false_capabilities = [
                key
                for key, value in capabilities.items()
                if isinstance(key, str) and value is False
            ]
        else:
            true_capabilities = []
            false_capabilities = []

        profile_path_text = str(profile_path.relative_to(_repo_root())) if profile_path else ""
        profile_value = (
            profile.get if isinstance(profile, dict) else lambda _key, default="": default
        )
        scale_value = scale.get if isinstance(scale, dict) else lambda _key, default="": default
        distribution_value = (
            distribution.get if isinstance(distribution, dict) else lambda _key, default="": default
        )

        by_dataset[dataset_id] = {
            "dataset_id": dataset_id,
            "dataset_profile_path": profile_path_text,
            "dataset_budget_class": profile_value("budget_class", ""),
            "dataset_seed": profile_value("seed", ""),
            "dataset_tenants_total": scale_value("tenants_total", ""),
            "dataset_events_per_tenant_avg": scale_value("events_per_tenant_avg", ""),
            "dataset_users_per_tenant_avg": scale_value("users_per_tenant_avg", ""),
            "dataset_lookback_days": scale_value("lookback_days", ""),
            "dataset_region_count": len(regions) if isinstance(regions, dict) and regions else "",
            "dataset_distribution_key": distribution_value("distribution_key", ""),
            "dataset_shard_count": distribution_value("shard_count", ""),
            "dataset_skew_profile": distribution_value("skew_profile", ""),
            "dataset_hot_tenant_pct": distribution_value("hot_tenant_pct", ""),
            "dataset_hot_event_pct": distribution_value("hot_event_pct", ""),
            "dataset_capability_true_count": len(true_capabilities),
            "dataset_capability_false_count": len(false_capabilities),
            "dataset_capabilities_true": ",".join(sorted(true_capabilities)),
            "dataset_capabilities_false": ",".join(sorted(false_capabilities)),
            "dataset_diagnosis_model_role": "audit_context_not_clustering_input",
        }

    fields = [
        "dataset_id",
        "dataset_profile_path",
        "dataset_budget_class",
        "dataset_seed",
        "dataset_tenants_total",
        "dataset_events_per_tenant_avg",
        "dataset_users_per_tenant_avg",
        "dataset_lookback_days",
        "dataset_region_count",
        "dataset_distribution_key",
        "dataset_shard_count",
        "dataset_skew_profile",
        "dataset_hot_tenant_pct",
        "dataset_hot_event_pct",
        "dataset_capability_true_count",
        "dataset_capability_false_count",
        "dataset_capabilities_true",
        "dataset_capabilities_false",
        "dataset_diagnosis_model_role",
    ]
    return list(by_dataset.values()), fields


def build_feature_matrix(
    *,
    index_dir: Path,
    out_dir: Path | None = None,
    schema_path: Path | None = None,
    topology: str = "eu_only",
) -> Path:
    index_dir = index_dir.resolve()
    if out_dir is None:
        out_dir = index_dir / "features"
    else:
        out_dir = out_dir.resolve()
    schema_file = _schema_path(index_dir, schema_path)
    schema = load_yaml(schema_file)

    execution_rows = _read_csv(index_dir / "execution_features.csv")
    query_rows = _read_csv(index_dir / "query_runs.csv")
    structure_rows = _read_csv(index_dir / "plan_structure_features.csv")
    plan_nodes = _read_csv(index_dir / "plan_nodes.csv")
    remote_plans = _read_csv(index_dir / "fdw_remote_plans.csv")
    region_fragments = _read_csv(index_dir / "region_fragments.csv")
    worker_task_fragments = _read_csv(index_dir / "worker_task_fragments.csv")

    merged_rows = _merge_rows(
        execution_rows=execution_rows,
        query_rows=query_rows,
        structure_rows=structure_rows,
        plan_nodes_by_run=_group_by_query_run(plan_nodes),
        remote_plans_by_run=_group_by_query_run(remote_plans),
        region_fragments_by_run=_group_by_query_run(region_fragments),
        worker_task_fragments_by_run=_group_by_query_run(worker_task_fragments),
        index_dir=index_dir,
    )
    if not merged_rows:
        raise ValueError(f"No query-run rows found in {index_dir}")

    all_fields = _all_fields(merged_rows)
    m0_features, m0_entries = _selected_feature_names(
        schema=schema,
        fields=all_fields,
        matrix="m0",
        topology=topology,
    )
    m1_features, m1_entries = _selected_feature_names(
        schema=schema,
        fields=all_fields,
        matrix="m1",
        topology=topology,
    )
    m0_rows, m0_fields, m0_expansions, m0_non_numeric = _materialize_matrix(
        merged_rows,
        m0_entries,
    )
    m1_rows, m1_fields, m1_expansions, m1_non_numeric = _materialize_matrix(
        merged_rows,
        m1_entries,
    )
    context_fields = _context_columns(schema, all_fields)
    context_rows = [{field: row.get(field, "") for field in context_fields} for row in merged_rows]
    severity_rows, severity_fields = _build_execution_severity_rows(merged_rows)
    dataset_diagnosis_rows, dataset_diagnosis_fields = _build_dataset_diagnosis_rows(merged_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        out_dir / "execution_features_all.csv",
        merged_rows,
        all_fields,
    )
    _write_csv(out_dir / "execution_features_m0.csv", m0_rows, m0_fields)
    _write_csv(out_dir / "execution_features_m1.csv", m1_rows, m1_fields)
    _write_csv(out_dir / "model_context.csv", context_rows, context_fields)
    _write_csv(out_dir / "execution_severity.csv", severity_rows, severity_fields)
    _write_csv(
        out_dir / "dataset_diagnosis.csv",
        dataset_diagnosis_rows,
        dataset_diagnosis_fields,
    )
    _write_feature_catalog(out_dir / "feature_catalog_m0.csv", m0_entries, m0_features)
    _write_feature_catalog(out_dir / "feature_catalog_m1.csv", m1_entries, m1_features)
    quality_rows = _matrix_quality_rows(
        matrix_name="m0",
        rows=m0_rows,
        fieldnames=m0_fields,
    ) + _matrix_quality_rows(
        matrix_name="m1",
        rows=m1_rows,
        fieldnames=m1_fields,
    )
    _write_csv(
        out_dir / "feature_quality_report.csv",
        quality_rows,
        [
            "matrix",
            "feature",
            "row_count",
            "non_null_count",
            "null_count",
            "null_fraction",
            "numeric_count",
            "zero_count",
            "distinct_non_null_count",
        ],
    )
    _write_csv(
        out_dir / "categorical_expansions.csv",
        m0_expansions + m1_expansions,
        ["source_feature", "expanded_feature", "category"],
    )

    manifest = {
        "feature_matrix_contract": "master_regimes_feature_matrix_v1",
        "fdw_pushdown_fidelity_contract": FDW_PUSHDOWN_FIDELITY_CONTRACT,
        "source_index_dir": str(index_dir),
        "schema_path": str(schema_file),
        "topology": topology,
        "row_count": len(merged_rows),
        "outputs": {
            "all": "execution_features_all.csv",
            "m0": "execution_features_m0.csv",
            "m1": "execution_features_m1.csv",
            "context": "model_context.csv",
            "severity": "execution_severity.csv",
            "dataset_diagnosis": "dataset_diagnosis.csv",
            "m0_catalog": "feature_catalog_m0.csv",
            "m1_catalog": "feature_catalog_m1.csv",
            "categorical_expansions": "categorical_expansions.csv",
            "quality_report": "feature_quality_report.csv",
        },
        "matrices": {
            "all": {
                "description": (
                    "complete merged execution feature layer before model-role filtering"
                ),
                "column_count": len(all_fields),
                "feature_count": len(all_fields) - 1,
            },
            "m0": {
                "description": "core_model_v1 behavioral input features",
                "column_count": len(m0_fields),
                "feature_count": len(m0_fields) - 1,
                "schema_feature_count": len(m0_features),
                "non_numeric_source_features_expanded": sorted(set(m0_non_numeric)),
            },
            "m1": {
                "description": "core_model_v1 plus plan_structure_v1 ablation features",
                "column_count": len(m1_fields),
                "feature_count": len(m1_fields) - 1,
                "schema_feature_count": len(m1_features),
                "non_numeric_source_features_expanded": sorted(set(m1_non_numeric)),
            },
            "context": {
                "description": "IDs, labels, runtime knobs, audit and quality-gate columns",
                "column_count": len(context_fields),
            },
            "severity": {
                "description": (
                    "post-hoc indeks opaženog intenziteta u odnosu na topologiju; "
                    "not a clustering input"
                ),
                "column_count": len(severity_fields),
                "row_count": len(severity_rows),
            },
            "dataset_diagnosis": {
                "description": (
                    "dataset profile scale/skew/capability context; not a clustering input"
                ),
                "column_count": len(dataset_diagnosis_fields),
                "row_count": len(dataset_diagnosis_rows),
            },
        },
        "rules": {
            "null_policy": (
                "missing values remain blank; zero is emitted only for explicitly "
                "derived count/boolean features"
            ),
            "default_model_filter": "included_in_default_model=true and model_role=input",
            "severity_policy": (
                "execution_severity.csv uses deployment/topology-relative observed-"
                "intensity proxy scores and remains separated from M0/M1 clustering inputs"
            ),
            "m1_extra_filter": "structural_feature=true and model_role=input",
            "categorical_policy": (
                "non-numeric selected input features are one-hot expanded with "
                "source_feature__category columns"
            ),
        },
    }
    write_yaml(out_dir / "feature_matrix_manifest.yml", manifest)
    return out_dir
