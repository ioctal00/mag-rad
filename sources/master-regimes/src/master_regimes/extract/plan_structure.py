from __future__ import annotations

import re
import statistics
from collections import defaultdict
from typing import Any

PLAN_STRUCTURE_FIXED_FIELDS = [
    "query_sweep_id",
    "query_run_id",
    "instance_id",
    "template_id",
]

PLAN_STRUCTURE_BASE_FEATURES = [
    "main_plan_node_count",
    "main_plan_max_depth",
    "main_plan_leaf_count",
    "main_plan_branch_node_count",
    "main_plan_avg_branching_factor",
    "main_plan_max_branching_factor",
    "remote_plan_leaf_count_sum",
    "remote_plan_avg_branching_factor",
    "aggregate_min_depth",
    "aggregate_max_depth",
    "sort_min_depth",
    "sort_max_depth",
    "join_min_depth",
    "join_max_depth",
    "foreign_scan_min_depth",
    "foreign_scan_max_depth",
    "custom_scan_min_depth",
    "custom_scan_max_depth",
    "aggregate_above_foreign_scan",
    "sort_above_foreign_scan",
    "limit_above_foreign_scan",
    "join_above_foreign_scan",
    "foreign_scan_under_aggregate",
    "foreign_scan_under_sort",
    "remote_aggregate_present",
    "remote_sort_present",
    "remote_join_present",
    "main_finalize_after_remote",
    "blocking_operator_count",
    "blocking_operator_min_depth",
    "blocking_operator_above_remote_count",
    "blocking_operator_below_remote_count",
    "first_blocking_operator_type",
    "first_blocking_operator_depth",
    "dominant_time_node_type",
    "dominant_time_node_depth",
    "dominant_time_node_actual_time_share",
    "dominant_rows_node_type",
    "dominant_rows_node_depth",
    "dominant_rows_node_row_share",
]


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _node_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("plan_id", "")), str(row.get("node_id", ""))


def _parent_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row.get("plan_id", "")), str(row.get("parent_node_id", ""))


def _slug_node_type(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "Unknown"
    parts = re.findall(r"[A-Za-z0-9]+", raw)
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Unknown"


def _child_counts(edges: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for edge in edges:
        parent = _parent_key(edge)
        if parent[0] and parent[1]:
            counts[parent] += 1
    return counts


def _tree_shape_features(
    *,
    prefix: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    if not nodes:
        return {
            f"{prefix}_plan_node_count": "",
            f"{prefix}_plan_max_depth": "",
            f"{prefix}_plan_leaf_count": "",
            f"{prefix}_plan_branch_node_count": "",
            f"{prefix}_plan_avg_branching_factor": "",
            f"{prefix}_plan_max_branching_factor": "",
        }

    counts = _child_counts(edges)
    node_keys = [_node_key(node) for node in nodes]
    child_count_values = [counts.get(key, 0) for key in node_keys]
    branch_counts = [value for value in child_count_values if value > 0]
    depths = [
        depth for depth in (_int_or_none(node.get("depth")) for node in nodes) if depth is not None
    ]
    return {
        f"{prefix}_plan_node_count": len(nodes),
        f"{prefix}_plan_max_depth": max(depths) if depths else "",
        f"{prefix}_plan_leaf_count": sum(1 for value in child_count_values if value == 0),
        f"{prefix}_plan_branch_node_count": len(branch_counts),
        f"{prefix}_plan_avg_branching_factor": statistics.fmean(branch_counts)
        if branch_counts
        else 0.0,
        f"{prefix}_plan_max_branching_factor": max(branch_counts) if branch_counts else 0,
    }


def _remote_shape_features(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    if not nodes:
        return {
            "remote_plan_leaf_count_sum": "",
            "remote_plan_avg_branching_factor": "",
        }

    counts = _child_counts(edges)
    child_count_values = [counts.get(_node_key(node), 0) for node in nodes]
    branch_counts = [value for value in child_count_values if value > 0]
    return {
        "remote_plan_leaf_count_sum": sum(1 for value in child_count_values if value == 0),
        "remote_plan_avg_branching_factor": statistics.fmean(branch_counts)
        if branch_counts
        else 0.0,
    }


def _matches_operator(node_type: str, operator: str) -> bool:
    if operator == "aggregate":
        return "Aggregate" in node_type
    if operator == "sort":
        return "Sort" in node_type
    if operator == "join":
        return "Join" in node_type or node_type == "Nested Loop"
    if operator == "limit":
        return node_type == "Limit"
    if operator == "foreign_scan":
        return node_type == "Foreign Scan"
    if operator == "custom_scan":
        return node_type == "Custom Scan"
    return False


def _operator_depth_features(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for operator in ("aggregate", "sort", "join", "foreign_scan", "custom_scan"):
        depths = [
            depth
            for depth in (
                _int_or_none(node.get("depth"))
                for node in nodes
                if _matches_operator(str(node.get("node_type", "")), operator)
            )
            if depth is not None
        ]
        result[f"{operator}_min_depth"] = min(depths) if depths else ""
        result[f"{operator}_max_depth"] = max(depths) if depths else ""
    return result


def _transition_count_features(edges: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for edge in edges:
        parent = _slug_node_type(edge.get("parent_node_type", ""))
        child = _slug_node_type(edge.get("child_node_type", ""))
        counts[f"parent_child_type_count_{parent}_{child}"] += 1
    return dict(sorted(counts.items()))


def _node_lookup(nodes: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {_node_key(node): node for node in nodes}


def _ancestors(
    node: dict[str, Any],
    nodes_by_key: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    ancestors: list[dict[str, Any]] = []
    current = node
    seen: set[tuple[str, str]] = set()
    while True:
        parent = nodes_by_key.get(_parent_key(current))
        if parent is None:
            return ancestors
        key = _node_key(parent)
        if key in seen:
            return ancestors
        seen.add(key)
        ancestors.append(parent)
        current = parent


def _has_ancestor_matching(
    *,
    node: dict[str, Any],
    nodes_by_key: dict[tuple[str, str], dict[str, Any]],
    operator: str,
) -> bool:
    return any(
        _matches_operator(str(ancestor.get("node_type", "")), operator)
        for ancestor in _ancestors(node, nodes_by_key)
    )


def _has_node_matching(nodes: list[dict[str, Any]], operator: str) -> bool:
    return any(
        _matches_operator(str(node.get("node_type", "")), operator) for node in nodes
    )


def _remote_boundary_features(
    *,
    main_nodes: list[dict[str, Any]],
    remote_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes_by_key = _node_lookup(main_nodes)
    foreign_scans = [
        node
        for node in main_nodes
        if _matches_operator(str(node.get("node_type", "")), "foreign_scan")
    ]

    aggregate_above = any(
        _has_ancestor_matching(node=node, nodes_by_key=nodes_by_key, operator="aggregate")
        for node in foreign_scans
    )
    sort_above = any(
        _has_ancestor_matching(node=node, nodes_by_key=nodes_by_key, operator="sort")
        for node in foreign_scans
    )
    limit_above = any(
        _has_ancestor_matching(node=node, nodes_by_key=nodes_by_key, operator="limit")
        for node in foreign_scans
    )
    join_above = any(
        _has_ancestor_matching(node=node, nodes_by_key=nodes_by_key, operator="join")
        for node in foreign_scans
    )

    return {
        "aggregate_above_foreign_scan": _bool_text(aggregate_above),
        "sort_above_foreign_scan": _bool_text(sort_above),
        "limit_above_foreign_scan": _bool_text(limit_above),
        "join_above_foreign_scan": _bool_text(join_above),
        "foreign_scan_under_aggregate": _bool_text(aggregate_above),
        "foreign_scan_under_sort": _bool_text(sort_above),
        "remote_aggregate_present": _bool_text(_has_node_matching(remote_nodes, "aggregate")),
        "remote_sort_present": _bool_text(_has_node_matching(remote_nodes, "sort")),
        "remote_join_present": _bool_text(_has_node_matching(remote_nodes, "join")),
        "main_finalize_after_remote": _bool_text(aggregate_above),
    }


def _is_blocking_operator(node_type: str) -> bool:
    return (
        "Sort" in node_type
        or "Aggregate" in node_type
        or node_type == "Materialize"
        or node_type == "Hash"
        or "Hash Join" in node_type
    )


def _node_depth(node: dict[str, Any]) -> int | None:
    return _int_or_none(node.get("depth"))


def _node_order_key(node: dict[str, Any]) -> tuple[int, str]:
    depth = _node_depth(node)
    return (depth if depth is not None else 1_000_000, str(node.get("node_path", "")))


def _blocking_operator_features(
    *,
    main_nodes: list[dict[str, Any]],
    remote_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes_by_key = _node_lookup(main_nodes)
    main_blocking = [
        node
        for node in main_nodes
        if _is_blocking_operator(str(node.get("node_type", "")))
    ]
    remote_blocking = [
        node
        for node in remote_nodes
        if _is_blocking_operator(str(node.get("node_type", "")))
    ]
    foreign_scans = [
        node
        for node in main_nodes
        if _matches_operator(str(node.get("node_type", "")), "foreign_scan")
    ]
    ancestor_blocking_keys = {
        _node_key(ancestor)
        for foreign_scan in foreign_scans
        for ancestor in _ancestors(foreign_scan, nodes_by_key)
        if _is_blocking_operator(str(ancestor.get("node_type", "")))
    }
    all_blocking = main_blocking + remote_blocking
    depths = [
        depth for depth in (_node_depth(node) for node in all_blocking) if depth is not None
    ]
    first = min(all_blocking, key=_node_order_key) if all_blocking else None

    return {
        "blocking_operator_count": len(all_blocking),
        "blocking_operator_min_depth": min(depths) if depths else "",
        "blocking_operator_above_remote_count": len(ancestor_blocking_keys),
        "blocking_operator_below_remote_count": len(remote_blocking),
        "first_blocking_operator_type": first.get("node_type", "") if first else "",
        "first_blocking_operator_depth": _node_depth(first) if first else "",
    }


def _node_loops(node: dict[str, Any]) -> float:
    loops = _float_or_none(node.get("actual_loops"))
    return loops if loops is not None else 1.0


def _node_actual_time(node: dict[str, Any]) -> float | None:
    value = _float_or_none(node.get("actual_total_time"))
    if value is None:
        return None
    return value * _node_loops(node)


def _node_actual_rows(node: dict[str, Any]) -> float | None:
    value = _float_or_none(node.get("actual_rows"))
    if value is None:
        return None
    return value * _node_loops(node)


def _dominant_node_features(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    timed_nodes = [
        (node, value)
        for node in nodes
        if (value := _node_actual_time(node)) is not None and value >= 0
    ]
    row_nodes = [
        (node, value)
        for node in nodes
        if (value := _node_actual_rows(node)) is not None and value >= 0
    ]

    result: dict[str, Any] = {
        "dominant_time_node_type": "",
        "dominant_time_node_depth": "",
        "dominant_time_node_actual_time_share": "",
        "dominant_rows_node_type": "",
        "dominant_rows_node_depth": "",
        "dominant_rows_node_row_share": "",
    }
    if timed_nodes:
        total_time = sum(value for _, value in timed_nodes)
        dominant_time_node, dominant_time = max(timed_nodes, key=lambda item: item[1])
        result.update(
            {
                "dominant_time_node_type": dominant_time_node.get("node_type", ""),
                "dominant_time_node_depth": _node_depth(dominant_time_node),
                "dominant_time_node_actual_time_share": dominant_time / total_time
                if total_time > 0
                else "",
            }
        )
    if row_nodes:
        total_rows = sum(value for _, value in row_nodes)
        dominant_rows_node, dominant_rows = max(row_nodes, key=lambda item: item[1])
        result.update(
            {
                "dominant_rows_node_type": dominant_rows_node.get("node_type", ""),
                "dominant_rows_node_depth": _node_depth(dominant_rows_node),
                "dominant_rows_node_row_share": dominant_rows / total_rows
                if total_rows > 0
                else "",
            }
        )
    return result


def plan_structure_feature_row(
    *,
    query_sweep_id: str,
    query_run_id: str,
    instance_id: str,
    template_id: str,
    plan_nodes: list[dict[str, Any]],
    plan_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    main_nodes = [row for row in plan_nodes if row.get("plan_scope") == "main"]
    main_edges = [row for row in plan_edges if row.get("plan_scope") == "main"]
    remote_scopes = {"fdw_remote", "fdw_auto_explain_remote", "citus_task_remote"}
    remote_nodes = [row for row in plan_nodes if row.get("plan_scope") in remote_scopes]
    remote_edges = [row for row in plan_edges if row.get("plan_scope") in remote_scopes]

    row: dict[str, Any] = {
        "query_sweep_id": query_sweep_id,
        "query_run_id": query_run_id,
        "instance_id": instance_id,
        "template_id": template_id,
    }
    row.update(_tree_shape_features(prefix="main", nodes=main_nodes, edges=main_edges))
    row.update(_remote_shape_features(nodes=remote_nodes, edges=remote_edges))
    row.update(_operator_depth_features(main_nodes))
    row.update(_remote_boundary_features(main_nodes=main_nodes, remote_nodes=remote_nodes))
    row.update(_blocking_operator_features(main_nodes=main_nodes, remote_nodes=remote_nodes))
    row.update(_dominant_node_features(main_nodes + remote_nodes))
    row.update(_transition_count_features(plan_edges))
    return row


def plan_structure_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    dynamic_fields = sorted(
        {
            key
            for row in rows
            for key in row
            if key.startswith("parent_child_type_count_")
        }
    )
    return PLAN_STRUCTURE_FIXED_FIELDS + PLAN_STRUCTURE_BASE_FEATURES + dynamic_fields


def finalize_plan_structure_rows(rows: list[dict[str, Any]]) -> list[str]:
    fieldnames = plan_structure_fieldnames(rows)
    dynamic_fields = [
        field for field in fieldnames if field.startswith("parent_child_type_count_")
    ]
    for row in rows:
        has_parsed_plan = row.get("main_plan_node_count") not in ("", None) or row.get(
            "remote_plan_leaf_count_sum"
        ) not in ("", None)
        if not has_parsed_plan:
            continue
        for field in dynamic_fields:
            row.setdefault(field, 0)
    return fieldnames
