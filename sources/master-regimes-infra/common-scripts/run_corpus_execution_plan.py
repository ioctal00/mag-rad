#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent


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
        return "../" + str(path.relative_to(WORKSPACE_ROOT))
    except ValueError:
        return path_text


def log_event(component: str, message: str) -> None:
    print(f"[{utc_clock()}] [{component}] {message}", flush=True)


def is_prefixed_log_line(value: str) -> bool:
    return value.startswith("[") and "] [" in value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a rendered master-regimes corpus execution plan."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "corpus-sweeps",
    )
    parser.add_argument(
        "--database-sweep-out-root",
        type=Path,
        default=None,
        help="Override nested database-sweep output root. Defaults under corpus run dir.",
    )
    parser.add_argument(
        "--hardware-snapshot-dir",
        type=Path,
        default=None,
        help=(
            "Reuse a hardware snapshot collected by a parent pressure batch. "
            "Without this option, collect one snapshot for the corpus attempt."
        ),
    )
    parser.add_argument(
        "--group-id",
        action="append",
        default=[],
        help="Only run this corpus execution group. May be repeated.",
    )
    parser.add_argument(
        "--max-groups",
        type=int,
        default=None,
        help="Run only the first N selected groups.",
    )
    parser.add_argument(
        "--max-instances-per-group",
        type=int,
        default=None,
        help=(
            "Temporarily cap workload.max_instances for each selected group. "
            "Use only for probe starts; rendered source plans are not modified."
        ),
    )
    parser.add_argument(
        "--logical-run-id",
        default="",
        help=(
            "Stable ID shared by multiple physical corpus attempts. Defaults to "
            "the selected label."
        ),
    )
    parser.add_argument(
        "--rerun-of",
        default="",
        help="Optional corpus_run_id or logical_run_id that this run continues.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and write a planned manifest without executing database sweeps.",
    )
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def resolve_path(plan_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Path not found: {candidate}")
    for base in (plan_path.parent, REPO_ROOT, WORKSPACE_ROOT, *plan_path.parents):
        resolved = (base / candidate).resolve()
        if resolved.exists():
            return resolved
    raise FileNotFoundError(f"Path not found: {raw_path}")


def run_and_get_path(
    command: list[str],
    *,
    component: str,
    env: dict[str, str] | None = None,
) -> Path:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    output_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output_lines.append(line)
        stripped = line.strip()
        if stripped:
            if stripped.startswith("/"):
                log_event(component, f"artifact -> {short_path(stripped)}")
            elif is_prefixed_log_line(stripped):
                print(stripped, flush=True)
            else:
                log_event(component, stripped)
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


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def resolve_hardware_snapshot(path: Path) -> Path:
    snapshot_dir = path.resolve()
    manifest_path = snapshot_dir / "hardware_snapshot_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Shared hardware snapshot manifest not found: {manifest_path}"
        )
    return snapshot_dir


def capped_sweep_config(
    *,
    source_config: Path,
    run_dir: Path,
    group_id: str,
    max_instances_per_group: int | None,
) -> Path:
    if max_instances_per_group is None:
        return source_config
    if max_instances_per_group < 1:
        raise ValueError("--max-instances-per-group must be >= 1 when set.")
    sweep_config = load_yaml(source_config)
    workload = sweep_config.setdefault("workload", {})
    if not isinstance(workload, dict):
        raise ValueError(f"{source_config} workload section must be a mapping.")
    workload["max_instances"] = max_instances_per_group
    capped_path = run_dir / "capped-sweeps" / f"{group_id}.max-{max_instances_per_group}.yml"
    write_yaml(capped_path, sweep_config)
    return capped_path


def status_payload(
    *,
    run_id: str,
    created_at_utc: str,
    logical_run_id: str,
    rerun_of: str,
    plan_path: Path,
    status: str,
    groups: list[dict[str, Any]],
    error: BaseException | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "corpus_run_id": run_id,
        "logical_run_id": logical_run_id,
        "rerun_of": rerun_of,
        "created_at_utc": created_at_utc,
        "updated_at_utc": timestamp(),
        "source_plan": str(plan_path),
        "status": status,
        "completed_group_count": sum(
            1 for group in groups if str(group.get("status", "")).startswith("completed")
        ),
        "group_count": len(groups),
    }
    if groups:
        payload["groups"] = groups
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)
    return payload


def manifest_payload(
    *,
    run_id: str,
    created_at_utc: str,
    logical_run_id: str,
    rerun_of: str,
    plan_path: Path,
    plan: dict[str, Any],
    dry_run: bool,
    database_out_root: Path,
    hardware_snapshot_dir: Path | None,
    groups: list[dict[str, Any]],
    status: str,
    error: BaseException | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "corpus_run_id": run_id,
        "logical_run_id": logical_run_id,
        "rerun_of": rerun_of,
        "created_at_utc": created_at_utc,
        "source_plan": str(plan_path),
        "corpus_id": plan.get("corpus_id", ""),
        "execution_backend": plan.get("execution_backend", ""),
        "dry_run": dry_run,
        "selected_group_count": len(groups),
        "database_sweep_out_root": str(database_out_root),
        "hardware_snapshot_dir": (
            None
            if hardware_snapshot_dir is None
            else str(hardware_snapshot_dir)
        ),
        "groups": groups,
        "status": status,
    }
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)
    return payload


def selected_groups(
    plan: dict[str, Any],
    group_ids: list[str],
    max_groups: int | None,
) -> list[dict[str, Any]]:
    groups = plan.get("groups", [])
    if not isinstance(groups, list) or not groups:
        raise ValueError("corpus_execution_plan.yml must contain non-empty groups list.")
    normalized = [group for group in groups if isinstance(group, dict)]
    if group_ids:
        wanted = set(group_ids)
        normalized = [group for group in normalized if str(group.get("group_id", "")) in wanted]
        missing = sorted(wanted - {str(group.get("group_id", "")) for group in normalized})
        if missing:
            raise ValueError(f"Requested group_id not found: {missing}")
    if max_groups is not None:
        normalized = normalized[:max_groups]
    if not normalized:
        raise ValueError("No corpus execution groups selected.")
    return normalized


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def planned_instance_count(group: dict[str, Any], max_instances_per_group: int | None) -> int:
    count = _int_value(group.get("instance_count", 0))
    if max_instances_per_group is not None:
        return min(count, max_instances_per_group)
    return count


def main() -> int:
    args = parse_args()
    plan_path = args.plan.resolve()
    plan = load_yaml(plan_path)
    created_at_utc = timestamp()
    label = args.label or str(plan.get("corpus_id", "corpus-run"))
    logical_run_id = args.logical_run_id or label
    corpus_run_id = f"{created_at_utc}-{label}"
    run_dir = (args.out_root / corpus_run_id).resolve()
    database_out_root = (
        args.database_sweep_out_root.resolve()
        if args.database_sweep_out_root is not None
        else run_dir / "database-sweeps"
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    groups = selected_groups(plan, args.group_id, args.max_groups)
    total_planned_instances = sum(
        planned_instance_count(group, args.max_instances_per_group) for group in groups
    )
    log_event(
        "CORPUS",
        (
            f"start run_id={corpus_run_id} logical_run_id={logical_run_id} "
            f"groups={len(groups)} instances={total_planned_instances} "
            f"dry_run={args.dry_run}"
        ),
    )
    log_event("CORPUS", f"artifacts -> {short_path(str(run_dir))}")
    group_results: list[dict[str, Any]] = []
    status_file = run_dir / "corpus_execution_status.json"
    write_json(
        status_file,
        status_payload(
            run_id=corpus_run_id,
            created_at_utc=created_at_utc,
            logical_run_id=logical_run_id,
            rerun_of=args.rerun_of,
            plan_path=plan_path,
            status="dry_run" if args.dry_run else "running",
            groups=group_results,
        ),
    )

    try:
        hardware_snapshot_dir: Path | None = None
        if not args.dry_run:
            if args.hardware_snapshot_dir is not None:
                hardware_snapshot_dir = resolve_hardware_snapshot(
                    args.hardware_snapshot_dir
                )
                log_event(
                    "CORPUS",
                    (
                        "hardware snapshot reused from parent "
                        f"artifact={short_path(str(hardware_snapshot_dir))}"
                    ),
                )
            else:
                hardware_started_at = time.monotonic()
                log_event(
                    "CORPUS",
                    "hardware snapshot start scope=corpus_attempt_global",
                )
                hardware_snapshot_dir = run_and_get_path(
                    [
                        sys.executable,
                        str(
                            REPO_ROOT
                            / "common-scripts"
                            / "collect_hardware_snapshot.py"
                        ),
                        "--label",
                        f"{corpus_run_id}-hardware",
                        "--scope",
                        "corpus_attempt_global",
                        "--out-root",
                        str(run_dir / "hardware-snapshots"),
                    ],
                    component="HW",
                )
                log_event(
                    "CORPUS",
                    (
                        "hardware snapshot done in "
                        f"{format_duration(hardware_started_at)}"
                    ),
                )
        completed_instance_offset = 0
        for group_index, group in enumerate(groups, start=1):
            group_started_at = time.monotonic()
            group_id = str(group.get("group_id", f"group-{group_index}"))
            group_planned_instances = planned_instance_count(
                group, args.max_instances_per_group
            )
            source_sweep_config = resolve_path(plan_path, str(group.get("sweep_config", "")))
            sweep_config = capped_sweep_config(
                source_config=source_sweep_config,
                run_dir=run_dir,
                group_id=group_id,
                max_instances_per_group=args.max_instances_per_group,
            )
            group_result: dict[str, Any] = {
                "group_index": group_index,
                "group_id": group_id,
                "sweep_id": group.get("sweep_id", ""),
                "dataset_profile_id": group.get("dataset_profile_id", ""),
                "runtime_config_id": group.get("runtime_config_id", ""),
                "target_group": group.get("target_group", ""),
                "cell_count": group.get("cell_count", ""),
                "instance_count": group.get("instance_count", ""),
                "sweep_config": str(sweep_config),
                "source_sweep_config": str(source_sweep_config),
                "max_instances_per_group": args.max_instances_per_group or "",
                "status": "planned" if args.dry_run else "running",
            }
            group_results.append(group_result)
            log_event(
                "CORPUS",
                (
                    f"group {group_index}/{len(groups)} start group_id={group_id} "
                    f"dataset={group_result['dataset_profile_id']} "
                    f"runtime={group_result['runtime_config_id']} "
                    f"target={group_result['target_group']} "
                    f"instances={group_planned_instances}/{total_planned_instances} "
                    f"global_offset={completed_instance_offset}"
                ),
            )
            write_json(
                status_file,
                status_payload(
                    run_id=corpus_run_id,
                    created_at_utc=created_at_utc,
                    logical_run_id=logical_run_id,
                    rerun_of=args.rerun_of,
                    plan_path=plan_path,
                    status="dry_run" if args.dry_run else "running",
                    groups=group_results,
                ),
            )
            if args.dry_run:
                log_event("CORPUS", f"group {group_index}/{len(groups)} planned")
                completed_instance_offset += group_planned_instances
                continue

            child_env = dict(os.environ)
            child_env.update(
                {
                    "CORPUS_PROGRESS_TOTAL": str(total_planned_instances),
                    "CORPUS_PROGRESS_OFFSET": str(completed_instance_offset),
                    "CORPUS_PROGRESS_GROUP_INDEX": str(group_index),
                    "CORPUS_PROGRESS_GROUP_COUNT": str(len(groups)),
                    "CORPUS_PROGRESS_GROUP_ID": group_id,
                }
            )
            database_command = [
                sys.executable,
                str(REPO_ROOT / "common-scripts" / "run_database_sweep.py"),
                "--sweep",
                str(sweep_config),
                "--label",
                group_id,
                "--out-root",
                str(database_out_root),
            ]
            if hardware_snapshot_dir is not None:
                database_command.extend(
                    [
                        "--hardware-snapshot-dir",
                        str(hardware_snapshot_dir),
                    ]
                )
            database_sweep_dir = run_and_get_path(
                database_command,
                component="DB",
                env=child_env,
            )
            database_manifest = load_yaml(database_sweep_dir / "database_sweep_manifest.json")
            group_status = "completed"
            query_status_counts: dict[str, int] = {}
            for execution in database_manifest.get("executions", []) or []:
                for status_name, count in (execution.get("query_count_by_status") or {}).items():
                    query_status_counts[str(status_name)] = (
                        query_status_counts.get(str(status_name), 0) + int(count)
                    )
            if query_status_counts.get("failed", 0) > 0:
                group_status = "completed_with_failures"
            elif query_status_counts.get("timeout", 0) > 0:
                group_status = "completed_with_timeouts"
            group_result.update(
                {
                    "status": group_status,
                    "database_sweep_dir": str(database_sweep_dir),
                    "database_sweep_index_dir": str(database_sweep_dir / "_index"),
                    "query_count_by_status": query_status_counts,
                }
            )
            log_event(
                "CORPUS",
                (
                    f"group {group_index}/{len(groups)} {group_status} "
                    f"in {format_duration(group_started_at)} "
                    f"query_status={query_status_counts}"
                ),
            )
            write_json(
                status_file,
                status_payload(
                    run_id=corpus_run_id,
                    created_at_utc=created_at_utc,
                    logical_run_id=logical_run_id,
                    rerun_of=args.rerun_of,
                    plan_path=plan_path,
                    status="running",
                    groups=group_results,
                ),
            )
            completed_instance_offset += group_planned_instances
    except BaseException as exc:
        if group_results and group_results[-1].get("status") == "running":
            group_results[-1]["status"] = (
                "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            )
        run_status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        write_json(
            status_file,
            status_payload(
                run_id=corpus_run_id,
                created_at_utc=created_at_utc,
                logical_run_id=logical_run_id,
                rerun_of=args.rerun_of,
                plan_path=plan_path,
                status=run_status,
                groups=group_results,
                error=exc,
            ),
        )
        write_json(
            run_dir / "corpus_execution_manifest.json",
            manifest_payload(
                run_id=corpus_run_id,
                created_at_utc=created_at_utc,
                logical_run_id=logical_run_id,
                rerun_of=args.rerun_of,
                plan_path=plan_path,
                plan=plan,
                dry_run=args.dry_run,
                database_out_root=database_out_root,
                hardware_snapshot_dir=hardware_snapshot_dir,
                groups=group_results,
                status=run_status,
                error=exc,
            ),
        )
        log_event("CORPUS", f"{run_status}: {type(exc).__name__}: {exc}")
        raise

    final_status = (
        "dry_run"
        if args.dry_run
        else (
            "completed_with_failures"
            if any(
                group.get("status") == "completed_with_failures"
                for group in group_results
            )
            else (
                "completed_with_timeouts"
                if any(
                    group.get("status") == "completed_with_timeouts"
                    for group in group_results
                )
                else "completed"
            )
        )
    )
    manifest = manifest_payload(
        run_id=corpus_run_id,
        created_at_utc=created_at_utc,
        logical_run_id=logical_run_id,
        rerun_of=args.rerun_of,
        plan_path=plan_path,
        plan=plan,
        dry_run=args.dry_run,
        database_out_root=database_out_root,
        hardware_snapshot_dir=hardware_snapshot_dir,
        groups=group_results,
        status=final_status,
    )
    write_json(run_dir / "corpus_execution_manifest.json", manifest)
    write_json(
        status_file,
        status_payload(
            run_id=corpus_run_id,
            created_at_utc=created_at_utc,
            logical_run_id=logical_run_id,
            rerun_of=args.rerun_of,
            plan_path=plan_path,
            status=final_status,
            groups=group_results,
        ),
    )
    print(str(run_dir), flush=True)
    log_event("CORPUS", f"{final_status} artifact -> {short_path(str(run_dir))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
