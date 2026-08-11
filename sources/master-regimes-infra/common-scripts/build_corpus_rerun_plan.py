#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent


SEGMENT_FIELDS = ["dataset_id", "runtime_config_id", "target_group"]
ExecutionKey = tuple[str, ...]
MAX_RERUN_GROUP_ID_CHARS = 80


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a segment-optimized corpus rerun plan from a logical corpus "
            "run index. The generated plan groups unresolved query instances by "
            "dataset/runtime/target segment so environment setup is not zig-zagged."
        )
    )
    parser.add_argument("--source-plan", type=Path, required=True)
    parser.add_argument("--logical-index-dir", type=Path, required=True)
    parser.add_argument("--label", default="rerun")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--statuses",
        default="timeout,failed,missing,interrupted",
        help=(
            "Comma-separated resolved_status values to include. Defaults to "
            "timeout,failed,missing,interrupted."
        ),
    )
    parser.add_argument(
        "--hard-timeout-seconds",
        type=int,
        default=0,
        help="Optional timeout override for generated rerun sweep configs.",
    )
    parser.add_argument(
        "--timeout-grace-seconds",
        type=int,
        default=30,
        help="Grace period used when --hard-timeout-seconds is set.",
    )
    parser.add_argument(
        "--include-missing-from-source-plan",
        action="store_true",
        help=(
            "Also select instances present in the current source execution plan "
            "but absent from resolved_query_status.csv. Use this after the corpus "
            "manifest/source plan changes and an existing logical run needs only "
            "the newly planned cells."
        ),
    )
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def resolve_path(base: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    for root in (base, REPO_ROOT, WORKSPACE_ROOT, *base.parents):
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return (base / candidate).resolve()


def workspace_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(resolved)


def bounded_rerun_group_id(value: str) -> str:
    if len(value) <= MAX_RERUN_GROUP_ID_CHARS:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    remaining = MAX_RERUN_GROUP_ID_CHARS - len(digest) - 4
    prefix_length = remaining // 2
    suffix_length = remaining - prefix_length
    return f"{value[:prefix_length]}--{digest}--{value[-suffix_length:]}"


def segment_key_from_row(row: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(str(row.get(field, "")) for field in SEGMENT_FIELDS)  # type: ignore[return-value]


def group_segment_key(group: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(group.get("dataset_profile_id", "")),
        str(group.get("runtime_config_id", "")),
        str(group.get("target_group", "")),
    )


def group_segment_keys(group: dict[str, Any]) -> list[tuple[str, str, str]]:
    runtime_ids = [
        str(value)
        for value in (group.get("runtime_config_ids") or [])
        if str(value)
    ]
    if not runtime_ids:
        runtime_ids = [str(group.get("runtime_config_id", ""))]
    return [
        (
            str(group.get("dataset_profile_id", "")),
            runtime_id,
            str(group.get("target_group", "")),
        )
        for runtime_id in runtime_ids
    ]


def execution_key(row: dict[str, Any]) -> ExecutionKey:
    condition_id = str(row.get("condition_id", "")).strip()
    repetition_index = str(row.get("repetition_index", "")).strip()
    if condition_id and repetition_index:
        return ("repeatability", condition_id, repetition_index)
    return ("legacy", str(row.get("instance_id", "")))


def execution_key_label(key: ExecutionKey) -> str:
    return ":".join(key)


def selected_unresolved_rows(
    *,
    logical_index_dir: Path,
    statuses: set[str],
) -> list[dict[str, str]]:
    rows = read_csv(logical_index_dir / "resolved_query_status.csv")
    selected: list[dict[str, str]] = []
    for row in rows:
        if row.get("needs_rerun", "").strip().lower() != "true":
            continue
        status = row.get("resolved_status", "").strip().lower()
        if status in statuses:
            selected.append(row)
    return selected


def source_plan_missing_rows(
    *,
    source_plan_path: Path,
    source_groups: list[dict[str, Any]],
    resolved_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    resolved_execution_keys = {
        execution_key(row)
        for row in resolved_rows
        if row.get("instance_id", "")
    }
    selected: list[dict[str, str]] = []
    for group in source_groups:
        source_instance_manifest = resolve_path(
            source_plan_path.parent,
            str(group.get("instance_manifest", "")),
        )
        target_group = str(group.get("target_group", ""))
        dataset_id = str(group.get("dataset_profile_id", ""))
        runtime_config_id = str(group.get("runtime_config_id", ""))
        for planned in read_csv(source_instance_manifest):
            instance_id = planned.get("instance_id", "")
            if (
                not instance_id
                or execution_key(planned) in resolved_execution_keys
            ):
                continue
            selected.append(
                {
                    "dataset_id": dataset_id,
                    "runtime_config_id": runtime_config_id,
                    "target_group": target_group,
                    "corpus_cell_id": planned.get("corpus_cell_id", ""),
                    "instance_id": instance_id,
                    "condition_id": planned.get("condition_id", ""),
                    "repetition_index": planned.get("repetition_index", ""),
                    "run_order": planned.get("run_order", ""),
                    "template_id": planned.get("template_id", ""),
                    "logical_question_id": planned.get("logical_question_id", ""),
                    "execution_strategy": planned.get("execution_strategy", ""),
                    "intervention_axis": planned.get("intervention_axis", ""),
                    "attempt_count": "0",
                    "resolved_status": "missing",
                    "latest_status": "missing",
                    "needs_rerun": "true",
                    "missing_reason": "not_present_in_logical_resolved_status",
                }
            )
    return selected


def copy_instance_rows(
    *,
    source_manifest: Path,
    selected_execution_keys: set[ExecutionKey],
    output_manifest: Path,
    queries_dir: Path,
) -> tuple[list[dict[str, str]], list[str]]:
    source_rows = read_csv(source_manifest)
    if not source_rows:
        return [], sorted(
            execution_key_label(key) for key in selected_execution_keys
        )
    fieldnames = list(source_rows[0])
    selected_rows: list[dict[str, str]] = []
    found: set[ExecutionKey] = set()
    for row in source_rows:
        key = execution_key(row)
        if key not in selected_execution_keys:
            continue
        copied = dict(row)
        source_sql = Path(str(row.get("rendered_sql_path", "")))
        if not source_sql.is_absolute():
            source_sql = source_manifest.parent / source_sql
        if source_sql.exists():
            queries_dir.mkdir(parents=True, exist_ok=True)
            target_sql = queries_dir / source_sql.name
            shutil.copy2(source_sql, target_sql)
            copied["rendered_sql_path"] = str(target_sql.resolve())
        selected_rows.append(copied)
        found.add(key)
    write_csv(output_manifest, selected_rows, fieldnames)
    return selected_rows, sorted(
        execution_key_label(key) for key in selected_execution_keys - found
    )


def main() -> int:
    args = parse_args()
    source_plan_path = args.source_plan.resolve()
    logical_index_dir = args.logical_index_dir.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (
        args.out_dir.resolve()
        if args.out_dir is not None
        else REPO_ROOT
        / "generated"
        / "runs"
        / "corpus-sweeps"
        / "_rerun-plans"
        / f"{timestamp}-{args.label}"
    )

    source_plan = load_yaml(source_plan_path)
    statuses = {value.strip().lower() for value in args.statuses.split(",") if value.strip()}
    unresolved_rows = selected_unresolved_rows(
        logical_index_dir=logical_index_dir,
        statuses=statuses,
    )
    source_groups = [
        group
        for group in source_plan.get("groups", []) or []
        if isinstance(group, dict)
    ]
    resolved_rows = read_csv(logical_index_dir / "resolved_query_status.csv")
    if args.include_missing_from_source_plan and not resolved_rows:
        raise ValueError(
            "--include-missing-from-source-plan requires an existing "
            "resolved_query_status.csv with at least one row; refusing to select "
            "the entire source plan as a rerun."
        )
    if args.include_missing_from_source_plan:
        unresolved_rows.extend(
            source_plan_missing_rows(
                source_plan_path=source_plan_path,
                source_groups=source_groups,
                resolved_rows=resolved_rows,
            )
        )
    unresolved_by_segment: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in unresolved_rows:
        unresolved_by_segment.setdefault(segment_key_from_row(row), []).append(row)
    groups_by_segment = {
        segment_key: group
        for group in source_groups
        for segment_key in group_segment_keys(group)
    }

    plan_groups: list[dict[str, Any]] = []
    selection_rows: list[dict[str, str]] = []
    warnings: list[str] = []
    for segment_key, rows in sorted(unresolved_by_segment.items()):
        source_group = groups_by_segment.get(segment_key)
        if source_group is None:
            warnings.append(
                "No source group found for segment "
                f"dataset={segment_key[0]} runtime={segment_key[1]} target={segment_key[2]}"
            )
            continue

        source_instance_manifest = resolve_path(
            source_plan_path.parent,
            str(source_group.get("instance_manifest", "")),
        )
        bundled_group = len(group_segment_keys(source_group)) > 1
        runtime_suffix = f"__{segment_key[1]}" if bundled_group else ""
        rerun_group_id = bounded_rerun_group_id(
            f"{source_group['group_id']}{runtime_suffix}__{args.label}"
        )
        group_dir = out_dir / "groups" / rerun_group_id
        instance_manifest = group_dir / "instance_manifest.csv"
        selected_execution_keys = {execution_key(row) for row in rows}
        selected_rows, missing = copy_instance_rows(
            source_manifest=source_instance_manifest,
            selected_execution_keys=selected_execution_keys,
            output_manifest=instance_manifest,
            queries_dir=group_dir / "queries",
        )
        if missing:
            warnings.append(
                f"{rerun_group_id}: {len(missing)} selected instance(s) not found "
                f"in source manifest: {', '.join(missing[:5])}"
            )
        if not selected_rows:
            continue

        source_sweep_config = resolve_path(
            source_plan_path.parent,
            str(source_group.get("sweep_config", "")),
        )
        sweep_config = load_yaml(source_sweep_config)
        sweep_config["sweep_id"] = rerun_group_id
        if bundled_group:
            sweep_config["runtime_configs"] = [
                runtime
                for runtime in sweep_config.get("runtime_configs", []) or []
                if str(runtime.get("id", "")) == segment_key[1]
            ]
            if len(sweep_config["runtime_configs"]) != 1:
                raise ValueError(
                    f"Expected one runtime config {segment_key[1]} in "
                    f"{source_sweep_config}"
                )
        sweep_config.setdefault("workload", {})["instance_manifest"] = str(
            instance_manifest.resolve()
        )
        sweep_config["workload"].pop("max_instances", None)
        collection = sweep_config.setdefault("collection", {})
        if args.hard_timeout_seconds > 0:
            collection["hard_timeout_seconds"] = args.hard_timeout_seconds
            collection["timeout_grace_seconds"] = args.timeout_grace_seconds
        sweep_file = out_dir / "sweeps" / f"{rerun_group_id}.yml"
        write_yaml(sweep_file, sweep_config)

        unique_cells = sorted({row.get("corpus_cell_id", "") for row in selected_rows})
        strategies = sorted({row.get("execution_strategy", "") for row in selected_rows})
        plan_group = {
            **source_group,
            "group_id": rerun_group_id,
            "sweep_id": rerun_group_id,
            "source_group_id": source_group.get("group_id", ""),
            "rerun_plan": True,
            "rerun_reason_statuses": ",".join(sorted(statuses)),
            "cell_count": len([cell for cell in unique_cells if cell]),
            "instance_count": len(selected_rows),
            "strategies": strategies,
            "runtime_config_id": segment_key[1],
            "runtime_config_ids": [segment_key[1]],
            "instance_manifest": workspace_relative(instance_manifest),
            "sweep_config": workspace_relative(sweep_file),
        }
        plan_groups.append(plan_group)
        for row in rows:
            selection_rows.append(
                {
                    **row,
                    "rerun_group_id": rerun_group_id,
                    "source_group_id": str(source_group.get("group_id", "")),
                    "rerun_instance_manifest": str(instance_manifest.resolve()),
                    "rerun_sweep_config": str(sweep_file.resolve()),
                }
            )

    execution_budget = dict(source_plan.get("execution_budget", {}) or {})
    if args.hard_timeout_seconds > 0:
        execution_budget["hard_timeout_seconds"] = args.hard_timeout_seconds
        execution_budget["timeout_grace_seconds"] = args.timeout_grace_seconds
    plan = {
        "corpus_id": source_plan.get("corpus_id", ""),
        "source_plan": workspace_relative(source_plan_path),
        "source_logical_index_dir": workspace_relative(logical_index_dir),
        "rerun_plan": True,
        "rerun_label": args.label,
        "created_at_utc": timestamp,
        "selection_policy": {
            "needs_rerun": True,
            "resolved_statuses": sorted(statuses),
            "include_missing_from_source_plan": bool(args.include_missing_from_source_plan),
            "segment_fields": SEGMENT_FIELDS,
            "environment_setup_policy": "one setup per dataset/runtime/target segment",
        },
        "region": source_plan.get("region", "eu"),
        "execution_budget": execution_budget,
        "execution_backend": source_plan.get(
            "execution_backend", "master-regimes-infra.database_sweep"
        ),
        "group_count": len(plan_groups),
        "groups": plan_groups,
    }
    plan_path = out_dir / "corpus_execution_plan.yml"
    write_yaml(plan_path, plan)
    if selection_rows:
        write_csv(
            out_dir / "rerun_selection.csv",
            selection_rows,
            [
                "dataset_id",
                "runtime_config_id",
                "target_group",
                "corpus_cell_id",
                "instance_id",
                "condition_id",
                "repetition_index",
                "run_order",
                "template_id",
                "resolved_status",
                "latest_status",
                "missing_reason",
                "attempt_count",
                "rerun_group_id",
                "source_group_id",
                "rerun_instance_manifest",
                "rerun_sweep_config",
            ],
        )
    (out_dir / "rerun_plan_manifest.json").write_text(
        json.dumps(
            {
                "created_at_utc": timestamp,
                "source_plan": str(source_plan_path),
                "logical_index_dir": str(logical_index_dir),
                "out_dir": str(out_dir),
                "corpus_execution_plan": str(plan_path),
                "selected_query_count": len(selection_rows),
                "segment_count": len(plan_groups),
                "statuses": sorted(statuses),
                "warnings": warnings,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(str(plan_path), flush=True)
    if warnings:
        for warning in warnings:
            print(f"WARNING: {warning}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
