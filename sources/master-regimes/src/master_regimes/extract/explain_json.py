from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _root_plan(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, dict) and "Plan" in value:
        return value["Plan"]
    raise ValueError("Expected EXPLAIN FORMAT JSON output with a top-level Plan")


def _walk_plan(
    node: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    parent_id: int | None,
    child_index: int,
    depth: int,
    node_path: str,
) -> int:
    node_id = len(rows) + 1
    rows.append(
        {
            "node_id": node_id,
            "parent_node_id": parent_id or "",
            "child_index": child_index,
            "depth": depth,
            "node_path": node_path,
            "node_type": node.get("Node Type", ""),
            "strategy": node.get("Strategy", ""),
            "partial_mode": node.get("Partial Mode", ""),
            "join_type": node.get("Join Type", ""),
            "parent_relationship": node.get("Parent Relationship", ""),
            "parallel_aware": node.get("Parallel Aware", ""),
            "group_key": json.dumps(node.get("Group Key", []), sort_keys=True),
            "sort_key": json.dumps(node.get("Sort Key", []), sort_keys=True),
            "schema_name": node.get("Schema", ""),
            "relation_name": node.get("Relation Name", ""),
            "relations_text": node.get("Relations", ""),
            "alias": node.get("Alias", ""),
            "remote_sql_text": node.get("Remote SQL", ""),
            "startup_cost": node.get("Startup Cost", ""),
            "total_cost": node.get("Total Cost", ""),
            "plan_rows": node.get("Plan Rows", ""),
            "plan_width": node.get("Plan Width", ""),
            "actual_startup_time": node.get("Actual Startup Time", ""),
            "actual_total_time": node.get("Actual Total Time", ""),
            "actual_rows": node.get("Actual Rows", ""),
            "actual_loops": node.get("Actual Loops", ""),
            "shared_hit_blocks": node.get("Shared Hit Blocks", ""),
            "shared_read_blocks": node.get("Shared Read Blocks", ""),
            "temp_read_blocks": node.get("Temp Read Blocks", ""),
            "temp_written_blocks": node.get("Temp Written Blocks", ""),
            "sort_method": node.get("Sort Method", ""),
            "sort_space_used": node.get("Sort Space Used", ""),
            "sort_space_type": node.get("Sort Space Type", ""),
            "hash_buckets": node.get("Hash Buckets", ""),
            "hash_batches": node.get("Hash Batches", node.get("HashAgg Batches", "")),
            "disk_usage": node.get("Disk Usage", ""),
            "peak_memory_usage": node.get("Peak Memory Usage", ""),
        }
    )
    for index, child in enumerate(node.get("Plans", []) or []):
        _walk_plan(
            child,
            rows=rows,
            parent_id=node_id,
            child_index=index,
            depth=depth + 1,
            node_path=f"{node_path}.{index}",
        )
    return node_id


def extract_plan_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    _walk_plan(
        _root_plan(value),
        rows=rows,
        parent_id=None,
        child_index=0,
        depth=0,
        node_path="0",
    )
    return rows


_FINGERPRINT_KEYS = (
    "Node Type",
    "Strategy",
    "Partial Mode",
    "Parallel Aware",
    "Join Type",
    "Parent Relationship",
    "Relation Name",
    "Index Name",
    "Function Name",
    "Schema",
    "Alias",
    "Group Key",
    "Sort Key",
    "Hash Cond",
    "Merge Cond",
    "Join Filter",
    "Filter",
    "Index Cond",
    "Recheck Cond",
    "Remote SQL",
)


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, str):
        without_strings = re.sub(r"'(?:''|[^'])*'", "?", value)
        without_numbers = re.sub(r"\b\d+(?:\.\d+)?\b", "?", without_strings)
        return re.sub(r"\s+", " ", without_numbers).strip().lower()
    if isinstance(value, list):
        return [_fingerprint_value(item) for item in value]
    return value


def _fingerprint_node(node: dict[str, Any]) -> dict[str, Any]:
    payload = {key: _fingerprint_value(node[key]) for key in _FINGERPRINT_KEYS if key in node}
    children = node.get("Plans", []) or []
    if children:
        payload["Plans"] = [_fingerprint_node(child) for child in children]
    return payload


def plan_fingerprint(value: Any) -> str:
    """Return a stable structural fingerprint for an EXPLAIN JSON plan.

    Runtime, buffer, row-count and cost fields are intentionally ignored. The
    fingerprint is meant for plan stability/drift analysis, not performance
    comparison.
    """

    payload = _fingerprint_node(_root_plan(value))
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def extract_plan_nodes(*, input_path: Path, output_path: Path) -> Path:
    value = json.loads(input_path.read_text(encoding="utf-8"))
    rows = extract_plan_rows(value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["node_id"])
        writer.writeheader()
        writer.writerows(rows)
    return output_path
