from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
import textwrap
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .explain_json import extract_plan_rows, plan_fingerprint
from .plan_structure import finalize_plan_structure_rows, plan_structure_feature_row

CORPUS_METADATA_FIELDS = [
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
    "regional_pg_options_json",
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
]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _load_json_value(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _metadata_text(value: Any) -> str:
    if value in ("", None):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, dict):
        return _json_text(value)
    return str(value)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _safe_file_stem(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return sanitized[:180] or "value"


WORKER_PLAN_NODE_TYPES = [
    "Bitmap Heap Scan",
    "Bitmap Index Scan",
    "Index Only Scan",
    "Index Scan",
    "Parallel Seq Scan",
    "Seq Scan",
    "Tid Scan",
    "Subquery Scan",
    "Function Scan",
    "Values Scan",
    "CTE Scan",
    "Foreign Scan",
    "Custom Scan",
    "Hash Join",
    "Parallel Hash Join",
    "Merge Join",
    "Nested Loop",
    "Finalize Aggregate",
    "Partial Aggregate",
    "HashAggregate",
    "GroupAggregate",
    "MixedAggregate",
    "Aggregate",
    "Incremental Sort",
    "Sort",
    "Materialize",
    "Memoize",
    "Parallel Hash",
    "Hash",
    "Gather Merge",
    "Gather",
    "Append",
    "Merge Append",
    "BitmapAnd",
    "BitmapOr",
    "Limit",
    "Unique",
    "WindowAgg",
    "Result",
]


WORKER_PLAN_PROPERTY_PREFIXES = (
    "actual ",
    "buckets:",
    "buffers:",
    "cache ",
    "filter:",
    "group key:",
    "hash cond:",
    "index cond:",
    "index searches:",
    "join filter:",
    "merge cond:",
    "output:",
    "planned partitions:",
    "recheck cond:",
    "rows removed",
    "sort key:",
    "sort method:",
    "workers ",
)


def _extract_remote_plan_text_blocks(lines: list[str]) -> list[str]:
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if '"Remote Plan": [' not in lines[index]:
            index += 1
            continue
        index += 1
        block_lines: list[str] = []
        while index < len(lines):
            stripped = lines[index].strip()
            if stripped.startswith("]"):
                break
            block_lines.append(lines[index].rstrip())
            index += 1
        blocks.append(textwrap.dedent("\n".join(block_lines)).strip("\n"))
        index += 1
    return blocks


def _parse_worker_plan_node_type(line: str) -> str:
    candidate = re.sub(r"^\s*->\s*", "", line.strip())
    for node_type in WORKER_PLAN_NODE_TYPES:
        if candidate == node_type or candidate.startswith(node_type + " "):
            return node_type
    return ""


def _worker_plan_depth(line: str) -> int:
    stripped = line.lstrip()
    if stripped.startswith("->"):
        stripped = stripped[2:].lstrip()
    leading = len(line) - len(line.lstrip())
    return max(0, leading // 2)


def _scan_class(node_type: str) -> str:
    if node_type in {"Seq Scan", "Parallel Seq Scan"}:
        return "seq_scan"
    if node_type in {"Index Scan", "Index Only Scan"}:
        return "index_scan"
    if node_type in {"Bitmap Heap Scan", "Bitmap Index Scan", "BitmapAnd", "BitmapOr"}:
        return "bitmap_scan"
    if "Scan" in node_type:
        return "other_scan"
    return ""


def _is_worker_join(node_type: str) -> bool:
    return "Join" in node_type or node_type == "Nested Loop"


def _is_worker_aggregate(node_type: str) -> bool:
    return "Aggregate" in node_type


def _is_worker_sort(node_type: str) -> bool:
    return "Sort" in node_type


def _is_worker_blocking(node_type: str) -> bool:
    return (
        _is_worker_aggregate(node_type)
        or _is_worker_sort(node_type)
        or node_type in {"Materialize", "Hash", "Unique", "WindowAgg"}
    )


def _is_worker_materialization(node_type: str) -> bool:
    return node_type in {"Materialize", "Memoize"}


def _is_worker_parallel(node_type: str) -> bool:
    return "Parallel" in node_type or node_type in {"Gather", "Gather Merge"}


def _is_worker_bitmap(node_type: str) -> bool:
    return node_type in {"Bitmap Heap Scan", "Bitmap Index Scan", "BitmapAnd", "BitmapOr"}


def _is_worker_index_access(node_type: str) -> bool:
    return node_type in {"Index Scan", "Index Only Scan", "Bitmap Index Scan"}


def _is_worker_sequential_access(node_type: str) -> bool:
    return node_type in {"Seq Scan", "Parallel Seq Scan"}


def _is_worker_spill_capable(node_type: str) -> bool:
    return _is_worker_blocking(node_type) or node_type in {"Hash Join", "Merge Join"}


def _buffer_counter(line: str, buffer_class: str, counter: str) -> float:
    match = re.search(rf"\b{buffer_class}\b[^\n]*?\b{counter}=([0-9]+)", line)
    return float(match.group(1)) if match else 0.0


def _worker_text_plan_summary(text: str) -> dict[str, Any]:
    node_counts: Counter[str] = Counter()
    scan_counts: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    node_rows: list[float] = []
    node_times: list[float] = []
    scan_node_rows: list[float] = []
    max_depth = 0
    root_node_type = ""
    root_rows: float | None = None
    root_time: float | None = None
    spill_count = 0
    shared_hit_blocks = 0.0
    shared_read_blocks = 0.0
    temp_read_blocks = 0.0
    temp_written_blocks = 0.0

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = re.sub(r"^\s*->\s*", "", line.strip())
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith(WORKER_PLAN_PROPERTY_PREFIXES):
            if lower.startswith("buffers:"):
                shared_hit_blocks += _buffer_counter(lower, "shared", "hit")
                shared_read_blocks += _buffer_counter(lower, "shared", "read")
                temp_read_blocks += _buffer_counter(lower, "temp", "read")
                temp_written_blocks += _buffer_counter(lower, "temp", "written")
            if "external" in lower or "disk" in lower or "temp" in lower:
                spill_count += 1
            continue
        node_type = _parse_worker_plan_node_type(line)
        if not node_type:
            if "actual " in lower or re.search(r"\bscan\b|\bjoin\b|aggregate|sort", lower):
                unknown[stripped.split("(", 1)[0].strip()] += 1
            continue
        if not root_node_type:
            root_node_type = node_type
        node_counts[node_type] += 1
        scan_class = _scan_class(node_type)
        if scan_class:
            scan_counts[scan_class] += 1
        max_depth = max(max_depth, _worker_plan_depth(line))

        actual_rows = None
        actual_time = None
        rows_match = re.search(r"\bactual rows=([0-9]+(?:\.[0-9]+)?)", stripped)
        if rows_match:
            actual_rows = float(rows_match.group(1))
        else:
            detailed_rows_match = re.search(
                r"\bactual time=[0-9.]+(?:\.\.)?([0-9.]+)?\s+rows=([0-9]+(?:\.[0-9]+)?)",
                stripped,
            )
            if detailed_rows_match:
                actual_rows = float(detailed_rows_match.group(2))
        time_match = re.search(r"\bactual time=[0-9.]+\.\.([0-9]+(?:\.[0-9]+)?)", stripped)
        if time_match:
            actual_time = float(time_match.group(1))
        if actual_rows is not None:
            node_rows.append(actual_rows)
            if scan_class:
                scan_node_rows.append(actual_rows)
            if root_rows is None:
                root_rows = actual_rows
        if actual_time is not None:
            node_times.append(actual_time)
            if root_time is None:
                root_time = actual_time
        if "external" in lower or "disk" in lower or "temp" in lower:
            spill_count += 1

    fingerprint_payload = {
        "root_node_type": root_node_type,
        "node_types": dict(sorted(node_counts.items())),
    }
    return {
        "parse_status": "partial" if node_counts else ("empty" if not text.strip() else "failed"),
        "parse_confidence": "medium" if node_counts else "low",
        "root_node_type": root_node_type,
        "node_count": sum(node_counts.values()),
        "max_depth": max_depth if node_counts else "",
        "node_type_counts": dict(sorted(node_counts.items())),
        "scan_type_counts": dict(sorted(scan_counts.items())),
        "unknown_count": sum(unknown.values()),
        "unknown_set": sorted(unknown),
        "actual_rows": root_rows if root_rows is not None else "",
        "scan_actual_rows_sum": sum(scan_node_rows) if scan_node_rows else "",
        "scan_actual_rows_max": max(scan_node_rows) if scan_node_rows else "",
        "actual_time_ms": root_time if root_time is not None else "",
        "actual_rows_sum": sum(node_rows) if node_rows else "",
        "actual_time_sum_ms": sum(node_times) if node_times else "",
        "join_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_join(node)
        ),
        "aggregate_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_aggregate(node)
        ),
        "sort_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_sort(node)
        ),
        "blocking_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_blocking(node)
        ),
        "scan_node_count": sum(count for node, count in node_counts.items() if _scan_class(node)),
        "materialization_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_materialization(node)
        ),
        "parallel_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_parallel(node)
        ),
        "bitmap_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_bitmap(node)
        ),
        "index_access_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_index_access(node)
        ),
        "sequential_access_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_sequential_access(node)
        ),
        "spill_capable_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_spill_capable(node)
        ),
        "has_join": any(_is_worker_join(node) for node in node_counts),
        "has_aggregate": any(_is_worker_aggregate(node) for node in node_counts),
        "has_sort": any(_is_worker_sort(node) for node in node_counts),
        "has_blocking_operator": any(_is_worker_blocking(node) for node in node_counts),
        "has_parallel_operator": any(_is_worker_parallel(node) for node in node_counts),
        "has_hash": any("Hash" in node for node in node_counts),
        "has_materialize": "Materialize" in node_counts,
        "spill_flag": bool(spill_count),
        "spill_count": spill_count,
        "shared_hit_blocks": shared_hit_blocks if shared_hit_blocks else "",
        "shared_read_blocks": shared_read_blocks if shared_read_blocks else "",
        "temp_read_blocks": temp_read_blocks if temp_read_blocks else "",
        "temp_written_blocks": temp_written_blocks if temp_written_blocks else "",
        "plan_fingerprint": _hash_text(_json_text(fingerprint_payload)) if node_counts else "",
    }


def _attach_worker_plan_summaries(document: dict[str, Any], text_blocks: list[str]) -> None:
    tasks: list[dict[str, Any]] = []
    for _, group_tasks in _iter_citus_task_groups(document):
        tasks.extend(task for task in group_tasks if isinstance(task, dict))
    for task, text in zip(tasks, text_blocks, strict=False):
        task["Worker Plan Summary"] = _worker_text_plan_summary(text)


def _extract_auto_explain_json_documents(log_text: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    lines = log_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if " plan:" not in line:
            index += 1
            continue
        duration_match = re.search(r"\bduration:\s*([0-9]+(?:\.[0-9]+)?)\s*ms\b", line)
        duration_ms = float(duration_match.group(1)) if duration_match else None
        index += 1
        json_lines: list[str] = []
        brace_balance = 0
        started = False
        while index < len(lines):
            current = lines[index]
            stripped = current.strip()
            if not started and not stripped.startswith("{"):
                index += 1
                continue
            started = True
            json_lines.append(current)
            brace_balance += stripped.count("{") - stripped.count("}")
            index += 1
            if brace_balance <= 0:
                break
        if not json_lines:
            continue
        remote_plan_text_blocks = _extract_remote_plan_text_blocks(json_lines)
        try:
            parsed = json.loads("\n".join(_sanitize_citus_remote_plan_json_lines(json_lines)))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("Plan"), dict):
            if duration_ms is not None:
                parsed["Auto Explain Duration Ms"] = duration_ms
            _attach_worker_plan_summaries(parsed, remote_plan_text_blocks)
            documents.append(parsed)
    return documents


def _sanitize_citus_remote_plan_json_lines(lines: list[str]) -> list[str]:
    sanitized: list[str] = []
    skip_remote_plan = False
    for line in lines:
        stripped = line.strip()
        if skip_remote_plan:
            if stripped.startswith("]"):
                skip_remote_plan = False
            continue
        if '"Remote Plan": [' in stripped:
            indent = line[: len(line) - len(line.lstrip())]
            sanitized.append(f'{indent}"Remote Plan": []')
            skip_remote_plan = True
            continue
        sanitized.append(line)
    return sanitized


def _auto_explain_plan_files(
    *,
    root: Path,
    out_dir: Path,
    collection_dir: Path,
    query_run_id: str,
    fdw_auto_explain_hosts: dict[str, Any],
) -> list[dict[str, Any]]:
    plan_records: list[dict[str, Any]] = []
    output_dir = out_dir / "auto_explain_plans" / _safe_file_stem(query_run_id)
    for host_name, host_payload in sorted(fdw_auto_explain_hosts.items()):
        if not isinstance(host_payload, dict):
            continue
        region = str(host_payload.get("region", ""))
        local_log_file = str(host_payload.get("local_log_file", ""))
        if not local_log_file:
            continue
        log_file = collection_dir / local_log_file
        documents = _extract_auto_explain_json_documents(_read_text(log_file))
        for plan_index, document in enumerate(documents, start=1):
            document_role = _auto_explain_document_role(document)
            output_dir.mkdir(parents=True, exist_ok=True)
            remote_sql_id = f"auto_explain_{_safe_file_stem(region or host_name)}_{plan_index:03d}"
            plan_file = output_dir / f"{remote_sql_id}.json"
            plan_file.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            plan_records.append(
                {
                    "host_name": host_name,
                    "region": region,
                    "remote_sql_id": remote_sql_id,
                    "plan_file": plan_file,
                    "document_role": document_role,
                    "log_file": log_file,
                    "query_text": str(document.get("Query Text", "")),
                    "plan_file_rel": _rel(root, plan_file),
                    "log_file_rel": _rel(root, log_file),
                }
            )
    return plan_records


def _auto_explain_document_role(document: dict[str, Any]) -> str:
    root = _first_plan_node(document)
    query_text = str(document.get("Query Text", "")).lstrip().upper()
    root_node_type = str(root.get("Node Type", "")) if root else ""
    custom_provider = str(root.get("Custom Plan Provider", "")) if root else ""
    if query_text.startswith("EXPLAIN "):
        return "regional_diagnostic_explain"
    if query_text.startswith("DECLARE "):
        return "regional_remote_query"
    if root_node_type == "Custom Scan" and "Citus" in custom_provider:
        return "regional_remote_query"
    return "regional_internal_statement"


def _citus_text_plan_summary(explain_text: str) -> dict[str, Any]:
    lower = explain_text.lower()
    map_merge_count = explain_text.count("MapMergeJob")
    map_task_counts = [
        int(match.group(1)) for match in re.finditer(r"\bMap Task Count:\s*([0-9]+)", explain_text)
    ]
    merge_task_counts = [
        int(match.group(1))
        for match in re.finditer(r"\bMerge Task Count:\s*([0-9]+)", explain_text)
    ]
    top_task_counts = [
        int(match.group(1))
        for match in re.finditer(r"^\s*Task Count:\s*([0-9]+)", explain_text, flags=re.MULTILINE)
    ]
    top_task_count = top_task_counts[0] if top_task_counts else ""
    map_task_sum = sum(map_task_counts)
    merge_task_sum = sum(merge_task_counts)
    repartition = "re-partition quer" in lower or map_merge_count > 0
    return {
        "citus_top_task_count": top_task_count,
        "citus_map_merge_job_count": map_merge_count if map_merge_count else "",
        "citus_dependent_map_task_count_sum": map_task_sum if map_task_sum else "",
        "citus_dependent_merge_task_count_sum": merge_task_sum if merge_task_sum else "",
        "citus_repartition_fanout_ratio": (map_task_sum / top_task_count)
        if isinstance(top_task_count, int) and top_task_count > 0 and map_task_sum
        else "",
        "citus_repartition_query": "true" if repartition else "false",
        "citus_tasks_shown_none": "true" if "Tasks Shown: None" in explain_text else "false",
        "citus_plan_locality_class": "repartition_mapmerge" if repartition else "",
    }


def _sql_normalized(value: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", " ", value, flags=re.DOTALL)
    without_line_comments = re.sub(r"--[^\n\r]*", " ", without_block_comments)
    without_strings = re.sub(r"'(?:''|[^'])*'", "?", without_line_comments)
    without_dollar_strings = re.sub(
        r"\$[A-Za-z_][A-Za-z_0-9]*\$.*?\$[A-Za-z_][A-Za-z_0-9]*\$",
        "?",
        without_strings,
        flags=re.DOTALL,
    )
    without_numbers = re.sub(r"\b\d+(?:\.\d+)?\b", "?", without_dollar_strings)
    return re.sub(r"\s+", " ", without_numbers).strip().lower()


def _sql_hashes(query_sql_file: Path, source_sql_file: str | None) -> dict[str, str]:
    rendered_sql = _read_text(query_sql_file)
    if not rendered_sql and source_sql_file:
        rendered_sql = _read_text(_path_from(Path.cwd(), source_sql_file))
    if not rendered_sql:
        return {"rendered_sql_hash": "", "sql_normalized_hash": ""}
    return {
        "rendered_sql_hash": _hash_text(rendered_sql),
        "sql_normalized_hash": _hash_text(_sql_normalized(rendered_sql)),
    }


def _sql_for_clause_analysis(value: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", " ", value, flags=re.DOTALL)
    without_line_comments = re.sub(r"--[^\n\r]*", " ", without_block_comments)
    without_strings = re.sub(r"'(?:''|[^'])*'", "?", without_line_comments)
    return re.sub(r"\s+", " ", without_strings).strip().lower()


def _clause(sql: str, start_keyword: str, end_keywords: tuple[str, ...]) -> str:
    match = re.search(rf"\b{re.escape(start_keyword)}\b", sql)
    if not match:
        return ""
    start = match.end()
    end = len(sql)
    for keyword in end_keywords:
        keyword_match = re.search(rf"\b{re.escape(keyword)}\b", sql[start:])
        if keyword_match:
            end = min(end, start + keyword_match.start())
    return sql[start:end]


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _distribution_key_usage(
    *,
    sql_text: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    distribution_key: str = "tenant_id",
) -> dict[str, str]:
    sql = _sql_for_clause_analysis(sql_text)
    key = distribution_key.lower()
    where_clause = _clause(sql, "where", ("group by", "order by", "limit", "union"))
    group_clause = _clause(sql, "group by", ("order by", "limit", "union"))
    order_clause = _clause(sql, "order by", ("limit", "union"))
    join_clauses = " ".join(
        match.group(1)
        for match in re.finditer(
            (
                r"\bjoin\b\s+.+?\bon\b\s+(.+?)"
                r"(?=\bjoin\b|\bwhere\b|\bgroup by\b|\border by\b|\blimit\b|\bunion\b|$)"
            ),
            sql,
        )
    )
    tenant_filter_present = bool(
        re.search(rf"(?:\b\w+\.)?\b{re.escape(key)}\b\s*(=|in\b|any\b)", where_clause)
    )
    single_tenant_scope = bool(
        re.search(rf"(?:\b\w+\.)?\b{re.escape(key)}\b\s*=", where_clause)
        or ("tenant_id" in params and params.get("tenant_id") not in ("", None))
    )
    result = {
        "distribution_key": distribution_key,
        "filter_uses_distribution_key": _bool_text(key in where_clause),
        "join_uses_distribution_key": _bool_text(key in join_clauses),
        "group_by_uses_distribution_key": _bool_text(key in group_clause),
        "order_by_uses_distribution_key": _bool_text(key in order_clause),
        "tenant_filter_present": _bool_text(tenant_filter_present),
        "single_tenant_scope": _bool_text(single_tenant_scope),
        "multi_tenant_scope": _bool_text(not single_tenant_scope),
        "distribution_key_usage_source": "sql_heuristic",
    }
    override = metadata.get("distribution_key_usage", {})
    if isinstance(override, str) and override.strip():
        try:
            decoded_override = json.loads(override)
        except json.JSONDecodeError:
            decoded_override = {}
        override = decoded_override if isinstance(decoded_override, dict) else {}
    if isinstance(override, dict):
        for key_name in (
            "distribution_key",
            "filter_uses_distribution_key",
            "join_uses_distribution_key",
            "group_by_uses_distribution_key",
            "order_by_uses_distribution_key",
            "tenant_filter_present",
            "single_tenant_scope",
            "multi_tenant_scope",
        ):
            if key_name in override:
                value = override[key_name]
                result[key_name] = _bool_text(value) if isinstance(value, bool) else str(value)
        if override:
            result["distribution_key_usage_source"] = "metadata_override"
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


def _corpus_cell_rows(
    *,
    query_sweep_id: str,
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
                "query_sweep_id": query_sweep_id,
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
                "runtime_sensitivity": row.get("runtime_sensitivity", ""),
                "required_dataset_capabilities": row.get("required_dataset_capabilities", ""),
                "intervention_roles": row.get("intervention_roles", ""),
                "_template_ids": set(),
                "_instance_ids": set(),
                "_query_run_ids": set(),
            },
        )
        cell["_template_ids"].add(str(row.get("template_id", "")))
        cell["_instance_ids"].add(str(row.get("instance_id", "")))
        cell["_query_run_ids"].add(str(row.get("query_run_id", "")))

    result: list[dict[str, Any]] = []
    for cell in cells.values():
        result.append(
            {key: value for key, value in cell.items() if not key.startswith("_")}
            | {
                "template_ids": ",".join(sorted(cell["_template_ids"] - {""})),
                "instance_ids": ",".join(sorted(cell["_instance_ids"] - {""})),
                "query_run_count": len(cell["_query_run_ids"] - {""}),
            }
        )
    return sorted(result, key=lambda item: str(item["corpus_cell_id"]))


def _feature_schema_source() -> Path | None:
    candidates = [
        Path(__file__).resolve().parents[3] / "docs" / "feature_schema.yml",
        Path.cwd() / "docs" / "feature_schema.yml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _write_feature_schema_sidecar(out_dir: Path) -> str:
    source = _feature_schema_source()
    if source is None:
        return ""
    target = out_dir / "feature_schema.yml"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target.name


def _rel(root: Path, path: Path | str | None) -> str:
    if path is None:
        return ""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(candidate)


def _path_from(base: Path, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate


def _load_bindings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = _load_json(path)
    return {
        "psql_variables": value.get("psql_variables", {}),
        "pg_options": value.get("pg_options", {}),
        "sql_parameterization": value.get("sql_parameterization", ""),
        "raw_psql_variables": value.get("raw_psql_variables", []),
        "raw_pg_options": value.get("raw_pg_options", []),
        "execution_metadata": value.get("execution_metadata", {}),
    }


def _first_node_artifact(
    collection_dir: Path,
    collection_manifest: dict[str, Any],
) -> tuple[str, Path | None, dict[str, Any]]:
    coordinator = str(collection_manifest.get("coordinator", ""))
    artifact = collection_manifest.get("local_artifacts", {}).get(coordinator)
    if not artifact:
        return coordinator, None, {}
    node_dir = collection_dir / str(artifact)
    manifest_file = node_dir / "execution_manifest.json"
    remote_manifest = _load_json(manifest_file) if manifest_file.exists() else {}
    return coordinator, node_dir, remote_manifest


def _cpu_counter_pct(summary: dict[str, Any], counter: str) -> float | str:
    direct_value = summary.get(f"cpu_{counter}_pct")
    if direct_value not in ("", None):
        return float(direct_value)

    first_cpu = summary.get("first_sample", {}).get("cpu", {})
    last_cpu = summary.get("last_sample", {}).get("cpu", {})
    if not isinstance(first_cpu, dict) or not isinstance(last_cpu, dict):
        return ""
    keys = set(first_cpu) & set(last_cpu)
    if counter not in keys:
        return ""
    deltas = {
        key: max(0, int(last_cpu[key]) - int(first_cpu[key]))
        for key in keys
    }
    total = sum(deltas.values())
    if total == 0:
        return ""
    return 100.0 * deltas[counter] / total


def _os_network_summary(
    collection_dir: Path,
    collection_manifest: dict[str, Any],
) -> dict[str, Any]:
    node_rows: list[dict[str, Any]] = []
    artifacts = collection_manifest.get("local_artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
    clock_calibrations = collection_manifest.get(
        "node_clock_calibrations",
        {},
    )
    if not isinstance(clock_calibrations, dict):
        clock_calibrations = {}
    for node_name, artifact in sorted(artifacts.items()):
        metrics_dir = collection_dir / str(artifact) / "metrics"
        query_summary_path = metrics_dir / "os_query_summary.json"
        envelope_summary_path = metrics_dir / "os_summary.json"
        summary_path = (
            query_summary_path
            if query_summary_path.exists()
            else envelope_summary_path
        )
        if not summary_path.exists():
            continue
        summary = _load_json(summary_path)
        net_delta = summary.get("net_delta", {})
        if not isinstance(net_delta, dict):
            net_delta = {}
        rx_bytes = 0
        tx_bytes = 0
        rx_packets = 0
        tx_packets = 0
        rx_dropped = 0
        tx_dropped = 0
        rx_errors = 0
        tx_errors = 0
        for values in net_delta.values():
            if not isinstance(values, dict):
                continue
            rx_bytes += int(values.get("rx_bytes", 0) or 0)
            tx_bytes += int(values.get("tx_bytes", 0) or 0)
            rx_packets += int(values.get("rx_packets", 0) or 0)
            tx_packets += int(values.get("tx_packets", 0) or 0)
            rx_dropped += int(values.get("rx_dropped", 0) or 0)
            tx_dropped += int(values.get("tx_dropped", 0) or 0)
            rx_errors += int(values.get("rx_errors", 0) or 0)
            tx_errors += int(values.get("tx_errors", 0) or 0)
        tcp_delta = summary.get("tcp_delta", {})
        if not isinstance(tcp_delta, dict):
            tcp_delta = {}
        disk_delta = summary.get("disk_delta", {})
        if not isinstance(disk_delta, dict):
            disk_delta = {}
        disk_read_bytes = sum(
            int(values.get("read_bytes", 0) or 0)
            for values in disk_delta.values()
            if isinstance(values, dict)
        )
        disk_written_bytes = sum(
            int(values.get("written_bytes", 0) or 0)
            for values in disk_delta.values()
            if isinstance(values, dict)
        )
        alignment = summary.get("alignment", {})
        if not isinstance(alignment, dict):
            alignment = {}
        mem = summary.get("mem", {})
        if not isinstance(mem, dict):
            mem = {}
        clock_calibration = clock_calibrations.get(node_name, {})
        if not isinstance(clock_calibration, dict):
            clock_calibration = {}
        sampling_alignment_status = str(alignment.get("status", ""))
        effective_alignment_status = sampling_alignment_status
        clock_uncertainty = clock_calibration.get(
            "uncertainty_seconds",
            "",
        )
        median_sample_interval = alignment.get(
            "median_sample_interval_seconds",
            "",
        )
        if (
            sampling_alignment_status in {"high", "medium"}
            and clock_uncertainty not in ("", None)
            and median_sample_interval not in ("", None, 0)
        ):
            uncertainty_ratio = float(clock_uncertainty) / float(
                median_sample_interval
            )
            if uncertainty_ratio > 2:
                effective_alignment_status = "low"
            elif (
                uncertainty_ratio > 0.5
                and sampling_alignment_status == "high"
            ):
                effective_alignment_status = "medium"
        node_rows.append(
            {
                "node_name": str(node_name),
                "node_role": (
                    "worker"
                    if "-worker-" in str(node_name)
                    else "coordinator"
                    if "-coord-" in str(node_name)
                    else "analytics"
                    if "-analytics-" in str(node_name)
                    else "other"
                ),
                "logical_region": str(node_name).split("-", 1)[0],
                "rx_bytes": rx_bytes,
                "tx_bytes": tx_bytes,
                "rx_packets": rx_packets,
                "tx_packets": tx_packets,
                "rx_dropped": rx_dropped,
                "tx_dropped": tx_dropped,
                "rx_errors": rx_errors,
                "tx_errors": tx_errors,
                "tcp_retrans_segs": int(tcp_delta.get("retrans_segs", 0) or 0),
                "tcp_timeouts": int(tcp_delta.get("timeouts", 0) or 0),
                "cpu_busy_pct": summary.get("cpu_busy_pct", ""),
                "cpu_steal_pct": _cpu_counter_pct(summary, "steal"),
                "sample_count": int(summary.get("sample_count", 0) or 0),
                "raw_sample_count": int(
                    summary.get("raw_sample_count", 0) or 0
                ),
                "summary_scope": summary.get(
                    "summary_scope",
                    "capture_envelope_legacy",
                ),
                "alignment": alignment,
                "sampling_alignment_status": sampling_alignment_status,
                "alignment_status": effective_alignment_status,
                "alignment_coverage": alignment.get("coverage", ""),
                "query_duration_seconds": alignment.get(
                    "query_duration_seconds",
                    "",
                ),
                "query_bracket_duration_seconds": summary.get(
                    "duration_seconds",
                    "",
                ),
                "query_padding_seconds": alignment.get(
                    "total_padding_seconds",
                    "",
                ),
                "clock_calibration_status": clock_calibration.get(
                    "status",
                    "",
                ),
                "clock_offset_seconds": clock_calibration.get(
                    "remote_minus_controller_seconds",
                    "",
                ),
                "clock_uncertainty_seconds": clock_calibration.get(
                    "uncertainty_seconds",
                    "",
                ),
                "telemetry_window": summary.get("telemetry_window", {}),
                "net_delta_by_interface": net_delta,
                "tcp_delta": tcp_delta,
                "qdisc_before": summary.get("qdisc_before", []),
                "qdisc_after": summary.get("qdisc_after", []),
                "mem": mem,
                "disk_delta": disk_delta,
                "disk_read_bytes": disk_read_bytes,
                "disk_written_bytes": disk_written_bytes,
            }
        )

    numeric_cpu = [
        float(row["cpu_busy_pct"]) for row in node_rows if row["cpu_busy_pct"] not in ("", None)
    ]
    numeric_cpu_steal = [
        float(row["cpu_steal_pct"])
        for row in node_rows
        if row["cpu_steal_pct"] not in ("", None)
    ]
    coordinator_rows = [row for row in node_rows if "-coord-" in str(row["node_name"])]
    analytics_rows = [row for row in node_rows if "-analytics-" in str(row["node_name"])]
    worker_rows = [row for row in node_rows if row["node_role"] == "worker"]
    worker_rx_values = [float(row["rx_bytes"]) for row in worker_rows]
    worker_tx_values = [float(row["tx_bytes"]) for row in worker_rows]
    alignment_status_counts: dict[str, int] = {}
    for row in node_rows:
        status = str(row.get("alignment_status", "") or "legacy")
        alignment_status_counts[status] = (
            alignment_status_counts.get(status, 0) + 1
        )
    alignment_rank = {
        "high": 0,
        "medium": 1,
        "low": 2,
        "incomplete_coverage": 3,
        "insufficient_samples": 4,
        "legacy": 5,
    }
    worst_alignment = max(
        alignment_status_counts,
        key=lambda status: alignment_rank.get(status, 6),
        default="",
    )
    bracket_durations = [
        float(row["query_bracket_duration_seconds"])
        for row in node_rows
        if row["query_bracket_duration_seconds"] not in ("", None)
    ]
    query_paddings = [
        float(row["query_padding_seconds"])
        for row in node_rows
        if row["query_padding_seconds"] not in ("", None)
    ]
    clock_uncertainties = [
        float(row["clock_uncertainty_seconds"])
        for row in node_rows
        if row["clock_uncertainty_seconds"] not in ("", None)
    ]
    mem_peak_values = [
        int(row["mem"].get("max_used_bytes", 0) or 0)
        for row in node_rows
    ]
    mem_available_min_values = [
        int(row["mem"].get("min_available_bytes", 0) or 0)
        for row in node_rows
        if int(row["mem"].get("min_available_bytes", 0) or 0) > 0
    ]

    def coefficient_of_variation(values: list[float]) -> float | str:
        if not values:
            return ""
        mean = statistics.fmean(values)
        if mean <= 0:
            return 0.0
        return statistics.pstdev(values) / mean if len(values) > 1 else 0.0

    def maximum_share(values: list[float]) -> float | str:
        total = sum(values)
        return max(values) / total if values and total > 0 else ""

    worker_regions: dict[str, dict[str, int]] = {}
    for row in worker_rows:
        region = str(row["logical_region"])
        region_values = worker_regions.setdefault(
            region,
            {
                "worker_count": 0,
                "rx_bytes": 0,
                "tx_bytes": 0,
                "rx_packets": 0,
                "tx_packets": 0,
            },
        )
        region_values["worker_count"] += 1
        region_values["rx_bytes"] += int(row["rx_bytes"])
        region_values["tx_bytes"] += int(row["tx_bytes"])
        region_values["rx_packets"] += int(row["rx_packets"])
        region_values["tx_packets"] += int(row["tx_packets"])

    return {
        "os_sampled_node_count": len(node_rows),
        "os_sample_count_sum": sum(row["sample_count"] for row in node_rows),
        "os_raw_sample_count_sum": sum(
            row["raw_sample_count"] for row in node_rows
        ),
        "os_query_aligned_node_count": sum(
            row["summary_scope"] == "query_bracket"
            for row in node_rows
        ),
        "os_query_alignment_coverage_count": sum(
            row["alignment_coverage"] is True
            for row in node_rows
        ),
        "os_query_alignment_worst_status": worst_alignment,
        "os_query_alignment_status_counts_json": _json_text(
            alignment_status_counts
        ),
        "os_query_bracket_duration_seconds_mean": (
            statistics.fmean(bracket_durations)
            if bracket_durations
            else ""
        ),
        "os_query_bracket_duration_seconds_max": (
            max(bracket_durations) if bracket_durations else ""
        ),
        "os_query_padding_seconds_max": (
            max(query_paddings) if query_paddings else ""
        ),
        "os_clock_calibrated_node_count": sum(
            row["clock_calibration_status"] == "available"
            for row in node_rows
        ),
        "os_clock_uncertainty_seconds_max": (
            max(clock_uncertainties) if clock_uncertainties else ""
        ),
        "os_cpu_busy_pct_mean": (statistics.fmean(numeric_cpu) if numeric_cpu else ""),
        "os_cpu_busy_pct_max": max(numeric_cpu) if numeric_cpu else "",
        "os_cpu_steal_pct_mean": (
            statistics.fmean(numeric_cpu_steal) if numeric_cpu_steal else ""
        ),
        "os_cpu_steal_pct_max": (
            max(numeric_cpu_steal) if numeric_cpu_steal else ""
        ),
        "os_mem_used_peak_bytes_max": (
            max(mem_peak_values) if mem_peak_values else ""
        ),
        "os_mem_available_bytes_min": (
            min(mem_available_min_values)
            if mem_available_min_values
            else ""
        ),
        "os_disk_read_bytes_sum": sum(
            row["disk_read_bytes"] for row in node_rows
        ),
        "os_disk_written_bytes_sum": sum(
            row["disk_written_bytes"] for row in node_rows
        ),
        "os_net_rx_bytes_sum": sum(row["rx_bytes"] for row in node_rows),
        "os_net_tx_bytes_sum": sum(row["tx_bytes"] for row in node_rows),
        "os_net_rx_packets_sum": sum(row["rx_packets"] for row in node_rows),
        "os_net_tx_packets_sum": sum(row["tx_packets"] for row in node_rows),
        "os_net_rx_dropped_sum": sum(row["rx_dropped"] for row in node_rows),
        "os_net_tx_dropped_sum": sum(row["tx_dropped"] for row in node_rows),
        "os_net_rx_errors_sum": sum(row["rx_errors"] for row in node_rows),
        "os_net_tx_errors_sum": sum(row["tx_errors"] for row in node_rows),
        "os_tcp_retrans_segs_sum": sum(row["tcp_retrans_segs"] for row in node_rows),
        "os_tcp_timeouts_sum": sum(row["tcp_timeouts"] for row in node_rows),
        "regional_coordinator_tx_bytes_sum": sum(row["tx_bytes"] for row in coordinator_rows),
        "regional_coordinator_tx_packets_sum": sum(row["tx_packets"] for row in coordinator_rows),
        "analytics_rx_bytes_sum": sum(row["rx_bytes"] for row in analytics_rows),
        "analytics_rx_packets_sum": sum(row["rx_packets"] for row in analytics_rows),
        "worker_rx_bytes_sum": sum(row["rx_bytes"] for row in worker_rows),
        "worker_tx_bytes_sum": sum(row["tx_bytes"] for row in worker_rows),
        "worker_rx_bytes_cv": coefficient_of_variation(worker_rx_values),
        "worker_tx_bytes_cv": coefficient_of_variation(worker_tx_values),
        "worker_rx_bytes_max_share": maximum_share(worker_rx_values),
        "worker_tx_bytes_max_share": maximum_share(worker_tx_values),
        "worker_network_regions_json": _json_text(worker_regions),
        "os_network_nodes_json": _json_text(node_rows),
    }


def _load_remote_edge_context(
    collection_dir: Path,
    collection_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    contract = collection_manifest.get("remote_edge_context", {})
    if not isinstance(contract, dict):
        return []
    artifact = str(contract.get("artifact", "") or "")
    if not artifact:
        return []
    path = collection_dir / artifact
    if not path.exists():
        return []
    payload = _load_json(path)
    edges = payload.get("edges", [])
    return [row for row in edges if isinstance(row, dict)] if isinstance(edges, list) else []


def _json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [row for row in parsed if isinstance(row, dict)] if isinstance(parsed, list) else []


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _interface_metric(
    node: dict[str, Any],
    *,
    device: str,
    metric: str,
) -> Any:
    interfaces = node.get("net_delta_by_interface", {})
    if not isinstance(interfaces, dict):
        return ""
    values = interfaces.get(device, {}) if device else {}
    if not isinstance(values, dict):
        return ""
    return values.get(metric, "")


def _qdisc_metric_delta(
    node: dict[str, Any],
    *,
    metric: str,
) -> Any:
    def total(rows: Any) -> float | None:
        if not isinstance(rows, list):
            return None
        selected = [
            row
            for row in rows
            if isinstance(row, dict)
            and (
                str(row.get("handle", "")) == "30:"
                or str(row.get("kind", "")) == "netem"
            )
        ]
        if not selected:
            return None
        values: list[float] = []
        for row in selected:
            value = _float_or_none(row.get(metric))
            if value is not None:
                values.append(value)
        return sum(values) if values else None

    before = total(node.get("qdisc_before"))
    after = total(node.get("qdisc_after"))
    if before is None or after is None:
        return ""
    return max(0.0, after - before)


def _remote_edge_observation_rows(
    *,
    query_sweep_id: str,
    query_row: dict[str, Any],
    edge_context_rows: list[dict[str, Any]],
    plan_nodes: list[dict[str, Any]],
    region_fragments: list[dict[str, Any]],
    remote_plans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    query_run_id = str(query_row.get("query_run_id", ""))
    context_by_region = {
        str(row.get("source_cluster_id", "")): row
        for row in edge_context_rows
        if row.get("source_cluster_id")
    }
    os_nodes = {
        str(row.get("node_name", "")): row
        for row in _json_list(query_row.get("os_network_nodes_json", ""))
    }
    foreign_scans_by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in plan_nodes:
        if node.get("plan_scope") != "main" or node.get("node_type") != "Foreign Scan":
            continue
        schema_name = str(node.get("schema_name", "") or node.get("fdw_schema", ""))
        relations_text = str(node.get("relations_text", ""))
        match = re.match(r"fdw_([A-Za-z0-9_-]+)$", schema_name) or re.search(
            r"\bfdw_([A-Za-z0-9_-]+)\.",
            relations_text,
        )
        if match:
            foreign_scans_by_region[match.group(1)].append(node)

    fragments_by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in region_fragments:
        region = str(row.get("region_id", "") or row.get("cluster_id", ""))
        if region:
            fragments_by_region[region].append(row)

    remote_plans_by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in remote_plans:
        region = str(row.get("fdw_region", ""))
        if region:
            remote_plans_by_region[region].append(row)

    regions = sorted(
        set(context_by_region)
        | set(foreign_scans_by_region)
        | set(fragments_by_region)
        | set(remote_plans_by_region)
    )
    fetch_size = _float_or_none(query_row.get("fetch_size"))
    elapsed_seconds = _float_or_none(query_row.get("elapsed_seconds"))
    network_profile = _json_mapping(query_row.get("network_profile_json", ""))
    targeted_regions = {
        str(value)
        for value in network_profile.get("target_region_ids", [])
        if str(value)
    }
    intervention_active = any(
        (_float_or_none(network_profile.get(field)) or 0.0) > 0.0
        for field in (
            "configured_delay_ms",
            "configured_jitter_ms",
            "configured_loss_percent",
            "configured_bandwidth_mbit",
        )
    )
    result: list[dict[str, Any]] = []
    for region in regions:
        context = context_by_region.get(region, {})
        before = context.get("before", {}) if isinstance(context.get("before"), dict) else {}
        after = context.get("after", {}) if isinstance(context.get("after"), dict) else {}
        source_node_name = str(context.get("source_node", "") or f"{region}-coord-1")
        source_node = os_nodes.get(source_node_name, {})
        destination_node_name = str(context.get("destination_gac_id", ""))
        destination_node = os_nodes.get(destination_node_name, {})
        route_device = str(
            before.get("route_device", "") or after.get("route_device", "")
        )
        scans = foreign_scans_by_region.get(region, [])
        fragments = fragments_by_region.get(region, [])
        plans = remote_plans_by_region.get(region, [])

        scan_rows = [
            value
            for value in (_float_or_none(row.get("actual_rows")) for row in scans)
            if value is not None
        ]
        scan_times = [
            value
            for value in (_float_or_none(row.get("actual_total_time")) for row in scans)
            if value is not None
        ]
        scan_byte_values = []
        for row in scans:
            rows_value = _float_or_none(row.get("actual_rows"))
            width_value = _float_or_none(row.get("plan_width"))
            if rows_value is not None and width_value is not None:
                scan_byte_values.append(rows_value * width_value)
        fragment_rows = [
            value
            for value in (_float_or_none(row.get("remote_actual_rows")) for row in fragments)
            if value is not None
        ]
        fragment_times = [
            value
            for value in (
                _float_or_none(row.get("remote_actual_total_time_ms")) for row in fragments
            )
            if value is not None
        ]
        fragment_bytes = [
            value
            for value in (
                _float_or_none(row.get("remote_tuple_bytes_proxy")) for row in fragments
            )
            if value is not None
        ]
        remote_rows = sum(scan_rows) if scan_rows else (sum(fragment_rows) if fragment_rows else "")
        remote_bytes_proxy = (
            sum(scan_byte_values)
            if scan_byte_values
            else sum(fragment_bytes)
            if fragment_bytes
            else ""
        )
        estimated_fetch_cycles: float | str = ""
        if fetch_size is not None and fetch_size > 0:
            cycle_inputs = scan_rows or fragment_rows
            if cycle_inputs:
                estimated_fetch_cycles = sum(
                    math.ceil(value / fetch_size) for value in cycle_inputs
                )

        source_tx_bytes = _interface_metric(
            source_node,
            device=route_device,
            metric="tx_bytes",
        )
        source_tx_packets = _interface_metric(
            source_node,
            device=route_device,
            metric="tx_packets",
        )
        destination_rx_bytes = destination_node.get("rx_bytes", "")
        source_tx_bps: float | str = ""
        source_tx_float = _float_or_none(source_tx_bytes)
        if source_tx_float is not None and elapsed_seconds is not None and elapsed_seconds > 0:
            source_tx_bps = source_tx_float * 8.0 / elapsed_seconds
        payload_to_tx_ratio: float | str = ""
        remote_bytes_float = _float_or_none(remote_bytes_proxy)
        if (
            remote_bytes_float is not None
            and source_tx_float is not None
            and source_tx_float > 0
        ):
            payload_to_tx_ratio = remote_bytes_float / source_tx_float

        plan_fingerprints = sorted(
            {
                str(row.get("remote_plan_fingerprint", "") or row.get("plan_fingerprint", ""))
                for row in plans
                if row.get("remote_plan_fingerprint") or row.get("plan_fingerprint")
            }
        )
        remote_sql_texts = sorted(
            {
                _sql_normalized(str(row.get("remote_sql_text", "")))
                for row in scans
                if str(row.get("remote_sql_text", "")).strip()
            }
        )
        plan_widths = [
            value
            for value in (
                _float_or_none(row.get("plan_width")) for row in scans
            )
            if value is not None
        ]
        foreign_schemas = sorted(
            {
                str(row.get("schema_name", "") or f"fdw_{region}")
                for row in scans
            }
        )
        before_rtt = _float_or_none(before.get("rtt_median_ms"))
        after_rtt = _float_or_none(after.get("rtt_median_ms"))
        rtt_values = [value for value in (before_rtt, after_rtt) if value is not None]
        before_loss = _float_or_none(before.get("packet_loss_percent"))
        after_loss = _float_or_none(after.get("packet_loss_percent"))
        loss_values = [value for value in (before_loss, after_loss) if value is not None]
        plan_time = sum(fragment_times) if fragment_times else ""
        foreign_time = sum(scan_times) if scan_times else ""
        boundary_time_proxy: float | str = ""
        if foreign_time != "" and plan_time != "":
            boundary_time_proxy = float(foreign_time) - float(plan_time)

        evidence_available = bool(scans or fragments or plans)
        context_available = bool(context)
        intervention_targeted = intervention_active and (
            not targeted_regions or region in targeted_regions
        )

        def edge_configured_value(
            field: str,
            *,
            targeted: bool = intervention_targeted,
        ) -> Any:
            if not targeted:
                return 0
            return _first_value(
                network_profile.get(field),
                query_row.get(
                    {
                        "configured_delay_ms": "configured_latency_ms",
                        "configured_jitter_ms": "configured_jitter_ms",
                        "configured_loss_percent": "configured_loss_percent",
                        "configured_bandwidth_mbit": "configured_bandwidth_mbit",
                    }[field],
                    "",
                ),
                "",
            )

        result.append(
            {
                "query_sweep_id": query_sweep_id,
                "query_run_id": query_run_id,
                "instance_id": query_row.get("instance_id", ""),
                "template_id": query_row.get("template_id", ""),
                "edge_id": str(
                    context.get("edge_id", "")
                    or f"{region}->{destination_node_name or 'gac'}"
                ),
                "source_cluster_id": region,
                "destination_gac_id": destination_node_name,
                "source_node": source_node_name,
                "destination_node": destination_node_name,
                "foreign_schema_id": ",".join(foreign_schemas),
                "foreign_server_id": f"{region}_citus" if evidence_available else "",
                "remote_sql_fingerprint": (
                    _hash_text(_json_text(remote_sql_texts))
                    if remote_sql_texts
                    else ""
                ),
                "remote_sql_count": len(remote_sql_texts),
                "remote_plan_fingerprints_json": _json_text(plan_fingerprints),
                "remote_plan_fingerprint_count": len(plan_fingerprints),
                "regional_plan_count": len(plans),
                "remote_rows": remote_rows,
                "remote_tuple_width": (
                    max(plan_widths) if plan_widths else ""
                ),
                "remote_bytes_proxy": remote_bytes_proxy,
                "foreign_scan_time_ms_sum": foreign_time,
                "regional_plan_time_ms_sum": plan_time,
                "foreign_scan_minus_regional_time_ms_proxy": boundary_time_proxy,
                "fetch_size": query_row.get("fetch_size", ""),
                "estimated_fetch_cycles": estimated_fetch_cycles,
                "rtt_before_median_ms": before.get("rtt_median_ms", ""),
                "rtt_after_median_ms": after.get("rtt_median_ms", ""),
                "rtt_context_median_ms": (
                    statistics.median(rtt_values) if rtt_values else ""
                ),
                "rtt_before_max_ms": before.get("rtt_max_ms", ""),
                "rtt_after_max_ms": after.get("rtt_max_ms", ""),
                "rtt_context_max_ms": (
                    max(
                        value
                        for value in (
                            _float_or_none(before.get("rtt_max_ms")),
                            _float_or_none(after.get("rtt_max_ms")),
                        )
                        if value is not None
                    )
                    if before.get("rtt_max_ms", "") != ""
                    or after.get("rtt_max_ms", "") != ""
                    else ""
                ),
                "rtt_before_mdev_ms": before.get("rtt_mdev_ms", ""),
                "rtt_after_mdev_ms": after.get("rtt_mdev_ms", ""),
                "packet_loss_context_percent_max": max(loss_values) if loss_values else "",
                "rtt_probe_packets_received_min": (
                    min(
                        int(before.get("ping_packets_received", 0) or 0),
                        int(after.get("ping_packets_received", 0) or 0),
                    )
                    if context
                    else ""
                ),
                "route_device": route_device,
                "route_source_ip": (
                    before.get("route_source_ip", "")
                    or after.get("route_source_ip", "")
                ),
                "query_window_source_tx_bytes": source_tx_bytes,
                "query_window_source_tx_packets": source_tx_packets,
                "query_window_destination_rx_bytes_shared": destination_rx_bytes,
                "query_window_source_tx_bps": source_tx_bps,
                "remote_payload_to_source_tx_ratio": payload_to_tx_ratio,
                "query_window_qdisc_bytes": _qdisc_metric_delta(
                    source_node,
                    metric="bytes",
                ),
                "query_window_qdisc_packets": _qdisc_metric_delta(
                    source_node,
                    metric="packets",
                ),
                "query_window_qdisc_drops": _qdisc_metric_delta(
                    source_node,
                    metric="drops",
                ),
                "query_window_qdisc_overlimits": _qdisc_metric_delta(
                    source_node,
                    metric="overlimits",
                ),
                "tcp_retrans_delta_node_global": source_node.get(
                    "tcp_retrans_segs",
                    "",
                ),
                "configured_network_profile": query_row.get(
                    "network_profile_id",
                    "",
                ),
                "network_intervention_targeted": (
                    "true" if intervention_targeted else "false"
                ),
                "configured_delay_ms": edge_configured_value(
                    "configured_delay_ms"
                ),
                "configured_jitter_ms": edge_configured_value(
                    "configured_jitter_ms"
                ),
                "configured_loss_percent": edge_configured_value(
                    "configured_loss_percent"
                ),
                "configured_bandwidth_mbit": edge_configured_value(
                    "configured_bandwidth_mbit"
                ),
                "network_profile_json": query_row.get("network_profile_json", ""),
                "measurement_quality": (
                    "edge_context_plus_query_window_node_interface"
                    if context_available and source_node
                    else "cross_layer_plan_only"
                    if evidence_available
                    else "missing"
                ),
                "availability_status": (
                    "available"
                    if evidence_available and context_available and source_node
                    else "partial"
                    if evidence_available or context_available
                    else "missing"
                ),
                "traffic_counter_scope": "source_node_route_interface_query_window",
                "tcp_counter_scope": "source_node_global_query_window",
                "destination_rx_scope": "gac_node_global_shared_across_edges",
                "rtt_scope": "before_after_context_not_query_socket",
            }
        )
    return result


def _result_signature_summary(
    collection_dir: Path,
    collection_manifest: dict[str, Any],
) -> dict[str, Any]:
    signature = collection_manifest.get("result_signature", {})
    if not isinstance(signature, dict):
        signature = {}
    relative_path = str(signature.get("artifact", ""))
    signature_path = collection_dir / relative_path if relative_path else None
    payload = (
        _load_json(signature_path) if signature_path is not None and signature_path.exists() else {}
    )
    return {
        "result_signature_status": signature.get("status", ""),
        "result_signature_file": (
            _rel(collection_dir, signature_path)
            if signature_path is not None and signature_path.exists()
            else ""
        ),
        "result_row_count": payload.get("row_count", ""),
        "result_output_byte_count": payload.get("output_byte_count", ""),
        "result_multiset_sha256": payload.get("multiset_sha256", ""),
        "result_ordered_sha256": payload.get("ordered_sha256", ""),
        "result_signature_elapsed_seconds": payload.get("elapsed_seconds", ""),
        "database_result_rows_stored": payload.get(
            "database_result_rows_stored",
            False,
        ),
    }


def _plan_summary(plan_file: Path | None) -> dict[str, Any]:
    if plan_file is None or not plan_file.exists():
        return {
            "plan_node_count": "",
            "has_foreign_scan": "",
            "has_remote_sql": "",
            "plan_fingerprint": "",
            "plan_parse_error": "plan file missing",
        }
    try:
        value = _load_json_value(plan_file)
        rows = extract_plan_rows(value)
        fingerprint = plan_fingerprint(value)
    except (json.JSONDecodeError, ValueError) as error:
        return {
            "plan_node_count": "",
            "has_foreign_scan": "",
            "has_remote_sql": "",
            "plan_fingerprint": "",
            "plan_parse_error": str(error),
        }
    raw = json.dumps(value)
    return {
        "plan_node_count": len(rows),
        "has_foreign_scan": any(row.get("node_type") == "Foreign Scan" for row in rows),
        "has_remote_sql": "Remote SQL" in raw,
        "plan_fingerprint": fingerprint,
        "plan_parse_error": "",
    }


def _buffer_audit_summary(plan_file: Path | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "shared_blks_hit_sum": "",
        "shared_blks_read_sum": "",
        "shared_hit_ratio": "",
        "temp_blks_read_sum": "",
        "temp_blks_written_sum": "",
    }
    if plan_file is None or not plan_file.exists():
        return result
    try:
        rows = extract_plan_rows(_load_json_value(plan_file))
    except (json.JSONDecodeError, ValueError):
        return result
    if not rows:
        return result

    def root_or_sum(key: str) -> float | None:
        root_value = _float_or_none(rows[0].get(key))
        if root_value is not None:
            return root_value
        values = [
            value for value in (_float_or_none(row.get(key)) for row in rows) if value is not None
        ]
        return sum(values) if values else None

    hit = root_or_sum("shared_hit_blocks")
    read = root_or_sum("shared_read_blocks")
    temp_read = root_or_sum("temp_read_blocks")
    temp_written = root_or_sum("temp_written_blocks")
    denominator = (hit or 0.0) + (read or 0.0)
    result.update(
        {
            "shared_blks_hit_sum": hit if hit is not None else "",
            "shared_blks_read_sum": read if read is not None else "",
            "shared_hit_ratio": (hit or 0.0) / denominator if denominator > 0 else "",
            "temp_blks_read_sum": temp_read if temp_read is not None else "",
            "temp_blks_written_sum": temp_written if temp_written is not None else "",
        }
    )
    return result


def _result_width_class(width: float | None) -> str:
    if width is None:
        return ""
    if width < 64:
        return "narrow"
    if width < 512:
        return "medium"
    if width < 2048:
        return "wide"
    return "very_wide"


def _estimate_bytes(rows: float | None, width: float | None) -> float | None:
    if rows is None or width is None:
        return None
    return rows * width


def _fan_in_width_summary(
    *,
    main_plan_file: Path | None,
    remote_plan_files: list[Path],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "main_root_plan_width": "",
        "foreign_scan_plan_width_sum": "",
        "foreign_scan_plan_width_max": "",
        "remote_root_plan_width_sum": "",
        "remote_root_plan_width_max": "",
        "estimated_result_bytes": "",
        "estimated_remote_output_bytes": "",
        "estimated_fanin_bytes": "",
        "result_width_class": "",
    }
    if main_plan_file is None or not main_plan_file.exists():
        return result

    try:
        main_rows = extract_plan_rows(_load_json_value(main_plan_file))
    except (json.JSONDecodeError, ValueError):
        return result
    if not main_rows:
        return result

    root = main_rows[0]
    root_width = _float_or_none(root.get("plan_width"))
    root_actual_rows = _float_or_none(root.get("actual_rows"))
    foreign_scan_nodes = [
        row for row in main_rows if str(row.get("node_type", "")) == "Foreign Scan"
    ]
    foreign_scan_widths = [
        width
        for width in (_float_or_none(row.get("plan_width")) for row in foreign_scan_nodes)
        if width is not None
    ]
    foreign_scan_bytes = [
        value
        for value in (
            _estimate_bytes(
                _float_or_none(row.get("actual_rows")),
                _float_or_none(row.get("plan_width")),
            )
            for row in foreign_scan_nodes
        )
        if value is not None
    ]

    remote_root_widths: list[float] = []
    remote_root_bytes: list[float] = []
    for remote_plan_file in remote_plan_files:
        if not remote_plan_file.exists():
            continue
        try:
            remote_rows = extract_plan_rows(_load_json_value(remote_plan_file))
        except (json.JSONDecodeError, ValueError):
            continue
        if not remote_rows:
            continue
        remote_root = remote_rows[0]
        remote_width = _float_or_none(remote_root.get("plan_width"))
        remote_actual_rows = _float_or_none(remote_root.get("actual_rows"))
        if remote_width is not None:
            remote_root_widths.append(remote_width)
        remote_bytes = _estimate_bytes(remote_actual_rows, remote_width)
        if remote_bytes is not None:
            remote_root_bytes.append(remote_bytes)

    result.update(
        {
            "main_root_plan_width": root_width if root_width is not None else "",
            "foreign_scan_plan_width_sum": sum(foreign_scan_widths) if foreign_scan_widths else "",
            "foreign_scan_plan_width_max": max(foreign_scan_widths) if foreign_scan_widths else "",
            "remote_root_plan_width_sum": sum(remote_root_widths) if remote_root_widths else "",
            "remote_root_plan_width_max": max(remote_root_widths) if remote_root_widths else "",
            "estimated_result_bytes": _estimate_bytes(root_actual_rows, root_width) or "",
            "estimated_remote_output_bytes": sum(remote_root_bytes) if remote_root_bytes else "",
            "estimated_fanin_bytes": sum(foreign_scan_bytes)
            if foreign_scan_bytes
            else (sum(remote_root_bytes) if remote_root_bytes else ""),
            "result_width_class": _result_width_class(root_width),
        }
    )
    return result


COORDINATOR_OPERATOR_CLASSES = {
    "sort": {"Sort", "Incremental Sort"},
    "aggregate": {
        "Aggregate",
        "Finalize Aggregate",
        "GroupAggregate",
        "HashAggregate",
        "MixedAggregate",
    },
    "join": {
        "Hash Join",
        "Merge Join",
        "Nested Loop",
        "Parallel Hash Join",
    },
    "unique": {"Unique"},
    "window": {"WindowAgg"},
    "limit": {"Limit"},
}
COORDINATOR_BLOCKING_CLASSES = {"sort", "aggregate", "unique", "window"}


def _plan_row_count(row: dict[str, Any]) -> float | None:
    actual_rows = _float_or_none(row.get("actual_rows"))
    if actual_rows is None:
        return None
    actual_loops = _float_or_none(row.get("actual_loops"))
    return actual_rows * (actual_loops if actual_loops is not None else 1.0)


def _plan_row_time_ms(row: dict[str, Any]) -> float | None:
    actual_time = _float_or_none(row.get("actual_total_time"))
    if actual_time is None:
        return None
    actual_loops = _float_or_none(row.get("actual_loops"))
    return actual_time * (actual_loops if actual_loops is not None else 1.0)


def _coordinator_pressure_summary(main_plan_file: Path | None) -> dict[str, Any]:
    """Summarize work performed by the main GAC/coordinator plan.

    Input-row sums are operator-work proxies. A row can be counted by multiple
    blocking stages, so these values must not be interpreted as unique tuples
    or network bytes.
    """

    result: dict[str, Any] = {
        "coordinator_main_plan_total_time_ms": "",
        "coordinator_foreign_scan_time_ms_sum": "",
        "coordinator_non_foreign_time_ms_proxy": "",
        "coordinator_non_foreign_time_share_proxy": "",
        "coordinator_fanin_rows": "",
        "coordinator_fanin_bytes_estimated": "",
        "coordinator_final_rows": "",
        "coordinator_final_bytes_estimated": "",
        "coordinator_blocking_operator_count": 0,
        "coordinator_blocking_input_rows_sum": "",
        "coordinator_blocking_input_rows_max": "",
        "coordinator_blocking_output_rows_sum": "",
        "coordinator_temp_read_blocks": "",
        "coordinator_temp_written_blocks": "",
        "coordinator_spill_present": "false",
        "coordinator_disk_sort_count": 0,
        "coordinator_sort_space_used_kb_max": "",
        "coordinator_hash_batches_max": "",
        "coordinator_hashagg_disk_usage_kb_max": "",
        "coordinator_peak_memory_usage_kb_max": "",
    }
    for class_name in COORDINATOR_OPERATOR_CLASSES:
        result.update(
            {
                f"coordinator_{class_name}_operator_count": 0,
                f"coordinator_{class_name}_input_rows_sum": "",
                f"coordinator_{class_name}_input_rows_max": "",
                f"coordinator_{class_name}_output_rows_sum": "",
                f"coordinator_{class_name}_time_ms_max": "",
            }
        )
    if main_plan_file is None or not main_plan_file.exists():
        return result

    try:
        rows = extract_plan_rows(_load_json_value(main_plan_file))
    except (json.JSONDecodeError, ValueError):
        return result
    if not rows:
        return result

    rows_by_parent: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        parent_id = row.get("parent_node_id")
        if parent_id in ("", None):
            continue
        try:
            rows_by_parent[int(parent_id)].append(row)
        except (TypeError, ValueError):
            continue

    root = rows[0]
    root_time = _plan_row_time_ms(root)
    root_rows = _plan_row_count(root)
    root_width = _float_or_none(root.get("plan_width"))
    foreign_scans = [row for row in rows if row.get("node_type") == "Foreign Scan"]
    foreign_times = [
        value
        for value in (_plan_row_time_ms(row) for row in foreign_scans)
        if value is not None
    ]
    foreign_rows = [
        value
        for value in (_plan_row_count(row) for row in foreign_scans)
        if value is not None
    ]
    fanin_bytes = [
        value
        for value in (
            _estimate_bytes(
                _plan_row_count(row),
                _float_or_none(row.get("plan_width")),
            )
            for row in foreign_scans
        )
        if value is not None
    ]

    if root_time is not None:
        result["coordinator_main_plan_total_time_ms"] = root_time
    if foreign_times:
        foreign_time_sum = sum(foreign_times)
        result["coordinator_foreign_scan_time_ms_sum"] = foreign_time_sum
        if root_time is not None and root_time > 0:
            non_foreign_time = max(root_time - foreign_time_sum, 0.0)
            result["coordinator_non_foreign_time_ms_proxy"] = non_foreign_time
            result["coordinator_non_foreign_time_share_proxy"] = (
                non_foreign_time / root_time
            )
    if foreign_rows:
        result["coordinator_fanin_rows"] = sum(foreign_rows)
    if fanin_bytes:
        result["coordinator_fanin_bytes_estimated"] = sum(fanin_bytes)
    if root_rows is not None:
        result["coordinator_final_rows"] = root_rows
    final_bytes = _estimate_bytes(root_rows, root_width)
    if final_bytes is not None:
        result["coordinator_final_bytes_estimated"] = final_bytes

    class_rows: dict[str, list[dict[str, Any]]] = {}
    for class_name, node_types in COORDINATOR_OPERATOR_CLASSES.items():
        class_rows[class_name] = [
            row for row in rows if str(row.get("node_type", "")) in node_types
        ]
        input_values: list[float] = []
        output_values: list[float] = []
        time_values: list[float] = []
        for row in class_rows[class_name]:
            node_id = row.get("node_id")
            try:
                children = rows_by_parent.get(int(node_id), [])
            except (TypeError, ValueError):
                children = []
            child_rows = [
                value
                for value in (_plan_row_count(child) for child in children)
                if value is not None
            ]
            output_rows = _plan_row_count(row)
            actual_time = _plan_row_time_ms(row)
            if child_rows:
                input_values.append(sum(child_rows))
            if output_rows is not None:
                output_values.append(output_rows)
            if actual_time is not None:
                time_values.append(actual_time)

        result[f"coordinator_{class_name}_operator_count"] = len(
            class_rows[class_name]
        )
        if input_values:
            result[f"coordinator_{class_name}_input_rows_sum"] = sum(input_values)
            result[f"coordinator_{class_name}_input_rows_max"] = max(input_values)
        if output_values:
            result[f"coordinator_{class_name}_output_rows_sum"] = sum(output_values)
        if time_values:
            result[f"coordinator_{class_name}_time_ms_max"] = max(time_values)

    blocking_rows = [
        row
        for class_name in COORDINATOR_BLOCKING_CLASSES
        for row in class_rows[class_name]
    ]
    blocking_inputs: list[float] = []
    blocking_outputs: list[float] = []
    for row in blocking_rows:
        try:
            children = rows_by_parent.get(int(row.get("node_id")), [])
        except (TypeError, ValueError):
            children = []
        child_values = [
            value
            for value in (_plan_row_count(child) for child in children)
            if value is not None
        ]
        if child_values:
            blocking_inputs.append(sum(child_values))
        output_rows = _plan_row_count(row)
        if output_rows is not None:
            blocking_outputs.append(output_rows)
    result["coordinator_blocking_operator_count"] = len(blocking_rows)
    if blocking_inputs:
        result["coordinator_blocking_input_rows_sum"] = sum(blocking_inputs)
        result["coordinator_blocking_input_rows_max"] = max(blocking_inputs)
    if blocking_outputs:
        result["coordinator_blocking_output_rows_sum"] = sum(blocking_outputs)

    root_temp_read = _float_or_none(root.get("temp_read_blocks"))
    root_temp_written = _float_or_none(root.get("temp_written_blocks"))
    if root_temp_read is not None:
        result["coordinator_temp_read_blocks"] = root_temp_read
    if root_temp_written is not None:
        result["coordinator_temp_written_blocks"] = root_temp_written
    disk_sorts = [
        row
        for row in class_rows["sort"]
        if str(row.get("sort_space_type", "")).strip().lower() == "disk"
    ]
    result["coordinator_disk_sort_count"] = len(disk_sorts)
    sort_space_values = [
        value
        for value in (
            _float_or_none(row.get("sort_space_used")) for row in class_rows["sort"]
        )
        if value is not None
    ]
    if sort_space_values:
        result["coordinator_sort_space_used_kb_max"] = max(sort_space_values)
    hash_batches = [
        value
        for value in (_float_or_none(row.get("hash_batches")) for row in rows)
        if value is not None
    ]
    if hash_batches:
        result["coordinator_hash_batches_max"] = max(hash_batches)
    hashagg_disk_usage = [
        value
        for value in (
            _float_or_none(row.get("disk_usage"))
            for row in class_rows["aggregate"]
        )
        if value is not None
    ]
    if hashagg_disk_usage:
        result["coordinator_hashagg_disk_usage_kb_max"] = max(hashagg_disk_usage)
    peak_memory = [
        value
        for value in (
            _float_or_none(row.get("peak_memory_usage")) for row in rows
        )
        if value is not None
    ]
    if peak_memory:
        result["coordinator_peak_memory_usage_kb_max"] = max(peak_memory)
    result["coordinator_spill_present"] = _bool_text(
        (root_temp_read or 0.0) > 0
        or (root_temp_written or 0.0) > 0
        or bool(disk_sorts)
        or any(value > 1 for value in hash_batches)
    )
    return result


def _first_value(*values: Any, default: Any = "") -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _citus_repartition_observed_v2(row: dict[str, Any]) -> bool:
    """Combine main-plan and regional Citus repartition evidence."""
    legacy = str(row.get("citus_repartition_query", "")).strip().lower() == "true"
    remote_count = _float_or_none(row.get("remote_citus_repartition_mapmerge_count"))
    locality_classes = {
        item.strip()
        for item in str(row.get("remote_citus_plan_locality_classes", "")).split(",")
        if item.strip()
    }
    return (
        legacy
        or bool(remote_count and remote_count > 0)
        or ("repartition_mapmerge" in locality_classes)
    )


def _execution_evidence_contract_summary(
    *,
    query_row: dict[str, Any],
    plan_files: list[dict[str, Any]],
    region_fragments: list[dict[str, Any]],
    worker_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe evidence availability without turning missing child rows into zero work."""

    internal_plan_count = sum(
        str(row.get("plan_scope", "")) == "fdw_auto_explain_internal"
        for row in plan_files
    )
    remote_plan_count = len(region_fragments)
    has_foreign_scan = str(query_row.get("main_has_foreign_scan", "")).lower() == "true"

    if remote_plan_count:
        regional_status = "available"
    elif has_foreign_scan:
        regional_status = "missing_unexpected"
    else:
        regional_status = "not_applicable_direct_or_local"

    repartition_without_tasks = _citus_repartition_observed_v2(query_row) or (
        str(query_row.get("citus_tasks_shown_none", "")).lower() == "true"
        or (_float_or_none(query_row.get("remote_citus_tasks_shown_none_count")) or 0) > 0
    )
    if worker_tasks:
        worker_status = "available"
    elif repartition_without_tasks:
        worker_status = "structurally_unavailable_repartition"
    else:
        direct_task_count = _float_or_none(query_row.get("citus_top_task_count"))
        remote_task_count = _float_or_none(query_row.get("remote_region_task_count_sum"))
        if (direct_task_count or 0) > 0 or (remote_task_count or 0) > 0:
            worker_status = "missing_unexpected"
        else:
            worker_status = "not_applicable_no_citus_tasks"

    parse_statuses = [
        str(row.get("parse_status", "")).strip().lower() for row in worker_tasks
    ]
    timing_available = any(
        _float_or_none(row.get("worker_task_actual_time_ms")) is not None
        for row in worker_tasks
    )
    if timing_available:
        timing_status = "available"
    elif worker_tasks:
        timing_status = "unavailable_in_embedded_task_plan"
    elif worker_status == "structurally_unavailable_repartition":
        timing_status = "structurally_unavailable_repartition"
    else:
        timing_status = "not_applicable"

    return {
        "regional_remote_plan_count": remote_plan_count,
        "regional_internal_plan_count": internal_plan_count,
        "regional_plan_evidence_status": regional_status,
        "worker_task_evidence_status": worker_status,
        "worker_task_plan_format": (
            "citus_embedded_text_in_explain_json" if worker_tasks else ""
        ),
        "worker_task_timing_status": timing_status,
        "worker_task_parse_ok_count": parse_statuses.count("ok"),
        "worker_task_parse_partial_count": parse_statuses.count("partial"),
        "worker_task_parse_failed_count": sum(
            status not in {"ok", "partial"} for status in parse_statuses
        ),
    }


def _blank_if_none(value: Any) -> Any:
    return "" if value is None else value


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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


def _node_class_estimate_error(rows: list[dict[str, Any]], class_name: str) -> float | None:
    def matches(row: dict[str, Any]) -> bool:
        node_type = str(row.get("node_type", ""))
        if class_name == "foreign_scan":
            return node_type == "Foreign Scan"
        if class_name == "aggregate":
            return "Aggregate" in node_type
        if class_name == "join":
            return "Join" in node_type
        if class_name == "sort":
            return node_type in {"Sort", "Incremental Sort"}
        return False

    values = [
        value
        for value in (_rows_estimate_error_log(row) for row in rows if matches(row))
        if value is not None
    ]
    return _largest_abs_signed(values)


def _estimate_error_summary(
    *,
    main_plan_file: Path | None,
    remote_plan_files: list[Path],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "foreign_scan_rows_estimate_error_log": "",
        "aggregate_rows_estimate_error_log": "",
        "join_rows_estimate_error_log": "",
        "sort_rows_estimate_error_log": "",
        "remote_root_rows_estimate_error_log": "",
    }
    if main_plan_file is None or not main_plan_file.exists():
        return result

    try:
        main_rows = extract_plan_rows(_load_json_value(main_plan_file))
    except (json.JSONDecodeError, ValueError):
        return result

    for class_name in ("foreign_scan", "aggregate", "join", "sort"):
        value = _node_class_estimate_error(main_rows, class_name)
        if value is not None:
            result[f"{class_name}_rows_estimate_error_log"] = value

    remote_root_values: list[float] = []
    for remote_plan_file in remote_plan_files:
        if not remote_plan_file.exists():
            continue
        try:
            remote_rows = extract_plan_rows(_load_json_value(remote_plan_file))
        except (json.JSONDecodeError, ValueError):
            continue
        if not remote_rows:
            continue
        value = _rows_estimate_error_log(remote_rows[0])
        if value is not None:
            remote_root_values.append(value)
    remote_root_error = _largest_abs_signed(remote_root_values)
    if remote_root_error is not None:
        result["remote_root_rows_estimate_error_log"] = remote_root_error
    return result


def _iter_citus_task_groups(value: Any) -> list[tuple[int | None, list[Any]]]:
    groups: list[tuple[int | None, list[Any]]] = []
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            tasks = current.get("Tasks")
            explicit_count = current.get("Task Count")
            task_count = None
            try:
                task_count = int(explicit_count) if explicit_count not in ("", None) else None
            except (TypeError, ValueError):
                task_count = None
            if isinstance(tasks, list) or task_count is not None:
                groups.append((task_count, tasks if isinstance(tasks, list) else []))
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return groups


def _first_plan_node(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if "Node Type" in value:
            return value
        plan = value.get("Plan")
        if isinstance(plan, dict) and "Node Type" in plan:
            return plan
        for nested in value.values():
            found = _first_plan_node(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _first_plan_node(nested)
            if found is not None:
                return found
    return None


def _task_worker(task: Any) -> str:
    if not isinstance(task, dict):
        return ""
    for key in ("Node", "Worker", "Worker Node", "worker", "node"):
        value = task.get(key)
        if value not in ("", None):
            return str(value)
    return ""


def _relation_shard_names(sql_text: str) -> list[str]:
    return re.findall(r"\b(?:public\.)?([A-Za-z_][A-Za-z_0-9]*_[0-9]+)\b", sql_text)


def _classify_citus_task_locality(
    *,
    task_count: int | str,
    tasks: list[dict[str, Any]],
    has_repartition: bool,
) -> str:
    if has_repartition:
        return "repartition_mapmerge"
    try:
        numeric_task_count = int(task_count)
    except (TypeError, ValueError):
        numeric_task_count = len(tasks)
    if numeric_task_count == 1:
        return "router_single_task"
    task_queries = [str(task.get("Query", "")) for task in tasks if isinstance(task, dict)]
    join_queries = [query for query in task_queries if re.search(r"\bjoin\b", query, flags=re.I)]
    if not join_queries:
        return "distributed_task_plan" if numeric_task_count > 1 else "unknown"

    relation_counts: Counter[str] = Counter()
    relation_families_by_task: list[set[str]] = []
    for query in join_queries:
        relations = _relation_shard_names(query)
        relation_counts.update(set(relations))
        relation_families_by_task.append(
            {re.sub(r"_[0-9]+$", "", relation) for relation in relations}
        )
    if relation_counts:
        dominant_relation_count = relation_counts.most_common(1)[0][1]
        dominant_relation_share = dominant_relation_count / max(len(join_queries), 1)
        if dominant_relation_count >= 2 and dominant_relation_share >= 0.5:
            return "reference_join_candidate"
    if relation_families_by_task and all(
        len(families) >= 2 for families in relation_families_by_task
    ):
        return "colocated_join_candidate"
    return "distributed_join_candidate"


def _iter_explain_documents(value: Any) -> list[Any]:
    documents: list[Any] = []
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if isinstance(current.get("Plan"), dict):
                documents.append(current)
            else:
                stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(reversed(current))
    return documents


def _iter_citus_task_remote_plans(value: Any) -> list[tuple[int, str, Any]]:
    remote_plans: list[tuple[int, str, Any]] = []
    task_index = 0
    for _, tasks in _iter_citus_task_groups(value):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            worker = _task_worker(task)
            for explain_document in _iter_explain_documents(task.get("Remote Plan")):
                remote_plans.append((task_index, worker, explain_document))
            task_index += 1
    return remote_plans


def _cv_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    if mean == 0.0:
        return 0.0 if std == 0.0 else None
    return std / mean


def _normalized_population_cv(value: float | None, count: int) -> float | None:
    if value is None or count <= 0:
        return None
    if count == 1:
        return 0.0
    return max(0.0, min(1.0, value / math.sqrt(count - 1.0)))


def _normalized_isf(value: float | None, count: int) -> float | None:
    if value is None or count <= 0:
        return None
    if count == 1:
        return 0.0
    return max(0.0, min(1.0, (value - 1.0) / (count - 1.0)))


def _parse_byte_count(value: Any) -> float | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([kmgt]?b|bytes?)?", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "bytes").lower()
    multiplier = {
        "bytes": 1,
        "byte": 1,
        "b": 1,
        "kb": 1024,
        "mb": 1024**2,
        "gb": 1024**3,
        "tb": 1024**4,
    }.get(unit, 1)
    return number * multiplier


def _worker_plan_summary(task: dict[str, Any]) -> dict[str, Any]:
    summary = task.get("Worker Plan Summary")
    if isinstance(summary, dict):
        return summary
    root = _first_plan_node(task.get("Remote Plan"))
    if root is None:
        return {}
    document = {"Plan": root}
    try:
        rows = extract_plan_rows(document)
    except ValueError:
        return {}

    node_counts = Counter(str(row.get("node_type", "")) for row in rows)
    node_counts.pop("", None)
    scan_counts = Counter(
        scan_class for row in rows if (scan_class := _scan_class(str(row.get("node_type", ""))))
    )
    scan_rows = [
        value
        for row in rows
        if _scan_class(str(row.get("node_type", "")))
        and (value := _float_or_none(row.get("actual_rows"))) is not None
    ]
    root_rows = _float_or_none(rows[0].get("actual_rows")) if rows else None
    root_time = _float_or_none(rows[0].get("actual_total_time")) if rows else None
    spill_count = sum(
        1
        for row in rows
        if (_float_or_none(row.get("temp_read_blocks")) or 0) > 0
        or (_float_or_none(row.get("temp_written_blocks")) or 0) > 0
        or str(row.get("sort_space_type", "")).lower() == "disk"
        or (_float_or_none(row.get("hash_batches")) or 1) > 1
    )

    def counter_sum(field: str) -> float:
        return sum(_float_or_none(row.get(field)) or 0 for row in rows)

    return {
        "parse_status": "ok",
        "parse_confidence": "high",
        "root_node_type": str(rows[0].get("node_type", "")) if rows else "",
        "node_count": len(rows),
        "max_depth": max((int(row.get("depth", 0) or 0) for row in rows), default=0),
        "node_type_counts": dict(sorted(node_counts.items())),
        "scan_type_counts": dict(sorted(scan_counts.items())),
        "unknown_count": 0,
        "unknown_set": [],
        "actual_rows": root_rows if root_rows is not None else "",
        "scan_actual_rows_sum": sum(scan_rows) if scan_rows else "",
        "scan_actual_rows_max": max(scan_rows) if scan_rows else "",
        "actual_time_ms": root_time if root_time is not None else "",
        "join_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_join(node)
        ),
        "aggregate_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_aggregate(node)
        ),
        "sort_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_sort(node)
        ),
        "blocking_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_blocking(node)
        ),
        "scan_node_count": sum(count for node, count in node_counts.items() if _scan_class(node)),
        "materialization_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_materialization(node)
        ),
        "parallel_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_parallel(node)
        ),
        "bitmap_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_bitmap(node)
        ),
        "index_access_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_index_access(node)
        ),
        "sequential_access_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_sequential_access(node)
        ),
        "spill_capable_node_count": sum(
            count for node, count in node_counts.items() if _is_worker_spill_capable(node)
        ),
        "has_join": any(_is_worker_join(node) for node in node_counts),
        "has_aggregate": any(_is_worker_aggregate(node) for node in node_counts),
        "has_sort": any(_is_worker_sort(node) for node in node_counts),
        "has_blocking_operator": any(_is_worker_blocking(node) for node in node_counts),
        "has_parallel_operator": any(_is_worker_parallel(node) for node in node_counts),
        "has_hash": any("Hash" in node for node in node_counts),
        "has_materialize": "Materialize" in node_counts,
        "spill_flag": bool(spill_count),
        "spill_count": spill_count,
        "shared_hit_blocks": counter_sum("shared_hit_blocks") or "",
        "shared_read_blocks": counter_sum("shared_read_blocks") or "",
        "temp_read_blocks": counter_sum("temp_read_blocks") or "",
        "temp_written_blocks": counter_sum("temp_written_blocks") or "",
        "plan_fingerprint": plan_fingerprint(document),
    }


def _worker_task_fragment_rows_from_plan_file(
    *,
    root: Path,
    query_sweep_id: str,
    query_run_id: str,
    instance_id: str,
    template_id: str,
    plan_id: str,
    remote_sql_id: str,
    fdw_region: str,
    plan_file: Path,
) -> list[dict[str, Any]]:
    if not plan_file.exists():
        return []
    try:
        value = _load_json_value(plan_file)
    except (json.JSONDecodeError, ValueError):
        return []
    rows: list[dict[str, Any]] = []
    task_index = 0
    for _, tasks in _iter_citus_task_groups(value):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            worker_summary = _worker_plan_summary(task)
            tuple_bytes = _parse_byte_count(task.get("Tuple data received from node"))
            task_query = str(task.get("Query", ""))
            rows.append(
                {
                    "query_sweep_id": query_sweep_id,
                    "query_run_id": query_run_id,
                    "instance_id": instance_id,
                    "template_id": template_id,
                    "plan_id": plan_id,
                    "remote_sql_id": remote_sql_id,
                    "fdw_region": fdw_region,
                    "task_index": task_index,
                    "worker_node": _task_worker(task),
                    "task_query_hash": _hash_text(task_query) if task_query else "",
                    "tuple_data_received_bytes": tuple_bytes if tuple_bytes is not None else "",
                    "parse_status": worker_summary.get("parse_status", ""),
                    "parse_confidence": worker_summary.get("parse_confidence", ""),
                    "worker_task_plan_fingerprint": worker_summary.get("plan_fingerprint", ""),
                    "worker_task_root_node_type": worker_summary.get("root_node_type", ""),
                    "worker_task_node_count": worker_summary.get("node_count", ""),
                    "worker_task_plan_max_depth": worker_summary.get("max_depth", ""),
                    "worker_task_actual_rows": worker_summary.get("actual_rows", ""),
                    "worker_task_scan_actual_rows_sum": worker_summary.get(
                        "scan_actual_rows_sum", ""
                    ),
                    "worker_task_scan_actual_rows_max": worker_summary.get(
                        "scan_actual_rows_max", ""
                    ),
                    "worker_task_actual_time_ms": worker_summary.get("actual_time_ms", ""),
                    "worker_task_node_type_counts_json": _json_text(
                        worker_summary.get("node_type_counts", {})
                    ),
                    "worker_task_scan_type_counts_json": _json_text(
                        worker_summary.get("scan_type_counts", {})
                    ),
                    "worker_task_node_type_unknown_count": worker_summary.get("unknown_count", ""),
                    "worker_task_node_type_unknown_set_json": _json_text(
                        worker_summary.get("unknown_set", [])
                    ),
                    "worker_task_join_node_count": worker_summary.get("join_node_count", ""),
                    "worker_task_aggregate_node_count": worker_summary.get(
                        "aggregate_node_count", ""
                    ),
                    "worker_task_sort_node_count": worker_summary.get("sort_node_count", ""),
                    "worker_task_blocking_node_count": worker_summary.get(
                        "blocking_node_count", ""
                    ),
                    "worker_task_scan_node_count": worker_summary.get("scan_node_count", ""),
                    "worker_task_materialization_node_count": worker_summary.get(
                        "materialization_node_count", ""
                    ),
                    "worker_task_parallel_node_count": worker_summary.get(
                        "parallel_node_count", ""
                    ),
                    "worker_task_bitmap_node_count": worker_summary.get("bitmap_node_count", ""),
                    "worker_task_index_access_node_count": worker_summary.get(
                        "index_access_node_count", ""
                    ),
                    "worker_task_sequential_access_node_count": worker_summary.get(
                        "sequential_access_node_count", ""
                    ),
                    "worker_task_spill_capable_node_count": worker_summary.get(
                        "spill_capable_node_count", ""
                    ),
                    "worker_task_has_join": _bool_text(bool(worker_summary.get("has_join", False)))
                    if worker_summary
                    else "",
                    "worker_task_has_aggregate": _bool_text(
                        bool(worker_summary.get("has_aggregate", False))
                    )
                    if worker_summary
                    else "",
                    "worker_task_has_sort": _bool_text(bool(worker_summary.get("has_sort", False)))
                    if worker_summary
                    else "",
                    "worker_task_has_blocking_operator": _bool_text(
                        bool(worker_summary.get("has_blocking_operator", False))
                    )
                    if worker_summary
                    else "",
                    "worker_task_has_parallel_operator": _bool_text(
                        bool(worker_summary.get("has_parallel_operator", False))
                    )
                    if worker_summary
                    else "",
                    "worker_task_has_hash": _bool_text(bool(worker_summary.get("has_hash", False)))
                    if worker_summary
                    else "",
                    "worker_task_has_materialize": _bool_text(
                        bool(worker_summary.get("has_materialize", False))
                    )
                    if worker_summary
                    else "",
                    "worker_task_spill_flag": _bool_text(
                        bool(worker_summary.get("spill_flag", False))
                    )
                    if worker_summary
                    else "",
                    "worker_task_spill_count": worker_summary.get("spill_count", ""),
                    "worker_task_shared_hit_blocks": worker_summary.get("shared_hit_blocks", ""),
                    "worker_task_shared_read_blocks": worker_summary.get("shared_read_blocks", ""),
                    "worker_task_temp_read_blocks": worker_summary.get("temp_read_blocks", ""),
                    "worker_task_temp_written_blocks": worker_summary.get(
                        "temp_written_blocks", ""
                    ),
                    "plan_json_file": _rel(root, plan_file),
                }
            )
            task_index += 1
    return rows


def _worker_task_aggregates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "worker_task_plan_count": "",
        "worker_task_actual_rows_sum": "",
        "worker_task_actual_rows_min": "",
        "worker_task_actual_rows_max": "",
        "worker_task_actual_rows_cv": "",
        "worker_task_actual_rows_max_share": "",
        "worker_task_root_rows_isf": "",
        "worker_task_scan_actual_rows_sum": "",
        "worker_task_scan_actual_rows_min": "",
        "worker_task_scan_actual_rows_max": "",
        "worker_task_scan_actual_rows_cv": "",
        "worker_task_scan_actual_rows_max_share": "",
        "worker_task_scan_rows_isf": "",
        "worker_task_scan_rows_isf_normalized": "",
        "worker_task_active_scan_rows_isf": "",
        "worker_task_active_scan_rows_isf_normalized": "",
        "worker_task_active_scan_skew_applicable": "",
        "worker_task_active_scan_skew_applicable_region_count": "",
        "worker_task_tuple_bytes_sum": "",
        "worker_task_tuple_bytes_min": "",
        "worker_task_tuple_bytes_max": "",
        "worker_task_tuple_bytes_cv": "",
        "worker_task_tuple_bytes_max_share": "",
        "worker_task_tuple_bytes_isf": "",
        "worker_task_tuple_bytes_isf_normalized": "",
        "worker_task_tuple_bytes_skew_applicable": "",
        "worker_task_tuple_bytes_skew_applicable_region_count": "",
        "worker_task_nonzero_scan_count": "",
        "worker_task_nonzero_scan_share": "",
        "worker_task_scan_skew_applicable": "",
        "worker_task_scan_skew_applicable_region_count": "",
        "worker_task_actual_time_sum": "",
        "worker_task_actual_time_min": "",
        "worker_task_actual_time_max": "",
        "worker_task_actual_time_cv": "",
        "worker_task_actual_time_max_share": "",
        "worker_task_actual_time_isf": "",
        "worker_task_actual_time_isf_normalized": "",
        "worker_task_scan_type_counts_json": "",
        "worker_task_index_scan_share": "",
        "worker_task_seq_scan_share": "",
        "worker_task_bitmap_scan_share": "",
        "worker_task_node_type_counts_json": "",
        "worker_task_node_type_unknown_count": "",
        "worker_task_node_type_unknown_set_json": "",
        "worker_task_node_count_sum": "",
        "worker_task_plan_max_depth_max": "",
        "worker_task_plan_max_depth_mean": "",
        "worker_task_join_node_count": "",
        "worker_task_aggregate_node_count": "",
        "worker_task_sort_node_count": "",
        "worker_task_blocking_node_count": "",
        "worker_task_scan_node_count": "",
        "worker_task_materialization_node_count": "",
        "worker_task_parallel_node_count": "",
        "worker_task_bitmap_node_count": "",
        "worker_task_index_access_node_count": "",
        "worker_task_sequential_access_node_count": "",
        "worker_task_spill_capable_node_count": "",
        "worker_task_has_join": "",
        "worker_task_has_aggregate": "",
        "worker_task_has_sort": "",
        "worker_task_has_blocking_operator": "",
        "worker_task_has_parallel_operator": "",
        "worker_task_has_hash": "",
        "worker_task_has_materialize": "",
        "worker_task_plan_fingerprint_count": "",
        "worker_task_plan_fingerprint_dominant_share": "",
        "worker_task_spill_count": "",
        "worker_task_shared_hit_sum": "",
        "worker_task_shared_read_sum": "",
        "worker_task_temp_read_sum": "",
        "worker_task_temp_written_sum": "",
        "worker_task_region_count": "",
        "worker_task_region_task_count_cv": "",
        "worker_task_region_rows_cv": "",
        "worker_task_region_rows_max_share": "",
        "worker_task_region_scan_rows_cv": "",
        "worker_task_region_scan_rows_max_share": "",
        "worker_task_within_region_rows_cv_max": "",
        "worker_task_within_region_rows_cv_mean": "",
        "worker_task_within_region_rows_max_share_max": "",
        "worker_task_within_region_scan_rows_cv_max": "",
        "worker_task_within_region_scan_rows_cv_mean": "",
        "worker_task_within_region_scan_rows_max_share_max": "",
        "worker_task_within_region_scan_rows_isf_max": "",
        "worker_task_within_region_scan_rows_isf_normalized_max": "",
        "worker_task_within_region_active_scan_rows_isf_normalized_max": "",
        "worker_task_within_region_tuple_bytes_isf_normalized_max": "",
        "worker_task_within_region_worker_scan_rows_cv_max": "",
        "worker_task_within_region_worker_scan_rows_cv_mean": "",
        "worker_task_within_region_worker_scan_rows_max_share_max": "",
        "worker_task_within_region_worker_scan_rows_isf_max": "",
        "worker_task_within_region_worker_scan_rows_isf_normalized_max": "",
        "worker_scan_rows_skew_applicable": "",
        "worker_scan_rows_skew_applicable_region_count": "",
        "worker_task_within_region_plan_fingerprint_count_max": "",
        "worker_task_within_region_plan_fingerprint_count_mean": "",
        "worker_task_worker_count": "",
        "worker_task_count_max_share": "",
        "worker_task_count_isf": "",
        "worker_task_count_isf_normalized": "",
        "worker_rows_max_share": "",
        "worker_rows_isf": "",
        "worker_rows_isf_normalized": "",
        "worker_time_max_share": "",
        "worker_time_isf": "",
        "worker_time_isf_normalized": "",
        "worker_scan_rows_sum": "",
        "worker_scan_rows_worker_count": "",
        "worker_scan_rows_cv": "",
        "worker_scan_rows_cv_normalized": "",
        "worker_scan_rows_max_share": "",
        "worker_scan_rows_isf": "",
        "worker_scan_rows_isf_normalized": "",
    }
    if not rows:
        return result

    def numeric(column: str) -> list[float]:
        return [
            value
            for value in (_float_or_none(row.get(column)) for row in rows)
            if value is not None
        ]

    def sum_column(column: str) -> float:
        return sum(numeric(column))

    actual_rows = numeric("worker_task_actual_rows")
    scan_actual_rows = numeric("worker_task_scan_actual_rows_sum")
    tuple_bytes = numeric("tuple_data_received_bytes")
    actual_times = numeric("worker_task_actual_time_ms")
    node_counts = numeric("worker_task_node_count")
    depths = numeric("worker_task_plan_max_depth")
    scan_counts: Counter[str] = Counter()
    node_type_counts: Counter[str] = Counter()
    unknown_sets: set[str] = set()
    fingerprints = [
        str(row.get("worker_task_plan_fingerprint", ""))
        for row in rows
        if row.get("worker_task_plan_fingerprint", "")
    ]
    for row in rows:
        try:
            encoded_counts = row.get("worker_task_scan_type_counts_json") or "{}"
            scan_counts.update(json.loads(str(encoded_counts)))
        except json.JSONDecodeError:
            pass
        try:
            node_type_counts.update(
                json.loads(str(row.get("worker_task_node_type_counts_json") or "{}"))
            )
        except json.JSONDecodeError:
            pass
        try:
            unknown = json.loads(str(row.get("worker_task_node_type_unknown_set_json") or "[]"))
            if isinstance(unknown, list):
                unknown_sets.update(str(item) for item in unknown)
        except json.JSONDecodeError:
            pass

    result["worker_task_plan_count"] = len(rows)
    if actual_rows:
        rows_sum = sum(actual_rows)
        rows_max_share = max(actual_rows) / rows_sum if rows_sum > 0 else ""
        result.update(
            {
                "worker_task_actual_rows_sum": rows_sum,
                "worker_task_actual_rows_min": min(actual_rows),
                "worker_task_actual_rows_max": max(actual_rows),
                "worker_task_actual_rows_cv": _cv_or_none(actual_rows),
                "worker_task_actual_rows_max_share": rows_max_share,
                "worker_task_root_rows_isf": rows_max_share * len(actual_rows)
                if rows_max_share != ""
                else "",
            }
        )
    if scan_actual_rows:
        scan_rows_sum = sum(scan_actual_rows)
        scan_rows_max_share = max(scan_actual_rows) / scan_rows_sum if scan_rows_sum > 0 else ""
        nonzero_scan_count = sum(value > 0 for value in scan_actual_rows)
        result.update(
            {
                "worker_task_scan_actual_rows_sum": scan_rows_sum,
                "worker_task_scan_actual_rows_min": min(scan_actual_rows),
                "worker_task_scan_actual_rows_max": max(scan_actual_rows),
                "worker_task_scan_actual_rows_cv": _cv_or_none(scan_actual_rows),
                "worker_task_scan_actual_rows_max_share": scan_rows_max_share,
                "worker_task_scan_rows_isf": scan_rows_max_share * len(scan_actual_rows)
                if scan_rows_max_share != ""
                else "",
                "worker_task_nonzero_scan_count": nonzero_scan_count,
                "worker_task_nonzero_scan_share": nonzero_scan_count / len(scan_actual_rows),
            }
        )
        result["worker_task_scan_rows_isf_normalized"] = _normalized_isf(
            _float_or_none(result.get("worker_task_scan_rows_isf")),
            len(scan_actual_rows),
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
    if tuple_bytes:
        tuple_bytes_sum = sum(tuple_bytes)
        tuple_bytes_max_share = (
            max(tuple_bytes) / tuple_bytes_sum if tuple_bytes_sum > 0 else ""
        )
        tuple_bytes_isf = (
            tuple_bytes_max_share * len(tuple_bytes)
            if tuple_bytes_max_share != ""
            else ""
        )
        result.update(
            {
                "worker_task_tuple_bytes_sum": tuple_bytes_sum,
                "worker_task_tuple_bytes_min": min(tuple_bytes),
                "worker_task_tuple_bytes_max": max(tuple_bytes),
                "worker_task_tuple_bytes_cv": _cv_or_none(tuple_bytes),
                "worker_task_tuple_bytes_max_share": tuple_bytes_max_share,
                "worker_task_tuple_bytes_isf": tuple_bytes_isf,
                "worker_task_tuple_bytes_isf_normalized": _blank_if_none(
                    _normalized_isf(
                        _float_or_none(tuple_bytes_isf),
                        len(tuple_bytes),
                    )
                ),
            }
        )
    if actual_times:
        time_sum = sum(actual_times)
        time_max_share = max(actual_times) / time_sum if time_sum > 0 else ""
        time_isf = time_max_share * len(actual_times) if time_max_share != "" else ""
        result.update(
            {
                "worker_task_actual_time_sum": time_sum,
                "worker_task_actual_time_min": min(actual_times),
                "worker_task_actual_time_max": max(actual_times),
                "worker_task_actual_time_cv": _cv_or_none(actual_times),
                "worker_task_actual_time_max_share": time_max_share,
                "worker_task_actual_time_isf": time_isf,
                "worker_task_actual_time_isf_normalized": _blank_if_none(
                    _normalized_isf(_float_or_none(time_isf), len(actual_times))
                ),
            }
        )

    worker_task_counts: dict[str, float] = defaultdict(float)
    worker_rows: dict[str, float] = defaultdict(float)
    worker_scan_rows: dict[str, float] = defaultdict(float)
    worker_times: dict[str, float] = defaultdict(float)
    worker_row_observation_counts: dict[str, float] = defaultdict(float)
    worker_scan_row_observation_counts: dict[str, float] = defaultdict(float)
    worker_time_observation_counts: dict[str, float] = defaultdict(float)
    for row in rows:
        worker = str(row.get("worker_node", "")).strip()
        if not worker:
            continue
        worker_task_counts[worker] += 1.0
        row_count = _float_or_none(row.get("worker_task_actual_rows"))
        if row_count is None:
            row_count = _float_or_none(row.get("worker_task_scan_actual_rows_sum"))
        if row_count is not None:
            worker_rows[worker] += row_count
            worker_row_observation_counts[worker] += 1.0
        scan_row_count = _float_or_none(row.get("worker_task_scan_actual_rows_sum"))
        if scan_row_count is not None:
            worker_scan_rows[worker] += scan_row_count
            worker_scan_row_observation_counts[worker] += 1.0
        task_time = _float_or_none(row.get("worker_task_actual_time_ms"))
        if task_time is not None:
            worker_times[worker] += task_time
            worker_time_observation_counts[worker] += 1.0

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
            _normalized_isf(
                _float_or_none(task_count_isf),
                len(task_count_values),
            )
        )
    if worker_task_counts and all(
        worker_row_observation_counts[worker] == task_count
        for worker, task_count in worker_task_counts.items()
    ):
        worker_row_values = [
            worker_rows[worker] for worker in sorted(worker_task_counts)
        ]
        worker_row_total = sum(worker_row_values)
        worker_row_max_share = (
            max(worker_row_values) / worker_row_total if worker_row_total > 0 else ""
        )
        worker_row_isf = (
            worker_row_max_share * len(worker_row_values)
            if worker_row_max_share != ""
            else ""
        )
        result["worker_rows_cv"] = _cv_or_none(worker_row_values)
        result["worker_rows_max_share"] = worker_row_max_share
        result["worker_rows_isf"] = worker_row_isf
        result["worker_rows_isf_normalized"] = _blank_if_none(
            _normalized_isf(_float_or_none(worker_row_isf), len(worker_row_values))
        )
    if worker_task_counts and all(
        worker_scan_row_observation_counts[worker] == task_count
        for worker, task_count in worker_task_counts.items()
    ):
        worker_values = [worker_scan_rows[worker] for worker in sorted(worker_task_counts)]
        worker_count = len(worker_values)
        worker_total = sum(worker_values)
        worker_cv = _cv_or_none(worker_values)
        worker_max_share = max(worker_values) / worker_total if worker_total > 0 else 0.0
        worker_isf = worker_max_share * worker_count
        result["worker_scan_rows_sum"] = worker_total
        result["worker_scan_rows_worker_count"] = worker_count
        result["worker_scan_rows_cv"] = _blank_if_none(worker_cv)
        result["worker_scan_rows_cv_normalized"] = _blank_if_none(
            _normalized_population_cv(worker_cv, worker_count)
        )
        result["worker_scan_rows_max_share"] = worker_max_share
        result["worker_scan_rows_isf"] = worker_isf
        result["worker_scan_rows_isf_normalized"] = _blank_if_none(
            _normalized_isf(worker_isf, worker_count)
        )
    if worker_task_counts and all(
        worker_time_observation_counts[worker] == task_count
        for worker, task_count in worker_task_counts.items()
    ):
        worker_time_values = [
            worker_times[worker] for worker in sorted(worker_task_counts)
        ]
        worker_time_total = sum(worker_time_values)
        worker_time_max_share = (
            max(worker_time_values) / worker_time_total if worker_time_total > 0 else ""
        )
        worker_time_isf = (
            worker_time_max_share * len(worker_time_values)
            if worker_time_max_share != ""
            else ""
        )
        result["worker_time_cv"] = _cv_or_none(worker_time_values)
        result["worker_time_max_share"] = worker_time_max_share
        result["worker_time_isf"] = worker_time_isf
        result["worker_time_isf_normalized"] = _blank_if_none(
            _normalized_isf(_float_or_none(worker_time_isf), len(worker_time_values))
        )

    scan_total = sum(scan_counts.values())
    if scan_counts:
        result["worker_task_scan_type_counts_json"] = _json_text(dict(sorted(scan_counts.items())))
        result["worker_task_index_scan_share"] = scan_counts.get("index_scan", 0) / scan_total
        result["worker_task_seq_scan_share"] = scan_counts.get("seq_scan", 0) / scan_total
        result["worker_task_bitmap_scan_share"] = scan_counts.get("bitmap_scan", 0) / scan_total
    if node_type_counts:
        result["worker_task_node_type_counts_json"] = _json_text(
            dict(sorted(node_type_counts.items()))
        )
    result["worker_task_node_type_unknown_count"] = sum_column(
        "worker_task_node_type_unknown_count"
    )
    result["worker_task_node_type_unknown_set_json"] = _json_text(sorted(unknown_sets))
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
        value = sum_column(column)
        result[output] = value if value else 0
    for output, column in (
        ("worker_task_shared_hit_sum", "worker_task_shared_hit_blocks"),
        ("worker_task_shared_read_sum", "worker_task_shared_read_blocks"),
        ("worker_task_temp_read_sum", "worker_task_temp_read_blocks"),
        ("worker_task_temp_written_sum", "worker_task_temp_written_blocks"),
    ):
        values = numeric(column)
        result[output] = sum(values) if values else ""
    for output, column in (
        ("worker_task_has_join", "worker_task_has_join"),
        ("worker_task_has_aggregate", "worker_task_has_aggregate"),
        ("worker_task_has_sort", "worker_task_has_sort"),
        ("worker_task_has_blocking_operator", "worker_task_has_blocking_operator"),
        ("worker_task_has_parallel_operator", "worker_task_has_parallel_operator"),
        ("worker_task_has_hash", "worker_task_has_hash"),
        ("worker_task_has_materialize", "worker_task_has_materialize"),
    ):
        result[output] = _bool_text(any(str(row.get(column, "")).lower() == "true" for row in rows))
    if fingerprints:
        counts = Counter(fingerprints)
        result["worker_task_plan_fingerprint_count"] = len(counts)
        result["worker_task_plan_fingerprint_dominant_share"] = max(counts.values()) / len(
            fingerprints
        )

    rows_by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        region = str(row.get("fdw_region") or "__unknown__")
        rows_by_region[region].append(row)
    if rows_by_region:
        result["worker_task_region_count"] = len(rows_by_region)
        region_task_counts = [float(len(region_rows)) for region_rows in rows_by_region.values()]
        result["worker_task_region_task_count_cv"] = _cv_or_none(region_task_counts)

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
                region_row_sum = sum(region_actual_rows)
                region_row_sums.append(region_row_sum)
                cv = _cv_or_none(region_actual_rows)
                if cv is not None:
                    within_region_rows_cvs.append(cv)
                if region_row_sum > 0:
                    within_region_rows_max_shares.append(max(region_actual_rows) / region_row_sum)
            region_scan_actual_rows = [
                value
                for value in (
                    _float_or_none(row.get("worker_task_scan_actual_rows_sum"))
                    for row in region_rows
                )
                if value is not None
            ]
            if region_scan_actual_rows:
                region_scan_row_sum = sum(region_scan_actual_rows)
                region_scan_row_sums.append(region_scan_row_sum)
                if len(region_scan_actual_rows) >= 2 and region_scan_row_sum > 0:
                    task_skew_applicable_region_count += 1
                scan_cv = _cv_or_none(region_scan_actual_rows)
                if scan_cv is not None:
                    within_region_scan_rows_cvs.append(scan_cv)
                if region_scan_row_sum > 0:
                    scan_max_share = max(region_scan_actual_rows) / region_scan_row_sum
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
                if row.get("worker_task_plan_fingerprint", "")
            }
            if region_fingerprints:
                within_region_plan_fingerprint_counts.append(float(len(region_fingerprints)))

        if region_row_sums:
            total_region_rows = sum(region_row_sums)
            result["worker_task_region_rows_cv"] = _cv_or_none(region_row_sums)
            result["worker_task_region_rows_max_share"] = (
                max(region_row_sums) / total_region_rows if total_region_rows > 0 else ""
            )
        if region_scan_row_sums:
            total_region_scan_rows = sum(region_scan_row_sums)
            result["worker_task_region_scan_rows_cv"] = _cv_or_none(region_scan_row_sums)
            result["worker_task_region_scan_rows_max_share"] = (
                max(region_scan_row_sums) / total_region_scan_rows
                if total_region_scan_rows > 0
                else ""
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
        result["worker_task_scan_skew_applicable"] = _bool_text(
            task_skew_applicable_region_count > 0
        )
        result["worker_task_active_scan_skew_applicable_region_count"] = (
            active_task_skew_applicable_region_count
        )
        result["worker_task_active_scan_skew_applicable"] = _bool_text(
            active_task_skew_applicable_region_count > 0
        )
        result["worker_task_tuple_bytes_skew_applicable_region_count"] = (
            tuple_bytes_skew_applicable_region_count
        )
        result["worker_task_tuple_bytes_skew_applicable"] = _bool_text(
            tuple_bytes_skew_applicable_region_count > 0
        )
        result["worker_scan_rows_skew_applicable_region_count"] = (
            worker_skew_applicable_region_count
        )
        result["worker_scan_rows_skew_applicable"] = _bool_text(
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


def _has_node_type(rows: list[dict[str, Any]], predicate: Any) -> bool:
    return any(predicate(str(row.get("node_type", ""))) for row in rows)


def _root_actual_rows(root: dict[str, Any]) -> float | None:
    rows = _float_or_none(root.get("actual_rows"))
    loops = _float_or_none(root.get("actual_loops"))
    if rows is None:
        return None
    return rows * (loops if loops is not None else 1.0)


def _root_actual_time(root: dict[str, Any]) -> float | None:
    time = _float_or_none(root.get("actual_total_time"))
    loops = _float_or_none(root.get("actual_loops"))
    if time is None:
        return None
    return time * (loops if loops is not None else 1.0)


def _citus_task_metadata(value: Any) -> dict[str, Any]:
    top_task_counts: list[int] = []
    all_task_counts: list[int] = []
    map_task_counts: list[int] = []
    merge_task_counts: list[int] = []
    tasks_shown_values: list[str] = []
    tasks_seen = 0
    shown_all = False
    tuple_bytes: list[float] = []
    tuple_node_bytes: list[float] = []
    task_tuple_bytes: list[float] = []
    all_tasks: list[dict[str, Any]] = []
    worker_parse_statuses: Counter[str] = Counter()
    worker_parse_confidences: Counter[str] = Counter()
    custom_scan_names: Counter[str] = Counter()

    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if current.get("Node Type") == "Custom Scan":
                provider = str(current.get("Custom Plan Provider", ""))
                if provider:
                    custom_scan_names[provider] += 1
            task_count_value = current.get("Task Count")
            try:
                if task_count_value not in ("", None):
                    task_count_int = int(task_count_value)
                    all_task_counts.append(task_count_int)
                    if (
                        "Tasks Shown" in current
                        or "Tuple data received from nodes" in current
                        or "Dependent Jobs" in current
                        or "Tasks" in current
                    ):
                        top_task_counts.append(task_count_int)
            except (TypeError, ValueError):
                pass
            for source_key, target in (
                ("Map Task Count", map_task_counts),
                ("Merge Task Count", merge_task_counts),
            ):
                try:
                    if current.get(source_key) not in ("", None):
                        target.append(int(current[source_key]))
                except (TypeError, ValueError):
                    pass
            tasks_shown = str(current.get("Tasks Shown", "")).strip()
            if tasks_shown:
                tasks_shown_values.append(tasks_shown)
            if tasks_shown.lower() == "all":
                shown_all = True
            tuple_nodes = _parse_byte_count(current.get("Tuple data received from nodes"))
            if tuple_nodes is not None:
                tuple_bytes.append(tuple_nodes)
                tuple_node_bytes.append(tuple_nodes)
            tasks = current.get("Tasks")
            if isinstance(tasks, list):
                tasks_seen += len(tasks)
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    all_tasks.append(task)
                    tuple_node = _parse_byte_count(task.get("Tuple data received from node"))
                    if tuple_node is not None:
                        tuple_bytes.append(tuple_node)
                        task_tuple_bytes.append(tuple_node)
                    summary = _worker_plan_summary(task)
                    status = str(summary.get("parse_status", ""))
                    confidence = str(summary.get("parse_confidence", ""))
                    if status:
                        worker_parse_statuses[status] += 1
                    if confidence:
                        worker_parse_confidences[confidence] += 1
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)

    task_count = (
        top_task_counts[0]
        if top_task_counts
        else (max(all_task_counts) if all_task_counts else (tasks_seen if tasks_seen else ""))
    )
    map_task_sum = sum(map_task_counts)
    merge_task_sum = sum(merge_task_counts)
    has_repartition = bool(map_task_counts or merge_task_counts) or any(
        value.lower().startswith("none") and "re-partition" in value.lower()
        for value in tasks_shown_values
    )
    task_list_available = tasks_seen > 0 or shown_all
    tuple_bytes_supported = True
    tuple_bytes_source = ""
    if task_tuple_bytes:
        tuple_bytes_source = "per_task_tuple_data_received"
    elif any(value > 0 for value in tuple_node_bytes):
        tuple_bytes_source = "top_job_tuple_data_received"
    elif tuple_node_bytes:
        tuple_bytes_source = "top_job_reported_zero"
        if has_repartition and not task_list_available:
            tuple_bytes_supported = False
            tuple_bytes_source = "repartition_task_list_unavailable_reported_zero"
    elif has_repartition and not task_list_available:
        tuple_bytes_supported = False
        tuple_bytes_source = "repartition_task_list_unavailable"

    try:
        repartition_fanout_ratio = (
            map_task_sum / int(task_count) if map_task_sum and int(task_count) > 0 else ""
        )
    except (TypeError, ValueError):
        repartition_fanout_ratio = ""
    locality_class = _classify_citus_task_locality(
        task_count=task_count,
        tasks=all_tasks,
        has_repartition=has_repartition,
    )
    parse_status = ""
    if worker_parse_statuses:
        parse_status = worker_parse_statuses.most_common(1)[0][0]
    return {
        "remote_citus_task_count": task_count,
        "remote_citus_top_task_count": task_count,
        "remote_citus_task_count_available": _bool_text(task_count not in ("", None)),
        "remote_citus_tasks_shown": ";".join(dict.fromkeys(tasks_shown_values)),
        "remote_citus_tasks_shown_none": _bool_text(
            any(value.lower().startswith("none") for value in tasks_shown_values)
        ),
        "remote_citus_task_list_available": _bool_text(task_list_available),
        "remote_citus_map_merge_job_count": len(map_task_counts)
        if map_task_counts or merge_task_counts
        else "",
        "remote_citus_dependent_map_task_count_sum": map_task_sum if map_task_sum else "",
        "remote_citus_dependent_merge_task_count_sum": merge_task_sum if merge_task_sum else "",
        "remote_citus_repartition_fanout_ratio": repartition_fanout_ratio,
        "remote_citus_tuple_bytes_supported": _bool_text(tuple_bytes_supported),
        "remote_citus_tuple_bytes_source": tuple_bytes_source,
        "remote_citus_plan_locality_class": locality_class,
        "remote_citus_router_single_task": _bool_text(locality_class == "router_single_task"),
        "remote_citus_reference_join_candidate": _bool_text(
            locality_class == "reference_join_candidate"
        ),
        "remote_citus_colocated_join_candidate": _bool_text(
            locality_class == "colocated_join_candidate"
        ),
        "remote_citus_repartition_mapmerge": _bool_text(locality_class == "repartition_mapmerge"),
        "remote_custom_scan_name": custom_scan_names.most_common(1)[0][0]
        if custom_scan_names
        else "",
        "remote_has_task_list": _bool_text(task_list_available),
        "remote_task_plan_parse_status": parse_status,
        "remote_task_plan_parse_confidence": worker_parse_confidences.most_common(1)[0][0]
        if worker_parse_confidences
        else "",
        "remote_tuple_bytes": max(tuple_bytes) if tuple_bytes else "",
    }


def _region_fragment_row_from_plan_file(
    *,
    root: Path,
    query_sweep_id: str,
    query_run_id: str,
    instance_id: str,
    template_id: str,
    remote_plan_id: str,
    region_id: str,
    source_type: str,
    remote_sql_id: str,
    remote_plan_fingerprint: str,
    plan_file: Path | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "query_sweep_id": query_sweep_id,
        "query_run_id": query_run_id,
        "instance_id": instance_id,
        "template_id": template_id,
        "remote_plan_id": remote_plan_id,
        "region_id": region_id,
        "cluster_id": region_id,
        "source_type": source_type,
        "remote_sql_id": remote_sql_id,
        "parse_status": "failed",
        "parse_confidence": "low",
        "remote_plan_fingerprint": remote_plan_fingerprint,
        "remote_plan_json_file": _rel(root, plan_file),
        "remote_plan_node_count": "",
        "remote_plan_max_depth": "",
        "remote_root_node_type": "",
        "remote_has_custom_scan": "",
        "remote_has_foreign_scan": "",
        "remote_has_aggregate": "",
        "remote_has_sort": "",
        "remote_has_join": "",
        "remote_has_limit": "",
        "remote_has_materialize": "",
        "remote_citus_task_count": "",
        "remote_citus_top_task_count": "",
        "remote_citus_task_count_available": "false",
        "remote_citus_tasks_shown": "",
        "remote_citus_tasks_shown_none": "false",
        "remote_citus_task_list_available": "false",
        "remote_citus_map_merge_job_count": "",
        "remote_citus_dependent_map_task_count_sum": "",
        "remote_citus_dependent_merge_task_count_sum": "",
        "remote_citus_repartition_fanout_ratio": "",
        "remote_citus_tuple_bytes_supported": "",
        "remote_citus_tuple_bytes_source": "",
        "remote_citus_plan_locality_class": "",
        "remote_citus_router_single_task": "false",
        "remote_citus_reference_join_candidate": "false",
        "remote_citus_colocated_join_candidate": "false",
        "remote_citus_repartition_mapmerge": "false",
        "remote_custom_scan_name": "",
        "remote_has_task_list": "false",
        "remote_task_plan_parse_status": "",
        "remote_task_plan_parse_confidence": "",
        "remote_actual_rows": "",
        "remote_plan_rows": "",
        "remote_actual_total_time_ms": "",
        "remote_actual_startup_time_ms": "",
        "remote_plan_width": "",
        "remote_estimated_tuple_bytes": "",
        "remote_temp_blocks_read": "",
        "remote_temp_blocks_written": "",
        "remote_shared_blks_hit": "",
        "remote_shared_blks_read": "",
        "remote_rows_estimate_error_log": "",
        "remote_tuple_bytes_proxy": "",
        "remote_zero_rows_flag": "",
        "remote_nonzero_rows_flag": "",
    }
    if plan_file is None or not plan_file.exists():
        return row
    try:
        value = _load_json_value(plan_file)
        rows = extract_plan_rows(value)
    except (json.JSONDecodeError, ValueError) as error:
        row["parse_error"] = str(error)
        return row
    if not rows:
        row["parse_error"] = "no plan nodes"
        return row

    root_node = rows[0]
    actual_rows = _root_actual_rows(root_node)
    actual_time = _root_actual_time(root_node)
    if actual_time is None and isinstance(value, dict):
        actual_time = _float_or_none(value.get("Auto Explain Duration Ms"))
    plan_rows = _float_or_none(root_node.get("plan_rows"))
    plan_width = _float_or_none(root_node.get("plan_width"))
    estimated_tuple_bytes = _estimate_bytes(plan_rows, plan_width)
    tuple_bytes_proxy = _estimate_bytes(actual_rows, plan_width)
    task_metadata = _citus_task_metadata(value)
    tuple_bytes_supported = (
        str(task_metadata.get("remote_citus_tuple_bytes_supported", "")).lower() != "false"
    )
    tuple_bytes = (
        _float_or_none(task_metadata.get("remote_tuple_bytes")) if tuple_bytes_supported else None
    )
    depths = [
        value for value in (_float_or_none(item.get("depth")) for item in rows) if value is not None
    ]

    row.update(
        {
            "parse_status": "ok",
            "parse_confidence": "high",
            "remote_plan_node_count": len(rows),
            "remote_plan_max_depth": max(depths) if depths else "",
            "remote_root_node_type": root_node.get("node_type", ""),
            "remote_has_custom_scan": _bool_text(
                _has_node_type(rows, lambda node_type: node_type == "Custom Scan")
            ),
            "remote_has_foreign_scan": _bool_text(
                _has_node_type(rows, lambda node_type: node_type == "Foreign Scan")
            ),
            "remote_has_aggregate": _bool_text(
                _has_node_type(rows, lambda node_type: "Aggregate" in node_type)
            ),
            "remote_has_sort": _bool_text(
                _has_node_type(rows, lambda node_type: "Sort" in node_type)
            ),
            "remote_has_join": _bool_text(
                _has_node_type(
                    rows,
                    lambda node_type: "Join" in node_type or node_type == "Nested Loop",
                )
            ),
            "remote_has_limit": _bool_text(
                _has_node_type(rows, lambda node_type: node_type == "Limit")
            ),
            "remote_has_materialize": _bool_text(
                _has_node_type(rows, lambda node_type: node_type == "Materialize")
            ),
            "remote_actual_rows": actual_rows if actual_rows is not None else "",
            "remote_plan_rows": plan_rows if plan_rows is not None else "",
            "remote_actual_total_time_ms": actual_time if actual_time is not None else "",
            "remote_actual_startup_time_ms": _blank_if_none(
                _float_or_none(root_node.get("actual_startup_time"))
            ),
            "remote_plan_width": plan_width if plan_width is not None else "",
            "remote_estimated_tuple_bytes": estimated_tuple_bytes
            if estimated_tuple_bytes is not None
            else "",
            "remote_temp_blocks_read": _blank_if_none(
                _float_or_none(root_node.get("temp_read_blocks"))
            ),
            "remote_temp_blocks_written": _blank_if_none(
                _float_or_none(root_node.get("temp_written_blocks"))
            ),
            "remote_shared_blks_hit": _blank_if_none(
                _float_or_none(root_node.get("shared_hit_blocks"))
            ),
            "remote_shared_blks_read": _blank_if_none(
                _float_or_none(root_node.get("shared_read_blocks"))
            ),
            "remote_rows_estimate_error_log": _rows_estimate_error_log(root_node)
            if _rows_estimate_error_log(root_node) is not None
            else "",
            "remote_tuple_bytes_proxy": tuple_bytes
            if tuple_bytes is not None
            else (
                tuple_bytes_proxy if tuple_bytes_supported and tuple_bytes_proxy is not None else ""
            ),
            "remote_zero_rows_flag": _bool_text(actual_rows == 0.0)
            if actual_rows is not None
            else "",
            "remote_nonzero_rows_flag": _bool_text(actual_rows > 0.0)
            if actual_rows is not None
            else "",
            **{key: value for key, value in task_metadata.items() if key != "remote_tuple_bytes"},
        }
    )
    return row


def _remote_region_aggregates(
    rows: list[dict[str, Any]],
    *,
    expected_regions: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "remote_region_count": "",
        "remote_region_observed_count": "",
        "remote_region_missing_count": "",
        "remote_region_evidence_completeness": "",
        "remote_region_parse_success_count": "",
        "remote_region_parse_partial_count": "",
        "remote_region_rows_available_count": "",
        "remote_region_time_available_count": "",
        "remote_region_task_count_available_count": "",
        "remote_region_actual_rows_sum": "",
        "remote_region_actual_rows_min": "",
        "remote_region_actual_rows_max": "",
        "remote_region_actual_rows_mean": "",
        "remote_region_actual_rows_cv": "",
        "remote_region_actual_rows_max_share": "",
        "remote_region_actual_rows_imbalance_ratio": "",
        "remote_region_actual_rows_min_max_ratio": "",
        "remote_region_actual_rows_active_share": "",
        "remote_region_zero_row_count": "",
        "remote_region_nonzero_count": "",
        "remote_region_actual_time_sum": "",
        "remote_region_actual_time_min": "",
        "remote_region_actual_time_max": "",
        "remote_region_actual_time_mean": "",
        "remote_region_actual_time_cv": "",
        "remote_region_actual_time_max_share": "",
        "remote_region_actual_time_imbalance_ratio": "",
        "remote_region_actual_time_min_max_ratio": "",
        "remote_region_actual_time_active_share": "",
        "remote_region_tuple_bytes_sum": "",
        "remote_region_tuple_bytes_min": "",
        "remote_region_tuple_bytes_max": "",
        "remote_region_tuple_bytes_mean": "",
        "remote_region_tuple_bytes_cv": "",
        "remote_region_tuple_bytes_max_share": "",
        "remote_region_tuple_bytes_imbalance_ratio": "",
        "remote_region_tuple_bytes_min_max_ratio": "",
        "remote_region_tuple_bytes_active_share": "",
        "remote_region_task_count_sum": "",
        "remote_region_task_count_min": "",
        "remote_region_task_count_max": "",
        "remote_region_task_count_mean": "",
        "remote_region_task_count_cv": "",
        "remote_region_task_count_max_share": "",
        "remote_region_task_count_imbalance_ratio": "",
        "remote_region_task_count_min_max_ratio": "",
        "remote_region_task_count_active_share": "",
        "regional_temp_evidence_region_count": "",
        "regional_temp_read_blocks_sum": "",
        "regional_temp_read_blocks_max": "",
        "regional_temp_written_blocks_sum": "",
        "regional_temp_written_blocks_max": "",
        "regional_spill_region_count": "",
        "regional_spill_present": "",
        "remote_region_plan_fingerprint_count": "",
        "remote_region_plan_fingerprint_all_same": "",
        "remote_region_dominant_plan_fingerprint_share": "",
        "remote_citus_tasks_shown_none_count": "",
        "remote_citus_task_list_available_count": "",
        "remote_citus_tuple_bytes_unsupported_count": "",
        "remote_citus_map_merge_job_count_sum": "",
        "remote_citus_dependent_map_task_count_sum": "",
        "remote_citus_dependent_merge_task_count_sum": "",
        "remote_citus_repartition_fanout_ratio_max": "",
        "remote_citus_router_single_task_count": "",
        "remote_citus_reference_join_candidate_count": "",
        "remote_citus_colocated_join_candidate_count": "",
        "remote_citus_repartition_mapmerge_count": "",
        "remote_citus_plan_locality_classes": "",
        "remote_citus_dominant_plan_locality_class": "",
    }
    observed_regions = sorted(
        {str(row.get("region_id", "")) for row in rows if str(row.get("region_id", "")).strip()}
    )
    if not expected_regions:
        expected_regions = observed_regions
    expected_unique = sorted({region for region in expected_regions if region})
    expected_count = len(expected_unique)
    observed_count = len(observed_regions)
    if expected_count or observed_count:
        result["remote_region_count"] = expected_count if expected_count else observed_count
        result["remote_region_observed_count"] = observed_count
        result["remote_region_missing_count"] = max(expected_count - observed_count, 0)
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

    rows_by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
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

    regional_temp_read: list[float] = []
    regional_temp_written: list[float] = []
    regional_spill_region_count = 0
    for region_rows in rows_by_region.values():
        read_values = [
            value
            for value in (
                _float_or_none(row.get("remote_temp_blocks_read")) for row in region_rows
            )
            if value is not None
        ]
        written_values = [
            value
            for value in (
                _float_or_none(row.get("remote_temp_blocks_written"))
                for row in region_rows
            )
            if value is not None
        ]
        if not read_values and not written_values:
            continue
        read_sum = sum(read_values)
        written_sum = sum(written_values)
        regional_temp_read.append(read_sum)
        regional_temp_written.append(written_sum)
        if read_sum > 0.0 or written_sum > 0.0:
            regional_spill_region_count += 1

    result["remote_region_rows_available_count"] = len(actual_rows)
    result["remote_region_time_available_count"] = len(actual_times)
    result["remote_region_task_count_available_count"] = len(task_counts)
    result["remote_region_zero_row_count"] = sum(1 for value in actual_rows if value == 0.0)
    result["remote_region_nonzero_count"] = sum(1 for value in actual_rows if value > 0.0)

    populate("remote_region_actual_rows", actual_rows)
    populate("remote_region_actual_time", actual_times)
    populate("remote_region_tuple_bytes", tuple_bytes)
    populate("remote_region_task_count", task_counts)
    if regional_temp_read or regional_temp_written:
        result["regional_temp_evidence_region_count"] = max(
            len(regional_temp_read),
            len(regional_temp_written),
        )
        result["regional_temp_read_blocks_sum"] = sum(regional_temp_read)
        result["regional_temp_read_blocks_max"] = max(regional_temp_read, default=0.0)
        result["regional_temp_written_blocks_sum"] = sum(regional_temp_written)
        result["regional_temp_written_blocks_max"] = max(
            regional_temp_written,
            default=0.0,
        )
        result["regional_spill_region_count"] = regional_spill_region_count
        result["regional_spill_present"] = _bool_text(regional_spill_region_count > 0)

    def truthy_count(column: str) -> int:
        return sum(1 for row in rows if str(row.get(column, "")).lower() == "true")

    def false_count(column: str) -> int:
        return sum(1 for row in rows if str(row.get(column, "")).lower() == "false")

    map_merge_counts = [
        value
        for value in (_float_or_none(row.get("remote_citus_map_merge_job_count")) for row in rows)
        if value is not None
    ]
    map_task_counts = [
        value
        for value in (
            _float_or_none(row.get("remote_citus_dependent_map_task_count_sum")) for row in rows
        )
        if value is not None
    ]
    merge_task_counts = [
        value
        for value in (
            _float_or_none(row.get("remote_citus_dependent_merge_task_count_sum")) for row in rows
        )
        if value is not None
    ]
    fanout_ratios = [
        value
        for value in (
            _float_or_none(row.get("remote_citus_repartition_fanout_ratio")) for row in rows
        )
        if value is not None
    ]
    locality_classes = [
        str(row.get("remote_citus_plan_locality_class", ""))
        for row in rows
        if str(row.get("remote_citus_plan_locality_class", "")).strip()
    ]
    result["remote_citus_tasks_shown_none_count"] = truthy_count("remote_citus_tasks_shown_none")
    result["remote_citus_task_list_available_count"] = truthy_count(
        "remote_citus_task_list_available"
    )
    result["remote_citus_tuple_bytes_unsupported_count"] = false_count(
        "remote_citus_tuple_bytes_supported"
    )
    if map_merge_counts:
        result["remote_citus_map_merge_job_count_sum"] = sum(map_merge_counts)
    if map_task_counts:
        result["remote_citus_dependent_map_task_count_sum"] = sum(map_task_counts)
    if merge_task_counts:
        result["remote_citus_dependent_merge_task_count_sum"] = sum(merge_task_counts)
    if fanout_ratios:
        result["remote_citus_repartition_fanout_ratio_max"] = max(fanout_ratios)
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
        result["remote_region_plan_fingerprint_all_same"] = _bool_text(len(counts) == 1)
        result["remote_region_dominant_plan_fingerprint_share"] = max(counts.values()) / len(
            region_plan_signatures
        )
    return result


def _expected_remote_regions_for_query(
    *,
    query_row: dict[str, Any],
    configured_regions: list[str],
    observed_region_rows: list[dict[str, Any]],
) -> list[str]:
    """Return strategy-aware region expectations for remote evidence completeness."""
    strategy = str(query_row.get("execution_strategy", ""))
    if strategy == "multiregion_union":
        return configured_regions
    if observed_region_rows:
        return []
    return []


def _task_skew_summary(plan_files: list[Path | None]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "task_count": "",
        "task_time_min_ms": "",
        "task_time_max_ms": "",
        "task_time_mean_ms": "",
        "task_time_cv": "",
        "task_rows_min": "",
        "task_rows_max": "",
        "task_rows_mean": "",
        "task_rows_cv": "",
        "worker_task_count_cv": "",
        "worker_rows_cv": "",
        "worker_time_cv": "",
    }
    task_count = 0
    tasks: list[Any] = []
    for plan_file in plan_files:
        if plan_file is None or not plan_file.exists():
            continue
        try:
            value = _load_json_value(plan_file)
        except (json.JSONDecodeError, ValueError):
            continue
        for explicit_count, group_tasks in _iter_citus_task_groups(value):
            task_count += explicit_count if explicit_count is not None else len(group_tasks)
            tasks.extend(group_tasks)

    if task_count:
        result["task_count"] = task_count
    if not tasks:
        return result

    task_times: list[float] = []
    task_rows: list[float] = []
    worker_task_counts: dict[str, int] = defaultdict(int)
    worker_rows: dict[str, float] = defaultdict(float)
    worker_times: dict[str, float] = defaultdict(float)

    for task in tasks:
        worker = _task_worker(task)
        if worker:
            worker_task_counts[worker] += 1
        plan_node = _first_plan_node(task)
        if plan_node is None:
            continue
        actual_time = _float_or_none(plan_node.get("Actual Total Time"))
        actual_rows = _float_or_none(plan_node.get("Actual Rows"))
        if actual_time is not None:
            task_times.append(actual_time)
            if worker:
                worker_times[worker] += actual_time
        if actual_rows is not None:
            task_rows.append(actual_rows)
            if worker:
                worker_rows[worker] += actual_rows

    if task_times:
        result.update(
            {
                "task_time_min_ms": min(task_times),
                "task_time_max_ms": max(task_times),
                "task_time_mean_ms": statistics.fmean(task_times),
                "task_time_cv": _cv_or_none(task_times),
            }
        )
    if task_rows:
        result.update(
            {
                "task_rows_min": min(task_rows),
                "task_rows_max": max(task_rows),
                "task_rows_mean": statistics.fmean(task_rows),
                "task_rows_cv": _cv_or_none(task_rows),
            }
        )
    worker_task_count_cv = _cv_or_none([float(value) for value in worker_task_counts.values()])
    if worker_task_count_cv is not None:
        result["worker_task_count_cv"] = worker_task_count_cv
    worker_rows_cv = _cv_or_none(list(worker_rows.values()))
    if worker_rows_cv is not None:
        result["worker_rows_cv"] = worker_rows_cv
    worker_time_cv = _cv_or_none(list(worker_times.values()))
    if worker_time_cv is not None:
        result["worker_time_cv"] = worker_time_cv
    return result


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _dominant(values: list[str]) -> str:
    non_empty = [value for value in values if value]
    if not non_empty:
        return ""
    counts = Counter(non_empty)
    max_count = max(counts.values())
    return sorted(value for value, count in counts.items() if count == max_count)[0]


def _dominant_column(rows: list[dict[str, Any]], column: str) -> str:
    return _dominant([str(row.get(column, "")) for row in rows])


def _numeric_column(rows: list[dict[str, Any]], column: str) -> list[float]:
    return [
        value for value in (_float_or_none(row.get(column)) for row in rows) if value is not None
    ]


def _mean_or_none(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _max_or_none(values: list[float]) -> float | None:
    return max(values) if values else None


def _abs_max_or_none(values: list[float]) -> float | None:
    value = _largest_abs_signed(values)
    return abs(value) if value is not None else None


def _is_failed_query_run(row: dict[str, Any]) -> bool:
    execution_status = str(row.get("execution_status", "")).strip().lower()
    if execution_status in {"failed", "timeout"}:
        return True
    if _int_or_zero(row.get("collection_error_count")) > 0:
        return True
    if _int_or_zero(row.get("remote_error_count")) > 0:
        return True
    if str(row.get("main_plan_parse_error", "")).strip():
        return True
    probe_status = str(row.get("fdw_remote_probe_status", "")).strip().lower()
    return probe_status in {"error", "failed"}


def _instance_summary_rows(
    *, query_sweep_id: str, query_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in query_rows:
        grouped[(str(row.get("template_id", "")), str(row.get("instance_id", "")))].append(row)

    summary_rows: list[dict[str, Any]] = []
    for (template_id, instance_id), rows in sorted(grouped.items()):
        elapsed = [
            value
            for value in (_float_or_none(row.get("elapsed_seconds")) for row in rows)
            if value is not None
        ]
        failures = sum(1 for row in rows if _is_failed_query_run(row))
        timeouts = sum(
            1 for row in rows if str(row.get("execution_status", "")).strip().lower() == "timeout"
        )
        plan_fingerprints = [str(row.get("plan_fingerprint", "")) for row in rows]
        remote_plan_fingerprints = [str(row.get("remote_plan_fingerprint", "")) for row in rows]
        run_orders = [
            value
            for value in (_float_or_none(row.get("run_order")) for row in rows)
            if value is not None
        ]
        main_root_widths = _numeric_column(rows, "main_root_plan_width")
        estimated_result_bytes = _numeric_column(rows, "estimated_result_bytes")
        estimated_remote_output_bytes = _numeric_column(rows, "estimated_remote_output_bytes")
        estimated_fanin_bytes = _numeric_column(rows, "estimated_fanin_bytes")
        foreign_scan_estimate_errors = _numeric_column(rows, "foreign_scan_rows_estimate_error_log")
        aggregate_estimate_errors = _numeric_column(rows, "aggregate_rows_estimate_error_log")
        join_estimate_errors = _numeric_column(rows, "join_rows_estimate_error_log")
        sort_estimate_errors = _numeric_column(rows, "sort_rows_estimate_error_log")
        remote_root_estimate_errors = _numeric_column(rows, "remote_root_rows_estimate_error_log")
        task_counts = _numeric_column(rows, "task_count")
        task_time_means = _numeric_column(rows, "task_time_mean_ms")
        task_time_cvs = _numeric_column(rows, "task_time_cv")
        task_rows_means = _numeric_column(rows, "task_rows_mean")
        task_rows_cvs = _numeric_column(rows, "task_rows_cv")
        worker_task_count_cvs = _numeric_column(rows, "worker_task_count_cv")
        worker_rows_cvs = _numeric_column(rows, "worker_rows_cv")
        worker_time_cvs = _numeric_column(rows, "worker_time_cv")
        mean = statistics.fmean(elapsed) if elapsed else None
        std = statistics.pstdev(elapsed) if len(elapsed) > 1 else (0.0 if elapsed else None)
        summary_rows.append(
            {
                "query_sweep_id": query_sweep_id,
                "template_id": template_id,
                "instance_id": instance_id,
                "query_run_count": len(rows),
                "measurement_count": len(elapsed),
                "successful_run_count": len(rows) - failures,
                "failed_run_count": failures,
                "timeout_run_count": timeouts,
                "failure_rate": failures / len(rows) if rows else None,
                "execution_time_mean": mean,
                "execution_time_median": statistics.median(elapsed) if elapsed else None,
                "execution_time_p95": _p95(elapsed),
                "execution_time_std": std,
                "execution_time_cv": (std / mean) if mean and std is not None else None,
                "plan_fingerprint_count": len({value for value in plan_fingerprints if value}),
                "dominant_plan_fingerprint": _dominant(plan_fingerprints),
                "remote_plan_fingerprint_count": len(
                    {value for value in remote_plan_fingerprints if value}
                ),
                "dominant_remote_plan_fingerprint": _dominant(remote_plan_fingerprints),
                "first_run_order": min(run_orders) if run_orders else None,
                "last_run_order": max(run_orders) if run_orders else None,
                "distribution_key": _dominant_column(rows, "distribution_key"),
                "filter_uses_distribution_key": _dominant_column(
                    rows, "filter_uses_distribution_key"
                ),
                "join_uses_distribution_key": _dominant_column(rows, "join_uses_distribution_key"),
                "group_by_uses_distribution_key": _dominant_column(
                    rows, "group_by_uses_distribution_key"
                ),
                "order_by_uses_distribution_key": _dominant_column(
                    rows, "order_by_uses_distribution_key"
                ),
                "tenant_filter_present": _dominant_column(rows, "tenant_filter_present"),
                "single_tenant_scope": _dominant_column(rows, "single_tenant_scope"),
                "multi_tenant_scope": _dominant_column(rows, "multi_tenant_scope"),
                "distribution_key_usage_source": _dominant_column(
                    rows, "distribution_key_usage_source"
                ),
                "main_root_plan_width_mean": _mean_or_none(main_root_widths),
                "main_root_plan_width_max": _max_or_none(main_root_widths),
                "estimated_result_bytes_mean": _mean_or_none(estimated_result_bytes),
                "estimated_result_bytes_max": _max_or_none(estimated_result_bytes),
                "estimated_remote_output_bytes_mean": _mean_or_none(estimated_remote_output_bytes),
                "estimated_remote_output_bytes_max": _max_or_none(estimated_remote_output_bytes),
                "estimated_fanin_bytes_mean": _mean_or_none(estimated_fanin_bytes),
                "estimated_fanin_bytes_max": _max_or_none(estimated_fanin_bytes),
                "dominant_result_width_class": _dominant_column(rows, "result_width_class"),
                "foreign_scan_rows_estimate_error_log_mean": _mean_or_none(
                    foreign_scan_estimate_errors
                ),
                "foreign_scan_rows_estimate_error_abs_max": _abs_max_or_none(
                    foreign_scan_estimate_errors
                ),
                "aggregate_rows_estimate_error_log_mean": _mean_or_none(aggregate_estimate_errors),
                "aggregate_rows_estimate_error_abs_max": _abs_max_or_none(
                    aggregate_estimate_errors
                ),
                "join_rows_estimate_error_log_mean": _mean_or_none(join_estimate_errors),
                "join_rows_estimate_error_abs_max": _abs_max_or_none(join_estimate_errors),
                "sort_rows_estimate_error_log_mean": _mean_or_none(sort_estimate_errors),
                "sort_rows_estimate_error_abs_max": _abs_max_or_none(sort_estimate_errors),
                "remote_root_rows_estimate_error_log_mean": _mean_or_none(
                    remote_root_estimate_errors
                ),
                "remote_root_rows_estimate_error_abs_max": _abs_max_or_none(
                    remote_root_estimate_errors
                ),
                "task_count_mean": _mean_or_none(task_counts),
                "task_count_max": _max_or_none(task_counts),
                "task_time_mean_ms_mean": _mean_or_none(task_time_means),
                "task_time_cv_mean": _mean_or_none(task_time_cvs),
                "task_time_cv_max": _max_or_none(task_time_cvs),
                "task_rows_mean_mean": _mean_or_none(task_rows_means),
                "task_rows_cv_mean": _mean_or_none(task_rows_cvs),
                "task_rows_cv_max": _max_or_none(task_rows_cvs),
                "worker_task_count_cv_mean": _mean_or_none(worker_task_count_cvs),
                "worker_task_count_cv_max": _max_or_none(worker_task_count_cvs),
                "worker_rows_cv_mean": _mean_or_none(worker_rows_cvs),
                "worker_rows_cv_max": _max_or_none(worker_rows_cvs),
                "worker_time_cv_mean": _mean_or_none(worker_time_cvs),
                "worker_time_cv_max": _max_or_none(worker_time_cvs),
            }
        )
    return summary_rows


def _append_plan_nodes(
    *,
    root: Path,
    rows: list[dict[str, Any]],
    edge_rows: list[dict[str, Any]],
    query_sweep_id: str,
    query_run_id: str,
    instance_id: str,
    template_id: str,
    plan_scope: str,
    plan_id: str,
    plan_file: Path | None,
    remote_sql_id: str = "",
    fdw_region: str = "",
    fdw_schema: str = "",
) -> None:
    if plan_file is None or not plan_file.exists():
        return
    value = _load_json_value(plan_file)
    context: dict[str, Any] = {
        "query_sweep_id": query_sweep_id,
        "query_run_id": query_run_id,
        "instance_id": instance_id,
        "template_id": template_id,
        "plan_scope": plan_scope,
        "plan_id": plan_id,
        "parent_plan_id": plan_id,
        "remote_sql_id": remote_sql_id,
        "fdw_region": fdw_region,
        "fdw_schema": fdw_schema,
        "plan_json_file": _rel(root, plan_file),
        "citus_task_index": "",
        "citus_task_worker": "",
    }
    _append_plan_value_nodes(rows=rows, edge_rows=edge_rows, value=value, context=context)
    for task_index, worker, task_plan in _iter_citus_task_remote_plans(value):
        task_context = {
            **context,
            "plan_scope": "citus_task_remote",
            "plan_id": f"{plan_id}:task_{task_index:03d}",
            "citus_task_index": task_index,
            "citus_task_worker": worker,
        }
        _append_plan_value_nodes(
            rows=rows,
            edge_rows=edge_rows,
            value=task_plan,
            context=task_context,
        )


def _append_plan_value_nodes(
    *,
    rows: list[dict[str, Any]],
    edge_rows: list[dict[str, Any]],
    value: Any,
    context: dict[str, Any],
) -> None:
    plan_nodes = extract_plan_rows(value)
    nodes_by_id = {node["node_id"]: node for node in plan_nodes}
    for node in plan_nodes:
        enriched = {
            **context,
        }
        enriched.update(node)
        rows.append(enriched)
        parent_id = node.get("parent_node_id")
        if parent_id in ("", None):
            continue
        parent = nodes_by_id.get(parent_id)
        if parent is None:
            continue
        edge_rows.append(
            {
                **context,
                "parent_node_id": parent_id,
                "child_node_id": node.get("node_id", ""),
                "parent_node_type": parent.get("node_type", ""),
                "child_node_type": node.get("node_type", ""),
                "child_index": node.get("child_index", ""),
                "parent_depth": parent.get("depth", ""),
                "child_depth": node.get("depth", ""),
                "parent_node_path": parent.get("node_path", ""),
                "child_node_path": node.get("node_path", ""),
                "edge_type": "plan_parent_child",
            }
        )


def index_query_sweep(*, sweep_dir: Path, out_dir: Path | None = None) -> Path:
    root = sweep_dir.resolve()
    if out_dir is None:
        out_dir = root / "_index"
    else:
        out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sweep_manifest = _load_json(root / "query_sweep_manifest.json")
    sweep_id = str(sweep_manifest["sweep_id"])

    query_rows: list[dict[str, Any]] = []
    binding_rows: list[dict[str, Any]] = []
    node_rows: list[dict[str, Any]] = []
    plan_file_rows: list[dict[str, Any]] = []
    plan_node_rows: list[dict[str, Any]] = []
    plan_edge_rows: list[dict[str, Any]] = []
    plan_structure_rows: list[dict[str, Any]] = []
    remote_plan_rows: list[dict[str, Any]] = []
    region_fragment_rows: list[dict[str, Any]] = []
    worker_task_rows: list[dict[str, Any]] = []
    remote_edge_rows: list[dict[str, Any]] = []
    instance_seen_counts: dict[str, int] = {}
    instance_last_finished_at: dict[str, float] = {}

    for execution_index, execution in enumerate(sweep_manifest.get("executions", []), start=1):
        collection_dir = Path(str(execution["collection_dir"])).resolve()
        collection_manifest = _load_json(collection_dir / "execution_manifest.json")
        query_run_id = str(collection_manifest["execution_id"])
        timeout_payload = collection_manifest.get("timeout") or {}
        execution_status = str(
            collection_manifest.get("execution_status")
            or execution.get("execution_status")
            or "completed"
        )
        instance_id = str(execution.get("instance_id", ""))
        template_id = str(execution.get("template_id", ""))
        params = execution.get("params", {})
        coordinator, node_dir, remote_manifest = _first_node_artifact(
            collection_dir,
            collection_manifest,
        )

        query_bindings_file = collection_dir / "input" / "query_bindings.json"
        query_sql_file = collection_dir / "input" / "query.sql"
        query_sql_text = _read_text(query_sql_file)
        sql_hashes = _sql_hashes(query_sql_file, str(execution.get("rendered_sql_path", "")))
        distribution_metadata = {
            "distribution_key_usage": _first_value(
                execution.get("distribution_key_usage"),
                collection_manifest.get("distribution_key_usage"),
                {},
            )
        }
        distribution_usage = _distribution_key_usage(
            sql_text=query_sql_text,
            params=params if isinstance(params, dict) else {},
            metadata=distribution_metadata,
            distribution_key=str(
                _first_value(
                    execution.get("distribution_key"),
                    collection_manifest.get("distribution_key"),
                    sweep_manifest.get("distribution_key"),
                    "tenant_id",
                )
            ),
        )
        bindings = _load_bindings(query_bindings_file)
        collection_execution_metadata = collection_manifest.get("execution_metadata", {})
        if not isinstance(collection_execution_metadata, dict):
            collection_execution_metadata = {}
        binding_execution_metadata = bindings.get("execution_metadata", {})
        if not isinstance(binding_execution_metadata, dict):
            binding_execution_metadata = {}
        timing = remote_manifest.get("timing", {}) if remote_manifest else {}
        probe = remote_manifest.get("fdw_remote_plan_probe", {}) if remote_manifest else {}
        fdw_auto_explain = (
            collection_manifest.get("fdw_auto_explain", {})
            if isinstance(collection_manifest.get("fdw_auto_explain", {}), dict)
            else {}
        )
        fdw_auto_explain_hosts = fdw_auto_explain.get("regional_hosts", {})
        if not isinstance(fdw_auto_explain_hosts, dict):
            fdw_auto_explain_hosts = {}
        fdw_auto_explain_log_files: list[str] = []
        fdw_auto_explain_observed_regions: list[str] = []
        for host_payload in fdw_auto_explain_hosts.values():
            if not isinstance(host_payload, dict):
                continue
            local_log_file = str(host_payload.get("local_log_file", ""))
            if local_log_file:
                fdw_auto_explain_log_files.append(_rel(root, collection_dir / local_log_file))
            try:
                captured_lines = int(host_payload.get("captured_lines", 0) or 0)
            except (TypeError, ValueError):
                captured_lines = 0
            region = str(host_payload.get("region", ""))
            if captured_lines > 0 and region:
                fdw_auto_explain_observed_regions.append(region)
        run_order = _first_value(
            execution.get("run_order"),
            collection_manifest.get("run_order"),
            remote_manifest.get("run_order") if remote_manifest else "",
            execution_index,
        )
        repetition_index = _first_value(
            execution.get("repetition_index"),
            collection_manifest.get("repetition_index"),
            remote_manifest.get("repetition_index") if remote_manifest else "",
            instance_seen_counts.get(instance_id, 0),
        )
        warmup_run_flag = _first_value(
            execution.get("warmup_run_flag"),
            collection_manifest.get("warmup_run_flag"),
            remote_manifest.get("warmup_run_flag") if remote_manifest else "",
            False,
        )
        cache_policy = _first_value(
            execution.get("cache_policy"),
            collection_manifest.get("cache_policy"),
            remote_manifest.get("cache_policy") if remote_manifest else "",
            sweep_manifest.get("cache_policy"),
            "natural",
        )

        main_plan_file = (
            _path_from(node_dir, str(remote_manifest.get("plan_file", "")))
            if node_dir is not None
            else None
        )
        main_summary = _plan_summary(main_plan_file)
        main_explain_text_path = (
            _path_from(node_dir, str(remote_manifest.get("explain_text_file", "")))
            if node_dir is not None
            else None
        )
        citus_text_summary = _citus_text_plan_summary(_read_text(main_explain_text_path))
        plan_node_start = len(plan_node_rows)
        plan_edge_start = len(plan_edge_rows)
        plan_file_start = len(plan_file_rows)
        region_fragment_start = len(region_fragment_rows)
        worker_task_start = len(worker_task_rows)
        remote_plan_fingerprints: list[dict[str, str]] = []
        remote_plan_files: list[Path] = []
        query_started_at = timing.get("query_started_at_unix", "")
        previous_gap_seconds = ""
        try:
            started_at_float = float(query_started_at)
            previous_finished_at = instance_last_finished_at.get(instance_id)
            if previous_finished_at is not None:
                previous_gap_seconds = max(0.0, started_at_float - previous_finished_at)
        except (TypeError, ValueError):
            started_at_float = None

        query_rows.append(
            {
                "query_sweep_id": sweep_id,
                "query_run_id": query_run_id,
                "attempt_id": collection_manifest.get(
                    "attempt_id",
                    collection_manifest.get("execution_id", ""),
                ),
                "execution_status": execution_status,
                "timed_out": bool(
                    collection_manifest.get("timed_out") or execution.get("timed_out")
                ),
                "hard_timeout_seconds": collection_manifest.get(
                    "hard_timeout_seconds", execution.get("hard_timeout_seconds", "")
                ),
                "timeout_phase": collection_manifest.get(
                    "timeout_phase",
                    execution.get("timeout_phase", timeout_payload.get("phase", "")),
                ),
                **{
                    field: _metadata_text(
                        _first_value(
                            execution.get(field),
                            collection_execution_metadata.get(field),
                            binding_execution_metadata.get(field),
                            "",
                        )
                    )
                    for field in CORPUS_METADATA_FIELDS
                },
                "instance_id": instance_id,
                "template_id": template_id,
                "sql_normalized_hash": sql_hashes["sql_normalized_hash"],
                "rendered_sql_hash": sql_hashes["rendered_sql_hash"],
                "plan_fingerprint": main_summary["plan_fingerprint"],
                "remote_plan_fingerprint": "",
                "remote_plan_fingerprints_json": "",
                "param_json": _json_text(params),
                "expected_shape_tags": execution.get("expected_shape_tags", ""),
                "collection_dir": _rel(root, collection_dir),
                "source_sql_file": execution.get("rendered_sql_path", ""),
                "query_sql_file": _rel(root, query_sql_file),
                "query_bindings_file": _rel(root, query_bindings_file),
                "coordinator_node": coordinator,
                "created_at_utc": collection_manifest.get("created_at_utc", ""),
                "elapsed_seconds": timing.get("elapsed_seconds", ""),
                "query_started_at_unix": timing.get("query_started_at_unix", ""),
                "query_finished_at_unix": timing.get("query_finished_at_unix", ""),
                "repetition_index": repetition_index,
                "run_order": run_order,
                "warmup_run_flag": warmup_run_flag,
                "cache_policy": cache_policy,
                "same_instance_previous_execution_gap_seconds": previous_gap_seconds,
                **_os_network_summary(collection_dir, collection_manifest),
                **_result_signature_summary(collection_dir, collection_manifest),
                **_buffer_audit_summary(main_plan_file),
                **distribution_usage,
                "main_root_plan_width": "",
                "foreign_scan_plan_width_sum": "",
                "foreign_scan_plan_width_max": "",
                "remote_root_plan_width_sum": "",
                "remote_root_plan_width_max": "",
                "estimated_result_bytes": "",
                "estimated_remote_output_bytes": "",
                "estimated_fanin_bytes": "",
                "result_width_class": "",
                "foreign_scan_rows_estimate_error_log": "",
                "aggregate_rows_estimate_error_log": "",
                "join_rows_estimate_error_log": "",
                "sort_rows_estimate_error_log": "",
                "remote_root_rows_estimate_error_log": "",
                "task_count": "",
                "task_time_min_ms": "",
                "task_time_max_ms": "",
                "task_time_mean_ms": "",
                "task_time_cv": "",
                "task_rows_min": "",
                "task_rows_max": "",
                "task_rows_mean": "",
                "task_rows_cv": "",
                "worker_task_count_cv": "",
                "worker_rows_cv": "",
                "worker_time_cv": "",
                "remote_region_count": "",
                "regional_remote_plan_count": "",
                "regional_internal_plan_count": "",
                "regional_plan_evidence_status": "",
                "remote_region_observed_count": "",
                "remote_region_missing_count": "",
                "remote_region_evidence_completeness": "",
                "remote_region_parse_success_count": "",
                "remote_region_parse_partial_count": "",
                "remote_region_rows_available_count": "",
                "remote_region_time_available_count": "",
                "remote_region_task_count_available_count": "",
                "remote_region_actual_rows_sum": "",
                "remote_region_actual_rows_min": "",
                "remote_region_actual_rows_max": "",
                "remote_region_actual_rows_mean": "",
                "remote_region_actual_rows_cv": "",
                "remote_region_actual_rows_max_share": "",
                "remote_region_actual_rows_imbalance_ratio": "",
                "remote_region_actual_rows_min_max_ratio": "",
                "remote_region_actual_rows_active_share": "",
                "remote_region_zero_row_count": "",
                "remote_region_nonzero_count": "",
                "remote_region_actual_time_sum": "",
                "remote_region_actual_time_min": "",
                "remote_region_actual_time_max": "",
                "remote_region_actual_time_mean": "",
                "remote_region_actual_time_cv": "",
                "remote_region_actual_time_max_share": "",
                "remote_region_actual_time_imbalance_ratio": "",
                "remote_region_actual_time_min_max_ratio": "",
                "remote_region_actual_time_active_share": "",
                "remote_region_tuple_bytes_sum": "",
                "remote_region_tuple_bytes_min": "",
                "remote_region_tuple_bytes_max": "",
                "remote_region_tuple_bytes_mean": "",
                "remote_region_tuple_bytes_cv": "",
                "remote_region_tuple_bytes_max_share": "",
                "remote_region_tuple_bytes_imbalance_ratio": "",
                "remote_region_tuple_bytes_min_max_ratio": "",
                "remote_region_tuple_bytes_active_share": "",
                "remote_region_task_count_sum": "",
                "remote_region_task_count_min": "",
                "remote_region_task_count_max": "",
                "remote_region_task_count_mean": "",
                "remote_region_task_count_cv": "",
                "remote_region_task_count_max_share": "",
                "remote_region_task_count_imbalance_ratio": "",
                "remote_region_task_count_min_max_ratio": "",
                "remote_region_task_count_active_share": "",
                "regional_temp_evidence_region_count": "",
                "regional_temp_read_blocks_sum": "",
                "regional_temp_read_blocks_max": "",
                "regional_temp_written_blocks_sum": "",
                "regional_temp_written_blocks_max": "",
                "regional_spill_region_count": "",
                "regional_spill_present": "",
                "remote_region_plan_fingerprint_count": "",
                "remote_region_plan_fingerprint_all_same": "",
                "remote_region_dominant_plan_fingerprint_share": "",
                "remote_citus_tasks_shown_none_count": "",
                "remote_citus_task_list_available_count": "",
                "remote_citus_tuple_bytes_unsupported_count": "",
                "remote_citus_map_merge_job_count_sum": "",
                "remote_citus_dependent_map_task_count_sum": "",
                "remote_citus_dependent_merge_task_count_sum": "",
                "remote_citus_repartition_fanout_ratio_max": "",
                "remote_citus_router_single_task_count": "",
                "remote_citus_reference_join_candidate_count": "",
                "remote_citus_colocated_join_candidate_count": "",
                "remote_citus_repartition_mapmerge_count": "",
                "remote_citus_plan_locality_classes": "",
                "remote_citus_dominant_plan_locality_class": "",
                "citus_repartition_observed_v2": "",
                "worker_task_plan_count": "",
                "worker_task_evidence_status": "",
                "worker_task_plan_format": "",
                "worker_task_timing_status": "",
                "worker_task_parse_ok_count": "",
                "worker_task_parse_partial_count": "",
                "worker_task_parse_failed_count": "",
                "worker_task_actual_rows_sum": "",
                "worker_task_actual_rows_min": "",
                "worker_task_actual_rows_max": "",
                "worker_task_actual_rows_cv": "",
                "worker_task_actual_rows_max_share": "",
                "worker_task_root_rows_isf": "",
                "worker_task_scan_actual_rows_sum": "",
                "worker_task_scan_actual_rows_min": "",
                "worker_task_scan_actual_rows_max": "",
                "worker_task_scan_actual_rows_cv": "",
                "worker_task_scan_actual_rows_max_share": "",
                "worker_task_scan_rows_isf": "",
                "worker_task_actual_time_sum": "",
                "worker_task_actual_time_min": "",
                "worker_task_actual_time_max": "",
                "worker_task_actual_time_cv": "",
                "worker_task_actual_time_max_share": "",
                "worker_task_scan_type_counts_json": "",
                "worker_task_index_scan_share": "",
                "worker_task_seq_scan_share": "",
                "worker_task_bitmap_scan_share": "",
                "worker_task_node_type_counts_json": "",
                "worker_task_node_type_unknown_count": "",
                "worker_task_node_type_unknown_set_json": "",
                "worker_task_node_count_sum": "",
                "worker_task_plan_max_depth_max": "",
                "worker_task_plan_max_depth_mean": "",
                "worker_task_join_node_count": "",
                "worker_task_aggregate_node_count": "",
                "worker_task_sort_node_count": "",
                "worker_task_blocking_node_count": "",
                "worker_task_scan_node_count": "",
                "worker_task_materialization_node_count": "",
                "worker_task_parallel_node_count": "",
                "worker_task_bitmap_node_count": "",
                "worker_task_index_access_node_count": "",
                "worker_task_sequential_access_node_count": "",
                "worker_task_spill_capable_node_count": "",
                "worker_task_has_join": "",
                "worker_task_has_aggregate": "",
                "worker_task_has_sort": "",
                "worker_task_has_blocking_operator": "",
                "worker_task_has_parallel_operator": "",
                "worker_task_has_hash": "",
                "worker_task_has_materialize": "",
                "worker_task_plan_fingerprint_count": "",
                "worker_task_plan_fingerprint_dominant_share": "",
                "worker_task_spill_count": "",
                "worker_task_shared_hit_sum": "",
                "worker_task_shared_read_sum": "",
                "worker_task_temp_read_sum": "",
                "worker_task_temp_written_sum": "",
                "worker_task_region_count": "",
                "worker_task_region_task_count_cv": "",
                "worker_task_region_rows_cv": "",
                "worker_task_region_rows_max_share": "",
                "worker_task_region_scan_rows_cv": "",
                "worker_task_region_scan_rows_max_share": "",
                "worker_task_within_region_rows_cv_max": "",
                "worker_task_within_region_rows_cv_mean": "",
                "worker_task_within_region_rows_max_share_max": "",
                "worker_task_within_region_scan_rows_cv_max": "",
                "worker_task_within_region_scan_rows_cv_mean": "",
                "worker_task_within_region_scan_rows_max_share_max": "",
                "worker_task_within_region_scan_rows_isf_max": "",
                "worker_task_within_region_plan_fingerprint_count_max": "",
                "worker_task_within_region_plan_fingerprint_count_mean": "",
                "main_plan_json_file": _rel(root, main_plan_file),
                "main_explain_text_file": _rel(root, main_explain_text_path),
                **citus_text_summary,
                "main_plan_node_count": main_summary["plan_node_count"],
                "main_has_foreign_scan": main_summary["has_foreign_scan"],
                "main_has_remote_sql": main_summary["has_remote_sql"],
                "main_plan_parse_error": main_summary["plan_parse_error"],
                "fdw_remote_probe_enabled": probe.get("enabled", ""),
                "fdw_remote_probe_status": probe.get("status", ""),
                "fdw_remote_sql_count": probe.get("remote_sql_count", 0),
                "fdw_auto_explain_enabled": fdw_auto_explain.get("enabled", ""),
                "fdw_auto_explain_status": fdw_auto_explain.get("status", ""),
                "fdw_auto_explain_regions": ",".join(
                    str(region) for region in fdw_auto_explain.get("regions", [])
                )
                if isinstance(fdw_auto_explain.get("regions", []), list)
                else "",
                "fdw_auto_explain_observed_regions": ",".join(
                    sorted(set(fdw_auto_explain_observed_regions))
                ),
                "fdw_auto_explain_log_files": _json_text(fdw_auto_explain_log_files),
                "collection_error_count": len(collection_manifest.get("errors", [])),
                "remote_error_count": len(remote_manifest.get("errors", []))
                if remote_manifest
                else "",
                "psql_variables_json": _json_text(bindings.get("psql_variables", {})),
                "pg_options_json": _json_text(bindings.get("pg_options", {})),
            }
        )
        query_row = query_rows[-1]

        for key, value in sorted(bindings.get("psql_variables", {}).items()):
            binding_rows.append(
                {
                    "query_sweep_id": sweep_id,
                    "query_run_id": query_run_id,
                    "instance_id": instance_id,
                    "binding_scope": "psql_variable",
                    "name": key,
                    "value": value,
                }
            )
        for key, value in sorted(bindings.get("pg_options", {}).items()):
            binding_rows.append(
                {
                    "query_sweep_id": sweep_id,
                    "query_run_id": query_run_id,
                    "instance_id": instance_id,
                    "binding_scope": "pg_option",
                    "name": key,
                    "value": value,
                }
            )

        if node_dir is not None:
            metadata_file = node_dir / "metadata.json"
            metadata = _load_json(metadata_file) if metadata_file.exists() else {}
            node_rows.append(
                {
                    "query_sweep_id": sweep_id,
                    "query_run_id": query_run_id,
                    "instance_id": instance_id,
                    "node_name": coordinator,
                    "node_role": metadata.get("node_role") or metadata.get("bench_node_role", ""),
                    "node_artifact_dir": _rel(root, node_dir),
                    "remote_run_dir": collection_manifest.get("node_run_dirs", {}).get(
                        coordinator, ""
                    ),
                    "metadata_file": _rel(root, metadata_file),
                }
            )

        main_plan_id = f"{query_run_id}:main"
        _append_plan_nodes(
            root=root,
            rows=plan_node_rows,
            edge_rows=plan_edge_rows,
            query_sweep_id=sweep_id,
            query_run_id=query_run_id,
            instance_id=instance_id,
            template_id=template_id,
            plan_scope="main",
            plan_id=main_plan_id,
            plan_file=main_plan_file,
        )
        plan_file_rows.append(
            {
                "query_sweep_id": sweep_id,
                "query_run_id": query_run_id,
                "instance_id": instance_id,
                "plan_scope": "main",
                "plan_id": main_plan_id,
                "remote_sql_id": "",
                "status": "ok" if main_plan_file and main_plan_file.exists() else "missing",
                "plan_fingerprint": main_summary["plan_fingerprint"],
                "plan_json_file": _rel(root, main_plan_file),
                "explain_text_file": _rel(
                    root,
                    _path_from(node_dir, str(remote_manifest.get("explain_text_file", "")))
                    if node_dir is not None
                    else None,
                ),
                "explain_text_sql_file": _rel(
                    root,
                    _path_from(node_dir, str(remote_manifest.get("explain_text_sql_file", "")))
                    if node_dir is not None
                    else None,
                ),
                "explain_analyze_json_sql_file": _rel(
                    root,
                    _path_from(
                        node_dir,
                        str(remote_manifest.get("explain_analyze_json_sql_file", "")),
                    )
                    if node_dir is not None
                    else None,
                ),
                "remote_sql_file": "",
            }
        )
        worker_task_rows.extend(
            _worker_task_fragment_rows_from_plan_file(
                root=root,
                query_sweep_id=sweep_id,
                query_run_id=query_run_id,
                instance_id=instance_id,
                template_id=template_id,
                plan_id=main_plan_id,
                remote_sql_id="",
                fdw_region=str(coordinator).split("-", 1)[0],
                plan_file=main_plan_file,
            )
        )
        query_row.update(
            _execution_evidence_contract_summary(
                query_row=query_row,
                plan_files=plan_file_rows[plan_file_start:],
                region_fragments=region_fragment_rows[region_fragment_start:],
                worker_tasks=worker_task_rows[worker_task_start:],
            )
        )

        if node_dir is None:
            plan_structure_rows.append(
                plan_structure_feature_row(
                    query_sweep_id=sweep_id,
                    query_run_id=query_run_id,
                    instance_id=instance_id,
                    template_id=template_id,
                    plan_nodes=plan_node_rows[plan_node_start:],
                    plan_edges=plan_edge_rows[plan_edge_start:],
                )
            )
            finished_at = timing.get("query_finished_at_unix", "")
            try:
                instance_last_finished_at[instance_id] = float(finished_at)
            except (TypeError, ValueError):
                if started_at_float is not None:
                    instance_last_finished_at[instance_id] = started_at_float
            instance_seen_counts[instance_id] = instance_seen_counts.get(instance_id, 0) + 1
            continue
        for remote_probe in probe.get("probes", []) or []:
            remote_sql_id = str(remote_probe.get("remote_sql_id", ""))
            plan_id = f"{query_run_id}:{remote_sql_id}"
            remote_plan_file = _path_from(node_dir, str(remote_probe.get("plan_file", "")))
            if remote_plan_file is not None:
                remote_plan_files.append(remote_plan_file)
            remote_sql_file = _path_from(
                node_dir,
                str(remote_probe.get("remote_sql_file", "")),
            )
            remote_summary = _plan_summary(remote_plan_file)
            remote_plan_rows.append(
                {
                    "query_sweep_id": sweep_id,
                    "query_run_id": query_run_id,
                    "remote_sql_hash": (
                        _hash_text(_read_text(remote_sql_file)) if remote_sql_file.is_file() else ""
                    ),
                    "remote_sql_text": _read_text(remote_sql_file),
                    "remote_plan_fingerprint": remote_summary["plan_fingerprint"],
                    "instance_id": instance_id,
                    "template_id": template_id,
                    "plan_id": plan_id,
                    "remote_sql_id": remote_sql_id,
                    "plan_fingerprint": remote_summary["plan_fingerprint"],
                    "status": remote_probe.get("status", ""),
                    "fdw_region": remote_probe.get("region", ""),
                    "fdw_schema": remote_probe.get("schema", ""),
                    "fdw_relation_name": remote_probe.get("relation_name", ""),
                    "fdw_alias": remote_probe.get("alias", ""),
                    "fdw_node_type": remote_probe.get("node_type", ""),
                    "plan_json_file": _rel(root, remote_plan_file),
                    "remote_sql_file": _rel(root, remote_sql_file),
                    "explain_text_file": _rel(
                        root,
                        _path_from(node_dir, str(remote_probe.get("explain_text_file", ""))),
                    ),
                    "explain_text_sql_file": _rel(
                        root,
                        _path_from(
                            node_dir,
                            str(remote_probe.get("explain_text_sql_file", "")),
                        ),
                    ),
                    "explain_analyze_json_sql_file": _rel(
                        root,
                        _path_from(
                            node_dir,
                            str(remote_probe.get("explain_analyze_json_sql_file", "")),
                        ),
                    ),
                    "plan_node_count": remote_summary["plan_node_count"],
                    "plan_parse_error": remote_summary["plan_parse_error"],
                    "diagnostic_timing_json": _json_text(remote_probe.get("diagnostic_timing", {})),
                    "error": remote_probe.get("error", ""),
                }
            )
            remote_plan_fingerprints.append(
                {
                    "remote_sql_id": remote_sql_id,
                    "fdw_region": str(remote_probe.get("region", "")),
                    "plan_fingerprint": str(remote_summary["plan_fingerprint"]),
                }
            )
            plan_file_rows.append(
                {
                    "query_sweep_id": sweep_id,
                    "query_run_id": query_run_id,
                    "instance_id": instance_id,
                    "plan_scope": "fdw_remote",
                    "plan_id": plan_id,
                    "remote_sql_id": remote_sql_id,
                    "status": remote_probe.get("status", ""),
                    "plan_fingerprint": remote_summary["plan_fingerprint"],
                    "plan_json_file": _rel(root, remote_plan_file),
                    "explain_text_file": _rel(
                        root,
                        _path_from(node_dir, str(remote_probe.get("explain_text_file", ""))),
                    ),
                    "explain_text_sql_file": _rel(
                        root,
                        _path_from(
                            node_dir,
                            str(remote_probe.get("explain_text_sql_file", "")),
                        ),
                    ),
                    "explain_analyze_json_sql_file": _rel(
                        root,
                        _path_from(
                            node_dir,
                            str(remote_probe.get("explain_analyze_json_sql_file", "")),
                        ),
                    ),
                    "remote_sql_file": _rel(
                        root,
                        _path_from(node_dir, str(remote_probe.get("remote_sql_file", ""))),
                    ),
                }
            )
            _append_plan_nodes(
                root=root,
                rows=plan_node_rows,
                edge_rows=plan_edge_rows,
                query_sweep_id=sweep_id,
                query_run_id=query_run_id,
                instance_id=instance_id,
                template_id=template_id,
                plan_scope="fdw_remote",
                plan_id=plan_id,
                remote_sql_id=remote_sql_id,
                fdw_region=str(remote_probe.get("region", "")),
                fdw_schema=str(remote_probe.get("schema", "")),
                plan_file=remote_plan_file,
            )
            region_fragment_rows.append(
                _region_fragment_row_from_plan_file(
                    root=root,
                    query_sweep_id=sweep_id,
                    query_run_id=query_run_id,
                    instance_id=instance_id,
                    template_id=template_id,
                    remote_plan_id=plan_id,
                    region_id=str(remote_probe.get("region", "")),
                    source_type="fdw_remote_probe",
                    remote_sql_id=remote_sql_id,
                    remote_plan_fingerprint=str(remote_summary["plan_fingerprint"]),
                    plan_file=remote_plan_file,
                )
            )
        query_row.update(
            _fan_in_width_summary(
                main_plan_file=main_plan_file,
                remote_plan_files=remote_plan_files,
            )
        )
        for auto_plan in _auto_explain_plan_files(
            root=root,
            out_dir=out_dir,
            collection_dir=collection_dir,
            query_run_id=query_run_id,
            fdw_auto_explain_hosts=fdw_auto_explain_hosts,
        ):
            remote_sql_id = str(auto_plan["remote_sql_id"])
            plan_id = f"{query_run_id}:{remote_sql_id}"
            auto_plan_file = Path(auto_plan["plan_file"])
            auto_summary = _plan_summary(auto_plan_file)
            query_text = str(auto_plan.get("query_text", ""))
            document_role = str(auto_plan.get("document_role", ""))
            is_remote_query_document = document_role == "regional_remote_query"
            if is_remote_query_document:
                remote_plan_files.append(auto_plan_file)
                remote_plan_rows.append(
                    {
                        "query_sweep_id": sweep_id,
                        "query_run_id": query_run_id,
                        "remote_sql_hash": _hash_text(query_text) if query_text else "",
                        "remote_sql_text": query_text,
                        "remote_plan_fingerprint": auto_summary["plan_fingerprint"],
                        "instance_id": instance_id,
                        "template_id": template_id,
                        "plan_id": plan_id,
                        "remote_sql_id": remote_sql_id,
                        "plan_fingerprint": auto_summary["plan_fingerprint"],
                        "status": "ok",
                        "fdw_region": auto_plan.get("region", ""),
                        "fdw_schema": "",
                        "fdw_relation_name": "",
                        "fdw_alias": "",
                        "fdw_node_type": "auto_explain",
                        "auto_explain_document_role": document_role,
                        "plan_json_file": auto_plan["plan_file_rel"],
                        "remote_sql_file": "",
                        "explain_text_file": auto_plan["log_file_rel"],
                        "explain_text_sql_file": "",
                        "explain_analyze_json_sql_file": "",
                        "plan_node_count": auto_summary["plan_node_count"],
                        "plan_parse_error": auto_summary["plan_parse_error"],
                        "diagnostic_timing_json": _json_text(
                            {
                                "source": "postgres_auto_explain_log",
                                "host": auto_plan.get("host_name", ""),
                                "document_role": document_role,
                            }
                        ),
                        "error": "",
                    }
                )
                remote_plan_fingerprints.append(
                    {
                        "remote_sql_id": remote_sql_id,
                        "fdw_region": str(auto_plan.get("region", "")),
                        "plan_fingerprint": str(auto_summary["plan_fingerprint"]),
                    }
                )
            plan_scope = (
                "fdw_auto_explain_remote"
                if is_remote_query_document
                else "fdw_auto_explain_internal"
            )
            plan_file_rows.append(
                {
                    "query_sweep_id": sweep_id,
                    "query_run_id": query_run_id,
                    "instance_id": instance_id,
                    "plan_scope": plan_scope,
                    "plan_id": plan_id,
                    "remote_sql_id": remote_sql_id,
                    "status": "ok",
                    "plan_fingerprint": auto_summary["plan_fingerprint"],
                    "auto_explain_document_role": document_role,
                    "plan_json_file": auto_plan["plan_file_rel"],
                    "explain_text_file": auto_plan["log_file_rel"],
                    "explain_text_sql_file": "",
                    "explain_analyze_json_sql_file": "",
                    "remote_sql_file": "",
                }
            )
            _append_plan_nodes(
                root=root,
                rows=plan_node_rows,
                edge_rows=plan_edge_rows,
                query_sweep_id=sweep_id,
                query_run_id=query_run_id,
                instance_id=instance_id,
                template_id=template_id,
                plan_scope=plan_scope,
                plan_id=plan_id,
                remote_sql_id=remote_sql_id,
                fdw_region=str(auto_plan.get("region", "")),
                fdw_schema="",
                plan_file=auto_plan_file,
            )
            if is_remote_query_document:
                worker_task_rows.extend(
                    _worker_task_fragment_rows_from_plan_file(
                        root=root,
                        query_sweep_id=sweep_id,
                        query_run_id=query_run_id,
                        instance_id=instance_id,
                        template_id=template_id,
                        plan_id=plan_id,
                        remote_sql_id=remote_sql_id,
                        fdw_region=str(auto_plan.get("region", "")),
                        plan_file=auto_plan_file,
                    )
                )
                region_fragment_rows.append(
                    _region_fragment_row_from_plan_file(
                        root=root,
                        query_sweep_id=sweep_id,
                        query_run_id=query_run_id,
                        instance_id=instance_id,
                        template_id=template_id,
                        remote_plan_id=plan_id,
                        region_id=str(auto_plan.get("region", "")),
                        source_type="fdw_auto_explain_remote",
                        remote_sql_id=remote_sql_id,
                        remote_plan_fingerprint=str(auto_summary["plan_fingerprint"]),
                        plan_file=auto_plan_file,
                    )
                )
        query_row.update(
            _fan_in_width_summary(
                main_plan_file=main_plan_file,
                remote_plan_files=remote_plan_files,
            )
        )
        query_row.update(_coordinator_pressure_summary(main_plan_file))
        query_row.update(
            _estimate_error_summary(
                main_plan_file=main_plan_file,
                remote_plan_files=remote_plan_files,
            )
        )
        query_row.update(_task_skew_summary([main_plan_file, *remote_plan_files]))
        query_row.update(_worker_task_aggregates(worker_task_rows[worker_task_start:]))
        configured_regions = []
        if isinstance(fdw_auto_explain.get("regions", []), list):
            configured_regions = [str(region) for region in fdw_auto_explain.get("regions", [])]
        region_rows_for_query = region_fragment_rows[region_fragment_start:]
        expected_regions = _expected_remote_regions_for_query(
            query_row=query_row,
            configured_regions=configured_regions,
            observed_region_rows=region_rows_for_query,
        )
        query_row.update(
            _remote_region_aggregates(
                region_rows_for_query,
                expected_regions=expected_regions,
            )
        )
        query_row["citus_repartition_observed_v2"] = (
            "true" if _citus_repartition_observed_v2(query_row) else "false"
        )
        query_row.update(
            _execution_evidence_contract_summary(
                query_row=query_row,
                plan_files=plan_file_rows[plan_file_start:],
                region_fragments=region_rows_for_query,
                worker_tasks=worker_task_rows[worker_task_start:],
            )
        )
        remote_edge_rows.extend(
            _remote_edge_observation_rows(
                query_sweep_id=sweep_id,
                query_row=query_row,
                edge_context_rows=_load_remote_edge_context(
                    collection_dir,
                    collection_manifest,
                ),
                plan_nodes=plan_node_rows[plan_node_start:],
                region_fragments=region_rows_for_query,
                remote_plans=[
                    row
                    for row in remote_plan_rows
                    if row.get("query_run_id") == query_run_id
                ],
            )
        )
        plan_structure_rows.append(
            plan_structure_feature_row(
                query_sweep_id=sweep_id,
                query_run_id=query_run_id,
                instance_id=instance_id,
                template_id=template_id,
                plan_nodes=plan_node_rows[plan_node_start:],
                plan_edges=plan_edge_rows[plan_edge_start:],
            )
        )
        if remote_plan_fingerprints:
            remote_fingerprints_json = _json_text(remote_plan_fingerprints)
            query_row["remote_plan_fingerprints_json"] = remote_fingerprints_json
            query_row["remote_plan_fingerprint"] = _hash_text(remote_fingerprints_json)
        finished_at = timing.get("query_finished_at_unix", "")
        try:
            instance_last_finished_at[instance_id] = float(finished_at)
        except (TypeError, ValueError):
            if started_at_float is not None:
                instance_last_finished_at[instance_id] = started_at_float
        instance_seen_counts[instance_id] = instance_seen_counts.get(instance_id, 0) + 1

    corpus_cell_rows = _corpus_cell_rows(
        query_sweep_id=sweep_id,
        query_rows=query_rows,
    )
    _write_csv(
        out_dir / "corpus_cells.csv",
        corpus_cell_rows,
        [
            "query_sweep_id",
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
            "runtime_sensitivity",
            "required_dataset_capabilities",
            "intervention_roles",
            "template_ids",
            "instance_ids",
            "query_run_count",
        ],
    )
    _write_csv(
        out_dir / "query_runs.csv",
        query_rows,
        [
            "query_sweep_id",
            "query_run_id",
            "attempt_id",
            "execution_status",
            "timed_out",
            "hard_timeout_seconds",
            "timeout_phase",
            *CORPUS_METADATA_FIELDS,
            "instance_id",
            "template_id",
            "sql_normalized_hash",
            "rendered_sql_hash",
            "plan_fingerprint",
            "remote_plan_fingerprint",
            "remote_plan_fingerprints_json",
            "param_json",
            "expected_shape_tags",
            "collection_dir",
            "os_sampled_node_count",
            "os_sample_count_sum",
            "os_raw_sample_count_sum",
            "os_query_aligned_node_count",
            "os_query_alignment_coverage_count",
            "os_query_alignment_worst_status",
            "os_query_alignment_status_counts_json",
            "os_query_bracket_duration_seconds_mean",
            "os_query_bracket_duration_seconds_max",
            "os_query_padding_seconds_max",
            "os_clock_calibrated_node_count",
            "os_clock_uncertainty_seconds_max",
            "os_cpu_busy_pct_mean",
            "os_cpu_busy_pct_max",
            "os_cpu_steal_pct_mean",
            "os_cpu_steal_pct_max",
            "os_mem_used_peak_bytes_max",
            "os_mem_available_bytes_min",
            "os_disk_read_bytes_sum",
            "os_disk_written_bytes_sum",
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
            "source_sql_file",
            "query_sql_file",
            "query_bindings_file",
            "coordinator_node",
            "created_at_utc",
            "elapsed_seconds",
            "query_started_at_unix",
            "query_finished_at_unix",
            "repetition_index",
            "run_order",
            "warmup_run_flag",
            "cache_policy",
            "same_instance_previous_execution_gap_seconds",
            "shared_blks_hit_sum",
            "shared_blks_read_sum",
            "shared_hit_ratio",
            "temp_blks_read_sum",
            "temp_blks_written_sum",
            "distribution_key",
            "filter_uses_distribution_key",
            "join_uses_distribution_key",
            "group_by_uses_distribution_key",
            "order_by_uses_distribution_key",
            "tenant_filter_present",
            "single_tenant_scope",
            "multi_tenant_scope",
            "distribution_key_usage_source",
            "main_root_plan_width",
            "foreign_scan_plan_width_sum",
            "foreign_scan_plan_width_max",
            "remote_root_plan_width_sum",
            "remote_root_plan_width_max",
            "estimated_result_bytes",
            "estimated_remote_output_bytes",
            "estimated_fanin_bytes",
            "result_width_class",
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
            *[
                field
                for class_name in COORDINATOR_OPERATOR_CLASSES
                for field in (
                    f"coordinator_{class_name}_operator_count",
                    f"coordinator_{class_name}_input_rows_sum",
                    f"coordinator_{class_name}_input_rows_max",
                    f"coordinator_{class_name}_output_rows_sum",
                    f"coordinator_{class_name}_time_ms_max",
                )
            ],
            "foreign_scan_rows_estimate_error_log",
            "aggregate_rows_estimate_error_log",
            "join_rows_estimate_error_log",
            "sort_rows_estimate_error_log",
            "remote_root_rows_estimate_error_log",
            "task_count",
            "task_time_min_ms",
            "task_time_max_ms",
            "task_time_mean_ms",
            "task_time_cv",
            "task_rows_min",
            "task_rows_max",
            "task_rows_mean",
            "task_rows_cv",
            "worker_task_count_cv",
            "worker_task_worker_count",
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
            "remote_region_count",
            "regional_remote_plan_count",
            "regional_internal_plan_count",
            "regional_plan_evidence_status",
            "remote_region_observed_count",
            "remote_region_missing_count",
            "remote_region_evidence_completeness",
            "remote_region_parse_success_count",
            "remote_region_parse_partial_count",
            "remote_region_rows_available_count",
            "remote_region_time_available_count",
            "remote_region_task_count_available_count",
            "remote_region_actual_rows_sum",
            "remote_region_actual_rows_min",
            "remote_region_actual_rows_max",
            "remote_region_actual_rows_mean",
            "remote_region_actual_rows_cv",
            "remote_region_actual_rows_max_share",
            "remote_region_actual_rows_imbalance_ratio",
            "remote_region_actual_rows_min_max_ratio",
            "remote_region_actual_rows_active_share",
            "remote_region_zero_row_count",
            "remote_region_nonzero_count",
            "remote_region_actual_time_sum",
            "remote_region_actual_time_min",
            "remote_region_actual_time_max",
            "remote_region_actual_time_mean",
            "remote_region_actual_time_cv",
            "remote_region_actual_time_max_share",
            "remote_region_actual_time_imbalance_ratio",
            "remote_region_actual_time_min_max_ratio",
            "remote_region_actual_time_active_share",
            "remote_region_tuple_bytes_sum",
            "remote_region_tuple_bytes_min",
            "remote_region_tuple_bytes_max",
            "remote_region_tuple_bytes_mean",
            "remote_region_tuple_bytes_cv",
            "remote_region_tuple_bytes_max_share",
            "remote_region_tuple_bytes_imbalance_ratio",
            "remote_region_tuple_bytes_min_max_ratio",
            "remote_region_tuple_bytes_active_share",
            "remote_region_task_count_sum",
            "remote_region_task_count_min",
            "remote_region_task_count_max",
            "remote_region_task_count_mean",
            "remote_region_task_count_cv",
            "remote_region_task_count_max_share",
            "remote_region_task_count_imbalance_ratio",
            "remote_region_task_count_min_max_ratio",
            "remote_region_task_count_active_share",
            "regional_temp_evidence_region_count",
            "regional_temp_read_blocks_sum",
            "regional_temp_read_blocks_max",
            "regional_temp_written_blocks_sum",
            "regional_temp_written_blocks_max",
            "regional_spill_region_count",
            "regional_spill_present",
            "remote_region_plan_fingerprint_count",
            "remote_region_plan_fingerprint_all_same",
            "remote_region_dominant_plan_fingerprint_share",
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
            "worker_task_plan_count",
            "worker_task_evidence_status",
            "worker_task_plan_format",
            "worker_task_timing_status",
            "worker_task_parse_ok_count",
            "worker_task_parse_partial_count",
            "worker_task_parse_failed_count",
            "worker_task_actual_rows_sum",
            "worker_task_actual_rows_min",
            "worker_task_actual_rows_max",
            "worker_task_actual_rows_cv",
            "worker_task_actual_rows_max_share",
            "worker_task_root_rows_isf",
            "worker_task_scan_actual_rows_sum",
            "worker_task_scan_actual_rows_min",
            "worker_task_scan_actual_rows_max",
            "worker_task_scan_actual_rows_cv",
            "worker_task_scan_actual_rows_max_share",
            "worker_task_scan_rows_isf",
            "worker_task_scan_rows_isf_normalized",
            "worker_task_active_scan_rows_isf",
            "worker_task_active_scan_rows_isf_normalized",
            "worker_task_active_scan_skew_applicable",
            "worker_task_active_scan_skew_applicable_region_count",
            "worker_task_tuple_bytes_sum",
            "worker_task_tuple_bytes_min",
            "worker_task_tuple_bytes_max",
            "worker_task_tuple_bytes_cv",
            "worker_task_tuple_bytes_max_share",
            "worker_task_tuple_bytes_isf",
            "worker_task_tuple_bytes_isf_normalized",
            "worker_task_tuple_bytes_skew_applicable",
            "worker_task_tuple_bytes_skew_applicable_region_count",
            "worker_task_nonzero_scan_count",
            "worker_task_nonzero_scan_share",
            "worker_task_scan_skew_applicable",
            "worker_task_scan_skew_applicable_region_count",
            "worker_task_actual_time_sum",
            "worker_task_actual_time_min",
            "worker_task_actual_time_max",
            "worker_task_actual_time_cv",
            "worker_task_actual_time_max_share",
            "worker_task_actual_time_isf",
            "worker_task_actual_time_isf_normalized",
            "worker_task_scan_type_counts_json",
            "worker_task_index_scan_share",
            "worker_task_seq_scan_share",
            "worker_task_bitmap_scan_share",
            "worker_task_node_type_counts_json",
            "worker_task_node_type_unknown_count",
            "worker_task_node_type_unknown_set_json",
            "worker_task_node_count_sum",
            "worker_task_plan_max_depth_max",
            "worker_task_plan_max_depth_mean",
            "worker_task_join_node_count",
            "worker_task_aggregate_node_count",
            "worker_task_sort_node_count",
            "worker_task_blocking_node_count",
            "worker_task_scan_node_count",
            "worker_task_materialization_node_count",
            "worker_task_parallel_node_count",
            "worker_task_bitmap_node_count",
            "worker_task_index_access_node_count",
            "worker_task_sequential_access_node_count",
            "worker_task_spill_capable_node_count",
            "worker_task_has_join",
            "worker_task_has_aggregate",
            "worker_task_has_sort",
            "worker_task_has_blocking_operator",
            "worker_task_has_parallel_operator",
            "worker_task_has_hash",
            "worker_task_has_materialize",
            "worker_task_plan_fingerprint_count",
            "worker_task_plan_fingerprint_dominant_share",
            "worker_task_spill_count",
            "worker_task_shared_hit_sum",
            "worker_task_shared_read_sum",
            "worker_task_temp_read_sum",
            "worker_task_temp_written_sum",
            "worker_task_region_count",
            "worker_task_region_task_count_cv",
            "worker_task_region_rows_cv",
            "worker_task_region_rows_max_share",
            "worker_task_region_scan_rows_cv",
            "worker_task_region_scan_rows_max_share",
            "worker_task_within_region_rows_cv_max",
            "worker_task_within_region_rows_cv_mean",
            "worker_task_within_region_rows_max_share_max",
            "worker_task_within_region_scan_rows_cv_max",
            "worker_task_within_region_scan_rows_cv_mean",
            "worker_task_within_region_scan_rows_max_share_max",
            "worker_task_within_region_scan_rows_isf_max",
            "worker_task_within_region_scan_rows_isf_normalized_max",
            "worker_task_within_region_active_scan_rows_isf_normalized_max",
            "worker_task_within_region_tuple_bytes_isf_normalized_max",
            "worker_task_within_region_worker_scan_rows_cv_max",
            "worker_task_within_region_worker_scan_rows_cv_mean",
            "worker_task_within_region_worker_scan_rows_max_share_max",
            "worker_task_within_region_worker_scan_rows_isf_max",
            "worker_task_within_region_worker_scan_rows_isf_normalized_max",
            "worker_scan_rows_skew_applicable",
            "worker_scan_rows_skew_applicable_region_count",
            "worker_task_within_region_plan_fingerprint_count_max",
            "worker_task_within_region_plan_fingerprint_count_mean",
            "main_plan_json_file",
            "main_explain_text_file",
            "citus_top_task_count",
            "citus_map_merge_job_count",
            "citus_dependent_map_task_count_sum",
            "citus_dependent_merge_task_count_sum",
            "citus_repartition_fanout_ratio",
            "citus_repartition_query",
            "citus_tasks_shown_none",
            "citus_plan_locality_class",
            "main_plan_node_count",
            "main_has_foreign_scan",
            "main_has_remote_sql",
            "main_plan_parse_error",
            "fdw_remote_probe_enabled",
            "fdw_remote_probe_status",
            "fdw_remote_sql_count",
            "fdw_auto_explain_enabled",
            "fdw_auto_explain_status",
            "fdw_auto_explain_regions",
            "fdw_auto_explain_observed_regions",
            "fdw_auto_explain_log_files",
            "collection_error_count",
            "remote_error_count",
            "psql_variables_json",
            "pg_options_json",
        ],
    )
    _write_csv(
        out_dir / "query_bindings.csv",
        binding_rows,
        ["query_sweep_id", "query_run_id", "instance_id", "binding_scope", "name", "value"],
    )
    _write_csv(
        out_dir / "query_nodes.csv",
        node_rows,
        [
            "query_sweep_id",
            "query_run_id",
            "instance_id",
            "node_name",
            "node_role",
            "node_artifact_dir",
            "remote_run_dir",
            "metadata_file",
        ],
    )
    _write_csv(
        out_dir / "plan_files.csv",
        plan_file_rows,
        [
            "query_sweep_id",
            "query_run_id",
            "instance_id",
            "plan_scope",
            "plan_id",
            "remote_sql_id",
            "status",
            "plan_fingerprint",
            "auto_explain_document_role",
            "plan_json_file",
            "explain_text_file",
            "explain_text_sql_file",
            "explain_analyze_json_sql_file",
            "remote_sql_file",
        ],
    )
    plan_node_fields = [
        "query_sweep_id",
        "query_run_id",
        "instance_id",
        "template_id",
        "plan_scope",
        "plan_id",
        "parent_plan_id",
        "remote_sql_id",
        "fdw_region",
        "fdw_schema",
        "plan_json_file",
        "citus_task_index",
        "citus_task_worker",
        "node_id",
        "parent_node_id",
        "child_index",
        "depth",
        "node_path",
        "node_type",
        "strategy",
        "partial_mode",
        "join_type",
        "parent_relationship",
        "parallel_aware",
        "group_key",
        "sort_key",
        "schema_name",
        "relation_name",
        "relations_text",
        "alias",
        "remote_sql_text",
        "startup_cost",
        "total_cost",
        "plan_rows",
        "plan_width",
        "actual_startup_time",
        "actual_total_time",
        "actual_rows",
        "actual_loops",
        "shared_hit_blocks",
        "shared_read_blocks",
        "temp_read_blocks",
        "temp_written_blocks",
        "sort_method",
        "sort_space_used",
        "sort_space_type",
        "hash_buckets",
        "hash_batches",
        "disk_usage",
        "peak_memory_usage",
    ]
    _write_csv(out_dir / "plan_nodes.csv", plan_node_rows, plan_node_fields)
    _write_csv(
        out_dir / "plan_edges.csv",
        plan_edge_rows,
        [
            "query_sweep_id",
            "query_run_id",
            "instance_id",
            "template_id",
            "plan_scope",
            "plan_id",
            "parent_plan_id",
            "remote_sql_id",
            "fdw_region",
            "fdw_schema",
            "plan_json_file",
            "citus_task_index",
            "citus_task_worker",
            "parent_node_id",
            "child_node_id",
            "parent_node_type",
            "child_node_type",
            "child_index",
            "parent_depth",
            "child_depth",
            "parent_node_path",
            "child_node_path",
            "edge_type",
        ],
    )
    _write_csv(
        out_dir / "fdw_remote_plans.csv",
        remote_plan_rows,
        [
            "query_sweep_id",
            "query_run_id",
            "remote_sql_hash",
            "remote_sql_text",
            "remote_plan_fingerprint",
            "instance_id",
            "template_id",
            "plan_id",
            "remote_sql_id",
            "plan_fingerprint",
            "status",
            "fdw_region",
            "fdw_schema",
            "fdw_relation_name",
            "fdw_alias",
            "fdw_node_type",
            "auto_explain_document_role",
            "plan_json_file",
            "remote_sql_file",
            "explain_text_file",
            "explain_text_sql_file",
            "explain_analyze_json_sql_file",
            "plan_node_count",
            "plan_parse_error",
            "diagnostic_timing_json",
            "error",
        ],
    )
    _write_csv(
        out_dir / "region_fragments.csv",
        region_fragment_rows,
        [
            "query_sweep_id",
            "query_run_id",
            "instance_id",
            "template_id",
            "remote_plan_id",
            "region_id",
            "cluster_id",
            "source_type",
            "remote_sql_id",
            "parse_status",
            "parse_confidence",
            "remote_plan_fingerprint",
            "remote_plan_json_file",
            "remote_plan_node_count",
            "remote_plan_max_depth",
            "remote_root_node_type",
            "remote_has_custom_scan",
            "remote_has_foreign_scan",
            "remote_has_aggregate",
            "remote_has_sort",
            "remote_has_join",
            "remote_has_limit",
            "remote_has_materialize",
            "remote_citus_task_count",
            "remote_citus_top_task_count",
            "remote_citus_task_count_available",
            "remote_citus_tasks_shown",
            "remote_citus_tasks_shown_none",
            "remote_citus_task_list_available",
            "remote_citus_map_merge_job_count",
            "remote_citus_dependent_map_task_count_sum",
            "remote_citus_dependent_merge_task_count_sum",
            "remote_citus_repartition_fanout_ratio",
            "remote_citus_tuple_bytes_supported",
            "remote_citus_tuple_bytes_source",
            "remote_citus_plan_locality_class",
            "remote_citus_router_single_task",
            "remote_citus_reference_join_candidate",
            "remote_citus_colocated_join_candidate",
            "remote_citus_repartition_mapmerge",
            "remote_custom_scan_name",
            "remote_has_task_list",
            "remote_task_plan_parse_status",
            "remote_task_plan_parse_confidence",
            "remote_actual_rows",
            "remote_plan_rows",
            "remote_actual_total_time_ms",
            "remote_actual_startup_time_ms",
            "remote_plan_width",
            "remote_estimated_tuple_bytes",
            "remote_temp_blocks_read",
            "remote_temp_blocks_written",
            "remote_shared_blks_hit",
            "remote_shared_blks_read",
            "remote_rows_estimate_error_log",
            "remote_tuple_bytes_proxy",
            "remote_zero_rows_flag",
            "remote_nonzero_rows_flag",
        ],
    )
    _write_csv(
        out_dir / "worker_task_fragments.csv",
        worker_task_rows,
        [
            "query_sweep_id",
            "query_run_id",
            "instance_id",
            "template_id",
            "plan_id",
            "remote_sql_id",
            "fdw_region",
            "task_index",
            "worker_node",
            "task_query_hash",
            "tuple_data_received_bytes",
            "parse_status",
            "parse_confidence",
            "worker_task_plan_fingerprint",
            "worker_task_root_node_type",
            "worker_task_node_count",
            "worker_task_plan_max_depth",
            "worker_task_actual_rows",
            "worker_task_scan_actual_rows_sum",
            "worker_task_scan_actual_rows_max",
            "worker_task_actual_time_ms",
            "worker_task_node_type_counts_json",
            "worker_task_scan_type_counts_json",
            "worker_task_node_type_unknown_count",
            "worker_task_node_type_unknown_set_json",
            "worker_task_join_node_count",
            "worker_task_aggregate_node_count",
            "worker_task_sort_node_count",
            "worker_task_blocking_node_count",
            "worker_task_scan_node_count",
            "worker_task_materialization_node_count",
            "worker_task_parallel_node_count",
            "worker_task_bitmap_node_count",
            "worker_task_index_access_node_count",
            "worker_task_sequential_access_node_count",
            "worker_task_spill_capable_node_count",
            "worker_task_has_join",
            "worker_task_has_aggregate",
            "worker_task_has_sort",
            "worker_task_has_blocking_operator",
            "worker_task_has_parallel_operator",
            "worker_task_has_hash",
            "worker_task_has_materialize",
            "worker_task_spill_flag",
            "worker_task_spill_count",
            "worker_task_shared_hit_blocks",
            "worker_task_shared_read_blocks",
            "worker_task_temp_read_blocks",
            "worker_task_temp_written_blocks",
            "plan_json_file",
        ],
    )
    _write_csv(
        out_dir / "remote_edge_observations.csv",
        remote_edge_rows,
        [
            "query_sweep_id",
            "query_run_id",
            "instance_id",
            "template_id",
            "edge_id",
            "source_cluster_id",
            "destination_gac_id",
            "source_node",
            "destination_node",
            "foreign_schema_id",
            "foreign_server_id",
            "remote_sql_fingerprint",
            "remote_sql_count",
            "remote_plan_fingerprints_json",
            "remote_plan_fingerprint_count",
            "regional_plan_count",
            "remote_rows",
            "remote_tuple_width",
            "remote_bytes_proxy",
            "foreign_scan_time_ms_sum",
            "regional_plan_time_ms_sum",
            "foreign_scan_minus_regional_time_ms_proxy",
            "fetch_size",
            "estimated_fetch_cycles",
            "rtt_before_median_ms",
            "rtt_after_median_ms",
            "rtt_context_median_ms",
            "rtt_before_max_ms",
            "rtt_after_max_ms",
            "rtt_context_max_ms",
            "rtt_before_mdev_ms",
            "rtt_after_mdev_ms",
            "packet_loss_context_percent_max",
            "rtt_probe_packets_received_min",
            "route_device",
            "route_source_ip",
            "query_window_source_tx_bytes",
            "query_window_source_tx_packets",
            "query_window_destination_rx_bytes_shared",
            "query_window_source_tx_bps",
            "remote_payload_to_source_tx_ratio",
            "query_window_qdisc_bytes",
            "query_window_qdisc_packets",
            "query_window_qdisc_drops",
            "query_window_qdisc_overlimits",
            "tcp_retrans_delta_node_global",
            "configured_network_profile",
            "network_intervention_targeted",
            "configured_delay_ms",
            "configured_jitter_ms",
            "configured_loss_percent",
            "configured_bandwidth_mbit",
            "network_profile_json",
            "measurement_quality",
            "availability_status",
            "traffic_counter_scope",
            "tcp_counter_scope",
            "destination_rx_scope",
            "rtt_scope",
        ],
    )
    _write_csv(
        out_dir / "plan_structure_features.csv",
        plan_structure_rows,
        finalize_plan_structure_rows(plan_structure_rows),
    )
    instance_summary_rows = _instance_summary_rows(
        query_sweep_id=sweep_id,
        query_rows=query_rows,
    )
    instance_summary_fields = [
        "query_sweep_id",
        "template_id",
        "instance_id",
        "query_run_count",
        "measurement_count",
        "successful_run_count",
        "failed_run_count",
        "timeout_run_count",
        "failure_rate",
        "execution_time_mean",
        "execution_time_median",
        "execution_time_p95",
        "execution_time_std",
        "execution_time_cv",
        "plan_fingerprint_count",
        "dominant_plan_fingerprint",
        "remote_plan_fingerprint_count",
        "dominant_remote_plan_fingerprint",
        "first_run_order",
        "last_run_order",
        "distribution_key",
        "filter_uses_distribution_key",
        "join_uses_distribution_key",
        "group_by_uses_distribution_key",
        "order_by_uses_distribution_key",
        "tenant_filter_present",
        "single_tenant_scope",
        "multi_tenant_scope",
        "distribution_key_usage_source",
        "main_root_plan_width_mean",
        "main_root_plan_width_max",
        "estimated_result_bytes_mean",
        "estimated_result_bytes_max",
        "estimated_remote_output_bytes_mean",
        "estimated_remote_output_bytes_max",
        "estimated_fanin_bytes_mean",
        "estimated_fanin_bytes_max",
        "dominant_result_width_class",
        "foreign_scan_rows_estimate_error_log_mean",
        "foreign_scan_rows_estimate_error_abs_max",
        "aggregate_rows_estimate_error_log_mean",
        "aggregate_rows_estimate_error_abs_max",
        "join_rows_estimate_error_log_mean",
        "join_rows_estimate_error_abs_max",
        "sort_rows_estimate_error_log_mean",
        "sort_rows_estimate_error_abs_max",
        "remote_root_rows_estimate_error_log_mean",
        "remote_root_rows_estimate_error_abs_max",
        "task_count_mean",
        "task_count_max",
        "task_time_mean_ms_mean",
        "task_time_cv_mean",
        "task_time_cv_max",
        "task_rows_mean_mean",
        "task_rows_cv_mean",
        "task_rows_cv_max",
        "worker_task_count_cv_mean",
        "worker_task_count_cv_max",
        "worker_rows_cv_mean",
        "worker_rows_cv_max",
        "worker_time_cv_mean",
        "worker_time_cv_max",
    ]
    _write_csv(
        out_dir / "instance_summary_features.csv",
        instance_summary_rows,
        instance_summary_fields,
    )
    if instance_summary_rows:
        _write_parquet(
            out_dir / "instance_summary_features.parquet",
            instance_summary_rows,
        )
    feature_schema_file = _write_feature_schema_sidecar(out_dir)

    summary = {
        "query_sweep_id": sweep_id,
        "sweep_dir": str(root),
        "index_dir": str(out_dir),
        "feature_schema_file": feature_schema_file,
        "feature_schema_contract": "master_regimes_feature_schema_v1"
        if feature_schema_file
        else "",
        "corpus_cell_count": len(corpus_cell_rows),
        "query_run_count": len(query_rows),
        "instance_summary_count": len(instance_summary_rows),
        "plan_file_count": len(plan_file_rows),
        "plan_node_count": len(plan_node_rows),
        "plan_edge_count": len(plan_edge_rows),
        "plan_structure_feature_count": len(plan_structure_rows),
        "fdw_remote_plan_count": len(remote_plan_rows),
        "region_fragment_count": len(region_fragment_rows),
        "worker_task_fragment_count": len(worker_task_rows),
        "remote_edge_observation_count": len(remote_edge_rows),
    }
    (out_dir / "index_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_dir
