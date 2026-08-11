#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import yaml

csv.field_size_limit(sys.maxsize)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build observability tables across multiple physical corpus run attempts. "
            "This does not modify attempt folders."
        )
    )
    parser.add_argument(
        "--corpus-run-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "corpus-sweeps",
    )
    parser.add_argument(
        "--logical-run-id",
        required=True,
        help="Stable logical run ID shared by the original run and reruns.",
    )
    parser.add_argument("--out-dir", type=Path, default=None)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def apply_max_instances(
    rows: list[dict[str, str]],
    max_instances: Any,
) -> list[dict[str, str]]:
    if max_instances in (None, ""):
        return rows
    try:
        limit = int(max_instances)
    except (TypeError, ValueError):
        return rows
    if limit < 0:
        return rows
    return rows[:limit]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def read_csv_with_fields(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def rel(root: Path, value: Any) -> str:
    if not value:
        return ""
    path = Path(str(value))
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def resolve_path(config_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    for base in (config_path.parent, REPO_ROOT, WORKSPACE_ROOT, *config_path.parents):
        resolved = (base / candidate).resolve()
        if resolved.exists():
            return resolved
    return (WORKSPACE_ROOT / candidate).resolve()


def resolve_database_sweep_paths(
    attempt_dir: Path,
    group: dict[str, Any],
) -> tuple[str, str, str]:
    sweep_dir = str(group.get("database_sweep_dir", ""))
    index_dir = str(group.get("database_sweep_index_dir", ""))
    if index_dir and Path(index_dir).exists():
        return sweep_dir, index_dir, "corpus_manifest"

    group_id = str(group.get("group_id", ""))
    sweep_root = attempt_dir / "database-sweeps"
    candidates = [
        candidate
        for candidate in sweep_root.glob("*")
        if candidate.is_dir()
        and candidate.name.endswith(group_id)
        and (candidate / "_index" / "query_runs.csv").exists()
    ]
    if len(candidates) != 1:
        return sweep_dir, index_dir, ""

    recovered_sweep_dir = candidates[0].resolve()
    return (
        str(recovered_sweep_dir),
        str(recovered_sweep_dir / "_index"),
        "recovered_after_postprocessing_failure",
    )


def merged_fieldnames(rows: list[dict[str, Any]], preferred: list[str]) -> list[str]:
    result = list(preferred)
    seen = set(result)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                result.append(key)
    return result


def status_rank(status: str) -> int:
    normalized = status.strip().lower()
    if normalized == "completed":
        return 4
    if normalized == "completed_with_timeouts":
        return 3
    if normalized == "timeout":
        return 2
    if normalized in {"failed", "interrupted"}:
        return 1
    return 0


def logical_query_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(row.get(field, ""))
        for field in (
            "dataset_id",
            "runtime_config_id",
            "target_group",
            "corpus_cell_id",
            "instance_id",
            "condition_id",
            "repetition_index",
        )
    )


def planned_query_row(
    *,
    planned: dict[str, Any],
    group: dict[str, Any],
    common: dict[str, Any],
) -> dict[str, Any]:
    """Build a planned row with the same identity as an indexed query row."""
    dataset_id = (
        planned.get("dataset_profile_id") or group.get("dataset_profile_id", "")
    )
    return {
        **common,
        "execution_status": "missing",
        "timed_out": "False",
        "dataset_id": dataset_id,
        "dataset_profile_id": dataset_id,
        # Bundled groups use "multiple" here, but each slot has one real runtime.
        "runtime_config_id": (
            planned.get("runtime_config_id") or group.get("runtime_config_id", "")
        ),
        "target_group": group.get("target_group", ""),
        "corpus_id": planned.get("corpus_id", ""),
        "corpus_cell_id": planned.get("corpus_cell_id", ""),
        "condition_id": planned.get("condition_id", ""),
        "repetition_index": planned.get("repetition_index", ""),
        "run_order": planned.get("run_order", ""),
        "logical_question_id": planned.get("logical_question_id", ""),
        "execution_strategy": planned.get("execution_strategy", ""),
        "intervention_axis": planned.get("intervention_axis", ""),
        "instance_id": planned.get("instance_id", ""),
        "template_id": planned.get("template_id", ""),
        "source_sql_file": planned.get("rendered_sql_path", ""),
        "expected_shape_tags": planned.get("expected_shape_tags", ""),
        "param_json": planned.get("param_json", ""),
    }


QUERY_RUN_SCOPED_TABLES = {
    "execution_features.csv",
    "feature_overview.csv",
    "fdw_remote_plans.csv",
    "node_artifacts.csv",
    "plan_edges.csv",
    "plan_files.csv",
    "plan_nodes.csv",
    "plan_structure_features.csv",
    "query_bindings.csv",
    "query_nodes.csv",
    "query_runs.csv",
    "region_fragments.csv",
    "worker_task_fragments.csv",
    "remote_edge_observations.csv",
}

INSTANCE_SCOPED_TABLES = {
    "instance_summary_features.csv",
}

RUN_CONTEXT_TABLES = {
    "corpus_cells.csv",
    "dataset_capability_audits.csv",
    "dataset_runs.csv",
    "global_snapshots.csv",
    "hardware_nodes.csv",
    "runtime_sweeps.csv",
    "result_validations.csv",
}


def write_logical_index(
    *,
    out_dir: Path,
    resolved_rows: list[dict[str, Any]],
    query_rows: list[dict[str, Any]],
) -> None:
    index_dir = out_dir / "_index"
    selected_query_run_ids = {
        str(row.get("resolved_query_run_id", ""))
        for row in resolved_rows
        if row.get("resolved_status") == "completed"
        and str(row.get("resolved_query_run_id", ""))
    }
    selected_index_dirs = {
        str(row.get("database_sweep_index_dir", ""))
        for row in query_rows
        if str(row.get("query_run_id", "")) in selected_query_run_ids
        and str(row.get("database_sweep_index_dir", ""))
    }
    source_index_dirs = [Path(value) for value in sorted(selected_index_dirs)]
    selected_instance_ids = {
        str(row.get("instance_id", ""))
        for row in resolved_rows
        if row.get("resolved_status") == "completed"
        and str(row.get("instance_id", ""))
    }
    table_names = sorted(QUERY_RUN_SCOPED_TABLES | INSTANCE_SCOPED_TABLES | RUN_CONTEXT_TABLES)
    table_counts: dict[str, int] = {}
    for table_name in table_names:
        merged_rows: list[dict[str, Any]] = []
        fieldnames: list[str] = []
        seen_fields: set[str] = set()
        seen_context_rows: set[tuple[tuple[str, str], ...]] = set()
        for source_index_dir in source_index_dirs:
            rows, fields = read_csv_with_fields(source_index_dir / table_name)
            for field in fields:
                if field not in seen_fields:
                    seen_fields.add(field)
                    fieldnames.append(field)
            for row in rows:
                query_run_id = str(row.get("query_run_id", ""))
                if table_name in QUERY_RUN_SCOPED_TABLES:
                    if query_run_id not in selected_query_run_ids:
                        continue
                    merged_rows.append({**row})
                    continue
                if table_name in INSTANCE_SCOPED_TABLES:
                    if str(row.get("instance_id", "")) not in selected_instance_ids:
                        continue
                    merged_rows.append({**row})
                    continue
                dedupe_key = tuple(sorted((key, str(value)) for key, value in row.items()))
                if dedupe_key in seen_context_rows:
                    continue
                seen_context_rows.add(dedupe_key)
                merged_rows.append({**row})
        write_csv(index_dir / table_name, merged_rows, fieldnames)
        table_counts[table_name.removesuffix(".csv")] = len(merged_rows)

    canonical_schema_path = WORKSPACE_ROOT / "master-regimes" / "docs" / "feature_schema.yml"
    schema_candidates = (
        [canonical_schema_path]
        + [source_index_dir / "feature_schema.yml" for source_index_dir in source_index_dirs]
    )
    for schema_path in schema_candidates:
        if schema_path.exists():
            (index_dir / "feature_schema.yml").write_text(
                schema_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            break

    (index_dir / "index_manifest.json").write_text(
        json.dumps(
            {
                "index_contract": "master_regimes_logical_run_index_v1",
                "source_logical_index_dir": str(out_dir),
                "source_index_dirs": [str(path) for path in source_index_dirs],
                "selected_query_run_count": len(selected_query_run_ids),
                "tables": table_counts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (index_dir / "README.md").write_text(
        "\n".join(
            [
                "# Logical Run Index",
                "",
                "This folder merges the best completed query attempts for one logical",
                "corpus run. One `query_run_id` remains one clustering observation;",
                "`region_fragments.csv`, `worker_task_fragments.csv`, and",
                "`remote_edge_observations.csv` are child evidence tables.",
                "",
                "Generated by `index_corpus_run_attempts.py`.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    root = args.corpus_run_root.resolve()
    out_dir = (
        args.out_dir.resolve()
        if args.out_dir is not None
        else root / "_logical-runs" / args.logical_run_id
    )

    attempt_manifests: list[tuple[Path, dict[str, Any]]] = []
    candidate_dirs = {
        path.parent
        for path in [
            *root.glob("*/corpus_execution_manifest.json"),
            *root.glob("*/corpus_execution_status.json"),
        ]
    }
    for attempt_dir in sorted(candidate_dirs):
        manifest_path = attempt_dir / "corpus_execution_manifest.json"
        status_path = attempt_dir / "corpus_execution_status.json"
        manifest = load_json(manifest_path) or load_json(status_path)
        logical_run_id = str(manifest.get("logical_run_id") or manifest.get("corpus_run_id", ""))
        if logical_run_id == args.logical_run_id:
            attempt_manifests.append((attempt_dir, manifest))

    attempt_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    query_rows: list[dict[str, Any]] = []

    for attempt_number, (attempt_dir, manifest) in enumerate(
        sorted(attempt_manifests, key=lambda item: str(item[1].get("created_at_utc", ""))),
        start=1,
    ):
        corpus_run_id = str(manifest.get("corpus_run_id", attempt_dir.name))
        status = str(manifest.get("status", ""))
        groups = manifest.get("groups", []) or []
        attempt_rows.append(
            {
                "logical_run_id": args.logical_run_id,
                "attempt_number": attempt_number,
                "corpus_run_id": corpus_run_id,
                "created_at_utc": manifest.get("created_at_utc", ""),
                "status": status,
                "rerun_of": manifest.get("rerun_of", ""),
                "source_plan": manifest.get("source_plan", ""),
                "attempt_dir": str(attempt_dir),
                "selected_group_count": manifest.get("selected_group_count", ""),
                "completed_group_count": sum(
                    1
                    for group in groups
                    if str(group.get("status", "")).startswith("completed")
                ),
            }
        )
        for group in groups:
            database_sweep_dir, database_sweep_index_dir, path_source = (
                resolve_database_sweep_paths(attempt_dir, group)
            )
            group_row = {
                "logical_run_id": args.logical_run_id,
                "attempt_number": attempt_number,
                "corpus_run_id": corpus_run_id,
                "group_id": group.get("group_id", ""),
                "group_index": group.get("group_index", ""),
                "status": group.get("status", ""),
                "dataset_profile_id": group.get("dataset_profile_id", ""),
                "runtime_config_id": group.get("runtime_config_id", ""),
                "target_group": group.get("target_group", ""),
                "cell_count": group.get("cell_count", ""),
                "instance_count": group.get("instance_count", ""),
                "sweep_config": group.get("sweep_config", ""),
                "database_sweep_dir": database_sweep_dir,
                "database_sweep_index_dir": database_sweep_index_dir,
                "database_sweep_path_source": path_source,
            }
            group_rows.append(group_row)
            raw_index_dir = database_sweep_index_dir
            index_dir = Path(raw_index_dir) if raw_index_dir else None
            indexed_queries = read_csv(index_dir / "query_runs.csv") if index_dir else []
            for query in indexed_queries:
                query_rows.append(
                    {
                        "logical_run_id": args.logical_run_id,
                        "attempt_number": attempt_number,
                        "corpus_run_id": corpus_run_id,
                        "group_id": group.get("group_id", ""),
                        "database_sweep_index_dir": str(index_dir or ""),
                        **query,
                        "target_group": query.get("target_group") or group.get("target_group", ""),
                    }
                )
            seen_query_keys = {
                logical_query_key(row)
                for row in query_rows
                if row.get("corpus_run_id") == corpus_run_id
                and row.get("group_id") == group.get("group_id", "")
            }
            sweep_config = Path(str(group.get("sweep_config", "")))
            if sweep_config.exists():
                sweep = load_yaml(sweep_config)
                manifest_raw = str(
                    (sweep.get("workload") or {}).get("instance_manifest") or ""
                )
                if manifest_raw:
                    manifest_path = resolve_path(sweep_config, manifest_raw)
                    planned_rows = apply_max_instances(
                        read_csv(manifest_path),
                        (sweep.get("workload") or {}).get("max_instances"),
                    )
                    for planned in planned_rows:
                        instance_id = str(planned.get("instance_id", ""))
                        if not instance_id:
                            continue
                        missing_row = planned_query_row(
                            planned=planned,
                            group=group,
                            common={
                                "logical_run_id": args.logical_run_id,
                                "attempt_number": attempt_number,
                                "corpus_run_id": corpus_run_id,
                                "group_id": group.get("group_id", ""),
                                "database_sweep_index_dir": str(index_dir or ""),
                            },
                        )
                        planned_key = logical_query_key(missing_row)
                        if planned_key in seen_query_keys:
                            continue
                        missing_row["missing_reason"] = (
                            "group_failed_before_query_index"
                            if index_dir is None or not index_dir.exists()
                            else "not_found_in_query_index"
                        )
                        query_rows.append(missing_row)
                        seen_query_keys.add(planned_key)

    key_fields = [
        "dataset_id",
        "runtime_config_id",
        "target_group",
        "corpus_cell_id",
        "instance_id",
        "condition_id",
        "repetition_index",
    ]
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in query_rows:
        key = logical_query_key(row)
        grouped.setdefault(key, []).append(row)

    resolved_rows: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        best = max(
            rows,
            key=lambda row: (
                status_rank(str(row.get("execution_status", ""))),
                int(row.get("attempt_number", 0) or 0),
            ),
        )
        latest = max(rows, key=lambda row: int(row.get("attempt_number", 0) or 0))
        resolved_rows.append(
            {
                **{field: key[index] for index, field in enumerate(key_fields)},
                "attempt_count": len(rows),
                "resolved_status": best.get("execution_status", ""),
                "resolved_attempt_number": best.get("attempt_number", ""),
                "resolved_query_run_id": best.get("query_run_id", ""),
                "group_id": best.get("group_id", ""),
                "latest_status": latest.get("execution_status", ""),
                "latest_attempt_number": latest.get("attempt_number", ""),
                "latest_query_run_id": latest.get("query_run_id", ""),
                "needs_rerun": str(best.get("execution_status", "") != "completed").lower(),
                "hard_timeout_seconds": best.get("hard_timeout_seconds", ""),
                "timeout_phase": best.get("timeout_phase", ""),
                "resolved_database_sweep_index_dir": best.get("database_sweep_index_dir", ""),
                "template_id": best.get("template_id", ""),
                "logical_question_id": best.get("logical_question_id", ""),
                "execution_strategy": best.get("execution_strategy", ""),
                "intervention_axis": best.get("intervention_axis", ""),
                "run_order": best.get("run_order", ""),
            }
        )

    write_csv(
        out_dir / "corpus_attempts.csv",
        attempt_rows,
        [
            "logical_run_id",
            "attempt_number",
            "corpus_run_id",
            "created_at_utc",
            "status",
            "rerun_of",
            "source_plan",
            "attempt_dir",
            "selected_group_count",
            "completed_group_count",
        ],
    )
    write_csv(
        out_dir / "group_attempts.csv",
        group_rows,
        [
            "logical_run_id",
            "attempt_number",
            "corpus_run_id",
            "group_id",
            "group_index",
            "status",
            "dataset_profile_id",
            "runtime_config_id",
            "target_group",
            "cell_count",
            "instance_count",
            "sweep_config",
            "database_sweep_dir",
            "database_sweep_index_dir",
            "database_sweep_path_source",
        ],
    )
    write_csv(
        out_dir / "query_attempts.csv",
        query_rows,
        merged_fieldnames(
            query_rows,
            [
                "logical_run_id",
                "attempt_number",
                "corpus_run_id",
                "group_id",
                "database_sweep_id",
                "query_sweep_id",
                "query_run_id",
                "execution_status",
                "timed_out",
                "hard_timeout_seconds",
                "timeout_phase",
                "dataset_id",
                "runtime_config_id",
                "target_group",
                "corpus_cell_id",
                "instance_id",
                "condition_id",
                "repetition_index",
                "run_order",
                "template_id",
                "elapsed_seconds",
            ],
        ),
    )
    write_csv(
        out_dir / "resolved_query_status.csv",
        resolved_rows,
        [
            *key_fields,
            "attempt_count",
            "resolved_status",
            "resolved_attempt_number",
            "resolved_query_run_id",
            "group_id",
            "latest_status",
            "latest_attempt_number",
            "latest_query_run_id",
            "needs_rerun",
            "hard_timeout_seconds",
            "timeout_phase",
            "resolved_database_sweep_index_dir",
            "template_id",
            "logical_question_id",
            "execution_strategy",
            "intervention_axis",
            "run_order",
        ],
    )
    write_logical_index(
        out_dir=out_dir,
        resolved_rows=resolved_rows,
        query_rows=query_rows,
    )
    (out_dir / "logical_run_index_manifest.json").write_text(
        json.dumps(
            {
                "logical_run_id": args.logical_run_id,
                "corpus_run_root": str(root),
                "index_dir": str(out_dir),
                "attempt_count": len(attempt_rows),
                "group_attempt_count": len(group_rows),
                "query_attempt_count": len(query_rows),
                "resolved_query_count": len(resolved_rows),
                "needs_rerun_count": sum(
                    1 for row in resolved_rows if row.get("needs_rerun") == "true"
                ),
                "logical_index_dir": str(out_dir / "_index"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(str(out_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
