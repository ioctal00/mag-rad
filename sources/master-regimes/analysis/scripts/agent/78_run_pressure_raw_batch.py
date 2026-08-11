from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
INFRA_ROOT = WORKSPACE_ROOT / "master-regimes-infra"
DEFAULT_PROGRAM = REPO_ROOT / "generated/corpus/pressure-raw-v1/pressure_raw_program.yml"
PROGRAM_CONSOLIDATOR = (
    REPO_ROOT
    / "analysis/scripts/agent/86_consolidate_pressure_raw_program.py"
)


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def clock() -> str:
    return datetime.now(UTC).strftime("%H:%M:%SZ")


def log(component: str, message: str) -> None:
    print(f"[{clock()}] [{component}] {message}", flush=True)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def resolve(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkpoint_artifact_completed(event: dict[str, Any]) -> bool:
    collection_dir = Path(str(event.get("collection_dir", "")))
    manifest_path = collection_dir / "execution_manifest.json"
    status_path = collection_dir / "execution_status.json"
    try:
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {}
        )
        status = (
            json.loads(status_path.read_text(encoding="utf-8"))
            if status_path.is_file()
            else {}
        )
    except (OSError, json.JSONDecodeError):
        return False
    execution_status = str(
        manifest.get("execution_status")
        or status.get("status")
        or ("failed" if manifest.get("errors") else "")
    )
    return collection_dir.is_dir() and execution_status == "completed"


def append_event(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()


def float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def read_execution_matrix(program: dict[str, Any]) -> list[dict[str, str]]:
    matrix_path = resolve(str(program["execution_matrix"]))
    with matrix_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def completed_checkpoint_records(
    paths: list[Path],
    *,
    require_artifact: bool = False,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(set(item.resolve() for item in paths if item.exists())):
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            event = json.loads(raw_line)
            slot_id = str(event.get("execution_slot_id", ""))
            if (
                event.get("status") == "completed"
                and slot_id
                and (
                    not require_artifact
                    or checkpoint_artifact_completed(event)
                )
            ):
                records[slot_id] = event
    return records


def progress_confidence(sample_count: int) -> str:
    if sample_count >= 20:
        return "high"
    if sample_count >= 5:
        return "medium"
    return "low"


def seconds_per_work_unit(
    *,
    completed: dict[str, dict[str, Any]],
    rows_by_slot: dict[str, dict[str, str]],
) -> tuple[float | None, int]:
    samples: list[float] = []
    for slot_id, event in completed.items():
        elapsed = float_value(event.get("elapsed_seconds"), 0.0)
        row = rows_by_slot.get(slot_id) or {}
        weight = float_value(
            event.get("planned_work_units"),
            float_value(row.get("planned_work_units"), 1.0),
        )
        if elapsed > 0 and weight > 0:
            samples.append(elapsed / weight)
    if not samples:
        return None, 0
    return statistics.median(samples), len(samples)


def planned_work(rows: list[dict[str, str]]) -> float:
    return sum(
        max(0.1, float_value(row.get("planned_work_units"), 1.0))
        for row in rows
    )


def progress_snapshot(
    *,
    rows: list[dict[str, str]],
    completed: dict[str, dict[str, Any]],
    runnable_batch_ids: set[str],
) -> dict[str, Any]:
    rows_by_slot = {
        str(row.get("execution_slot_id", "")): row
        for row in rows
        if row.get("execution_slot_id")
    }
    completed_slots = set(completed) & set(rows_by_slot)
    completed_work = sum(
        max(
            0.1,
            float_value(
                rows_by_slot[slot_id].get("planned_work_units"),
                1.0,
            ),
        )
        for slot_id in completed_slots
    )
    runnable_rows = [
        row
        for row in rows
        if str(row.get("batch_id", "")) in runnable_batch_ids
    ]
    runnable_slots = {
        str(row.get("execution_slot_id", ""))
        for row in runnable_rows
    }
    runnable_completed = completed_slots & runnable_slots
    remaining_runnable_rows = [
        row
        for row in runnable_rows
        if str(row.get("execution_slot_id", ""))
        not in runnable_completed
    ]
    remaining_cost_class_counts: dict[str, int] = {}
    remaining_dataset_size_counts: dict[str, int] = {}
    for row in remaining_runnable_rows:
        cost_class = str(row.get("progress_cost_class", "unknown"))
        size_class = str(row.get("dataset_size_class", "unknown"))
        remaining_cost_class_counts[cost_class] = (
            remaining_cost_class_counts.get(cost_class, 0) + 1
        )
        remaining_dataset_size_counts[size_class] = (
            remaining_dataset_size_counts.get(size_class, 0) + 1
        )
    runnable_completed_work = sum(
        max(
            0.1,
            float_value(
                rows_by_slot[slot_id].get("planned_work_units"),
                1.0,
            ),
        )
        for slot_id in runnable_completed
    )
    rate, sample_count = seconds_per_work_unit(
        completed=completed,
        rows_by_slot=rows_by_slot,
    )
    runnable_work = planned_work(runnable_rows)
    remaining_runnable_work = max(
        0.0,
        runnable_work - runnable_completed_work,
    )
    return {
        "planned_slot_count": len(rows),
        "completed_slot_count": len(completed_slots),
        "planned_work_units": round(planned_work(rows), 3),
        "completed_work_units": round(completed_work, 3),
        "runnable_slot_count": len(runnable_rows),
        "runnable_completed_slot_count": len(runnable_completed),
        "runnable_work_units": round(runnable_work, 3),
        "runnable_completed_work_units": round(
            runnable_completed_work,
            3,
        ),
        "blocked_slot_count": len(rows) - len(runnable_rows),
        "remaining_cost_class_counts": dict(
            sorted(remaining_cost_class_counts.items())
        ),
        "remaining_dataset_size_counts": dict(
            sorted(remaining_dataset_size_counts.items())
        ),
        "seconds_per_work_unit": (
            None if rate is None else round(rate, 6)
        ),
        "eta_seconds": (
            None if rate is None else round(rate * remaining_runnable_work, 1)
        ),
        "eta_sample_count": sample_count,
        "eta_confidence": progress_confidence(sample_count),
        "updated_at_utc": timestamp(),
    }


def checkpoint_paths(
    *,
    runs_root: Path,
    batch_ids: set[str],
    current_state_dir: Path,
    include_current: bool,
) -> list[Path]:
    paths = [
        path
        for batch_id in sorted(batch_ids)
        for path in (runs_root / batch_id / "run" / "checkpoints").glob(
            "*.jsonl"
        )
    ]
    if include_current:
        paths.extend(current_state_dir.glob("checkpoints/*.jsonl"))
    return sorted(set(path.resolve() for path in paths))


def log_program_progress(snapshot: dict[str, Any]) -> None:
    runnable_slots = int(snapshot["runnable_slot_count"])
    runnable_completed = int(
        snapshot["runnable_completed_slot_count"]
    )
    runnable_work = float(snapshot["runnable_work_units"])
    completed_work = float(
        snapshot["runnable_completed_work_units"]
    )
    remaining_costs = snapshot.get("remaining_cost_class_counts") or {}
    remaining_sizes = (
        snapshot.get("remaining_dataset_size_counts") or {}
    )
    heavy_remaining = int(remaining_costs.get("heavy", 0)) + int(
        remaining_costs.get("extreme", 0)
    )
    large_remaining = int(remaining_sizes.get("large", 0))
    log(
        "GLOBAL",
        (
            f"runnable slots={runnable_completed}/{runnable_slots} "
            f"({progress_percent(runnable_completed, runnable_slots):.1f}%) "
            f"weighted={completed_work:.1f}/{runnable_work:.1f} "
            f"({progress_percent(completed_work, runnable_work):.1f}%) "
            f"ETA~{format_seconds(snapshot.get('eta_seconds'))} "
            f"confidence={snapshot['eta_confidence']} "
            f"samples={snapshot['eta_sample_count']} "
            f"heavy_remaining={heavy_remaining} "
            f"large_remaining={large_remaining} "
            f"blocked_future_slots={snapshot['blocked_slot_count']}"
        ),
    )


def completed_checkpoint_slots(
    path: Path,
    *,
    require_artifact: bool = False,
) -> set[str]:
    if not path.exists():
        return set()
    result: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        event = json.loads(raw_line)
        if (
            event.get("status") == "completed"
            and event.get("execution_slot_id")
            and (
                not require_artifact
                or checkpoint_artifact_completed(event)
            )
        ):
            result.add(str(event["execution_slot_id"]))
    return result


def selected_batch(program: dict[str, Any], batch_id: str) -> dict[str, Any]:
    candidates = [
        program.get("smoke_batch") or {},
        *(program.get("rendered_batches") or []),
        *(program.get("prepared_batches") or []),
    ]
    matches = [item for item in candidates if str(item.get("batch_id")) == batch_id]
    if not matches:
        raise ValueError(f"Unknown batch_id: {batch_id}")
    batch = matches[0]
    if batch.get("status") != "ready":
        raise RuntimeError(f"Batch {batch_id} status={batch.get('status')}; execution refused")
    return batch


def batch_segments(batch: dict[str, Any]) -> list[dict[str, Any]]:
    if batch.get("segments"):
        return list(batch["segments"])
    if batch.get("backend") == "standard_corpus":
        return [
            {
                "segment_id": f"{batch['batch_id']}__{group['group_id']}",
                "backend": "standard_corpus",
                "status": "ready",
                "plan": batch["rendered_plan"],
                "group_id": group["group_id"],
                "execution_count": group["instance_count"],
                "dataset_profile_id": group.get(
                    "dataset_profile_id",
                    "",
                ),
                "dataset_size_class": group.get(
                    "dataset_size_class",
                    "medium",
                ),
                "planned_work_units": float_value(
                    group.get("planned_work_units"),
                    float_value(group.get("instance_count"), 1.0),
                ),
            }
            for group in batch["groups"]
        ]
    raise RuntimeError(f"Batch {batch['batch_id']} has no executable segments")


def rows_for_segment(
    *,
    batch_rows: list[dict[str, str]],
    segment: dict[str, Any],
) -> list[dict[str, str]]:
    if str(segment["backend"]) == "standard_corpus":
        return [
            row
            for row in batch_rows
            if str(row.get("group_id", ""))
            == str(segment.get("group_id", ""))
        ]
    return [
        row
        for row in batch_rows
        if str(row.get("segment_id", ""))
        == str(segment["segment_id"])
    ]


def expected_segment_slots(
    *,
    batch_rows: list[dict[str, str]],
    segment: dict[str, Any],
) -> set[str]:
    return {
        str(row.get("execution_slot_id", ""))
        for row in rows_for_segment(
            batch_rows=batch_rows,
            segment=segment,
        )
        if row.get("execution_slot_id")
    }


def command_for(
    *,
    program_id: str,
    batch_id: str,
    segment: dict[str, Any],
    attempt: int,
    dry_run: bool,
    hardware_snapshot_dir: Path | None,
) -> list[str]:
    label = f"{batch_id}__{segment['segment_id']}__attempt-{attempt:02d}"
    if segment["backend"] == "standard_corpus":
        command = [
            sys.executable,
            str(INFRA_ROOT / "common-scripts/run_corpus_execution_plan.py"),
            "--plan",
            str(resolve(str(segment["plan"]))),
            "--label",
            label,
            "--logical-run-id",
            f"{program_id}__{batch_id}",
            "--rerun-of",
            f"{program_id}__{batch_id}",
        ]
        if segment.get("group_id"):
            command.extend(["--group-id", str(segment["group_id"])])
        if hardware_snapshot_dir is not None:
            command.extend(
                [
                    "--hardware-snapshot-dir",
                    str(hardware_snapshot_dir),
                ]
            )
        if dry_run:
            command.append("--dry-run")
        return command
    if segment["backend"] == "placement_aware_worker":
        if dry_run:
            return [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    f"assert Path({str(resolve(str(segment['config'])))!r}).exists(); "
                    f"assert Path({str(resolve(str(segment['plan'])))!r}).exists()"
                ),
            ]
        return [
            sys.executable,
            str(INFRA_ROOT / "common-scripts/run_confirmatory_skew_capability_smoke.py"),
            "--config",
            str(resolve(str(segment["config"]))),
            "--plan",
            str(resolve(str(segment["plan"]))),
            "--label",
            label,
            "--hard-timeout-seconds",
            "1800",
            "--timeout-grace-seconds",
            "30",
        ]
    raise RuntimeError(f"Unsupported backend: {segment['backend']}")


def run_streaming(command: list[str], *, env: dict[str, str] | None = None) -> str:
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    paths: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        stripped = line.strip()
        if stripped:
            rendered = (
                stripped
                if stripped.startswith("[")
                else f"[{clock()}] [CHILD] {stripped}"
            )
            print(rendered, flush=True)
            if stripped.startswith("/"):
                paths.append(stripped)
    returncode = process.wait()
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)
    return paths[-1] if paths else ""


def index_sources_for_artifact(
    *,
    artifact: str,
    backend: str,
    segment_id: str,
) -> list[dict[str, str]]:
    if not artifact:
        return []
    artifact_dir = Path(artifact).resolve()
    sources: list[dict[str, str]] = []
    if backend == "standard_corpus":
        for index_dir in sorted(artifact_dir.glob("database-sweeps/*/_index")):
            if not (index_dir / "execution_features.csv").exists():
                continue
            sources.append(
                {
                    "segment_id": segment_id,
                    "index_kind": "database_sweep",
                    "index_dir": str(index_dir),
                    "execution_file": "execution_features.csv",
                }
            )
    elif backend == "placement_aware_worker":
        manifest_path = artifact_dir / "capability_smoke_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for state, payload in sorted((manifest.get("query_sweeps") or {}).items()):
            index_dir = Path(str(payload["index_dir"])).resolve()
            if not (index_dir / "query_runs.csv").exists():
                raise FileNotFoundError(index_dir / "query_runs.csv")
            sources.append(
                {
                    "segment_id": segment_id,
                    "placement_state": str(state),
                    "index_kind": "placement_query_sweep",
                    "index_dir": str(index_dir),
                    "execution_file": "query_runs.csv",
                }
            )
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run exactly one append-only pressure raw collection batch."
    )
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()

    program_path = args.program.resolve()
    program = load_yaml(program_path)
    batch = selected_batch(program, args.batch_id)
    execution_matrix_path = resolve(str(program["execution_matrix"])).resolve()
    state_identity = {
        "program_id": str(program["program_id"]),
        "batch_id": args.batch_id,
        "program_path": str(program_path),
        "program_sha256": sha256_file(program_path),
        "execution_matrix_path": str(execution_matrix_path),
        "execution_matrix_sha256": sha256_file(execution_matrix_path),
    }
    state_dir = (
        args.state_dir.resolve()
        if args.state_dir
        else REPO_ROOT
        / "generated/pressure-raw-runs"
        / args.batch_id
        / ("dry-run" if args.dry_run else "run")
    )
    runs_root = REPO_ROOT / "generated/pressure-raw-runs"
    state_path = state_dir / "status.json"
    events_path = state_dir / "events.jsonl"
    progress_path = state_dir / "progress.json"
    program_progress_path = (
        state_dir / "program-progress.json"
        if args.dry_run
        else runs_root / "program-progress.json"
    )
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        mismatches = [
            key
            for key, expected in state_identity.items()
            if state.get(key) not in {None, "", expected}
        ]
        if mismatches:
            raise RuntimeError(
                "Resume refused because the persisted run identity changed: "
                + ", ".join(sorted(mismatches))
            )
        state.update(
            {
                key: state.get(key) or value
                for key, value in state_identity.items()
            }
        )
    else:
        state = {
            **state_identity,
            "status": "not_started",
            "created_at_utc": timestamp(),
            "segments": {},
        }
    if args.status_only:
        status_program_progress_path = (
            state_dir / "program-progress.json"
            if (state_dir / "program-progress.json").exists()
            else program_progress_path
        )
        status_payload = {
            **state,
            "live_batch_progress": (
                json.loads(progress_path.read_text(encoding="utf-8"))
                if progress_path.exists()
                else None
            ),
            "live_program_progress": (
                json.loads(
                    status_program_progress_path.read_text(
                        encoding="utf-8"
                    )
                )
                if status_program_progress_path.exists()
                else None
            ),
        }
        print(json.dumps(status_payload, indent=2, sort_keys=True))
        return 0

    segments = batch_segments(batch)
    matrix_rows = read_execution_matrix(program)
    batch_rows = [
        row
        for row in matrix_rows
        if str(row.get("batch_id", "")) == args.batch_id
    ]
    runnable_batch_ids = {
        str(item.get("batch_id", ""))
        for item in program.get("rendered_batches") or []
        if str(item.get("status", "")) == "ready"
    }
    contributes_to_program_progress = (
        not args.dry_run and args.batch_id in runnable_batch_ids
    )
    completed_records = completed_checkpoint_records(
        checkpoint_paths(
            runs_root=runs_root,
            batch_ids=runnable_batch_ids,
            current_state_dir=state_dir,
            include_current=contributes_to_program_progress,
        ),
        require_artifact=not args.dry_run,
    )
    initial_program_progress = progress_snapshot(
        rows=matrix_rows,
        completed=completed_records,
        runnable_batch_ids=runnable_batch_ids,
    )
    write_json(program_progress_path, initial_program_progress)
    log_program_progress(initial_program_progress)

    batch_total_work = planned_work(batch_rows)
    batch_completed_slots = {
        slot_id
        for slot_id in completed_records
        if any(
            row.get("execution_slot_id") == slot_id
            for row in batch_rows
        )
    }
    batch_rows_by_slot = {
        str(row.get("execution_slot_id", "")): row
        for row in batch_rows
    }
    batch_completed_work = sum(
        float_value(
            batch_rows_by_slot[slot_id].get("planned_work_units"),
            1.0,
        )
        for slot_id in batch_completed_slots
    )
    log(
        "BATCH",
        (
            f"id={args.batch_id} slots={len(batch_completed_slots)}/"
            f"{len(batch_rows)} "
            f"weighted={batch_completed_work:.1f}/{batch_total_work:.1f}"
        ),
    )
    for schedule_index, segment in enumerate(segments, start=1):
        size_class = str(segment.get("dataset_size_class", "medium"))
        work_units = float_value(
            segment.get("planned_work_units"),
            float_value(segment.get("execution_count"), 1.0),
        )
        marker = " HEAVY_AHEAD" if size_class == "large" else ""
        log(
            "SCHEDULE",
            (
                f"{schedule_index}/{len(segments)} "
                f"dataset={segment.get('dataset_profile_id', '')} "
                f"size={size_class} "
                f"slots={segment['execution_count']} "
                f"work_units={work_units:.1f}{marker}"
            ),
        )
    for segment in segments:
        segment_id = str(segment["segment_id"])
        checkpoint_file = state_dir / "checkpoints" / f"{segment_id}.jsonl"
        expected_slots = expected_segment_slots(
            batch_rows=batch_rows,
            segment=segment,
        )
        completed_slots = completed_checkpoint_slots(
            checkpoint_file,
            require_artifact=not args.dry_run,
        ) & expected_slots
        if expected_slots and completed_slots == expected_slots:
            state["segments"][segment_id] = {
                **state["segments"].get(segment_id, {}),
                "status": "completed",
                "execution_count": int(segment["execution_count"]),
                "completed_slot_count": len(completed_slots),
                "completion_source": "execution_slot_checkpoint",
            }
        elif (
            state["segments"].get(segment_id, {}).get("status")
            == "completed"
        ):
            state["segments"][segment_id] = {
                **state["segments"][segment_id],
                "status": "incomplete",
                "completed_slot_count": len(completed_slots),
                "completion_source": "execution_slot_checkpoint",
            }
    pending = [
        segment
        for segment in segments
        if state["segments"].get(segment["segment_id"], {}).get("status")
        != "completed"
    ]
    log(
        "BATCH",
        (
            f"id={args.batch_id} segments={len(segments)} pending={len(pending)} "
            f"executions={sum(int(item['execution_count']) for item in pending)} "
            f"dry_run={args.dry_run}"
        ),
    )
    state["status"] = "dry_run" if args.dry_run else "running"
    state["updated_at_utc"] = timestamp()
    write_json(state_path, state)
    try:
        hardware_snapshot_dir: Path | None = None
        if pending and not args.dry_run:
            saved_snapshot = Path(str(state.get("hardware_snapshot_dir", "")))
            saved_manifest = saved_snapshot / "hardware_snapshot_manifest.json"
            if saved_snapshot.is_absolute() and saved_manifest.is_file():
                hardware_snapshot_dir = saved_snapshot
                log(
                    "HW",
                    (
                        "reusing pressure-batch snapshot "
                        f"artifact={hardware_snapshot_dir}"
                    ),
                )
            else:
                hardware_started = time.monotonic()
                log("HW", "collecting once for all pending batch segments")
                artifact = run_streaming(
                    [
                        sys.executable,
                        str(
                            INFRA_ROOT
                            / "common-scripts"
                            / "collect_hardware_snapshot.py"
                        ),
                        "--label",
                        (
                            f"{program['program_id']}__"
                            f"{args.batch_id}-hardware"
                        ),
                        "--scope",
                        "pressure_batch_global",
                        "--out-root",
                        str(state_dir / "hardware-snapshots"),
                    ]
                )
                hardware_snapshot_dir = Path(artifact).resolve()
                manifest_path = (
                    hardware_snapshot_dir / "hardware_snapshot_manifest.json"
                )
                if not manifest_path.is_file():
                    raise FileNotFoundError(manifest_path)
                state["hardware_snapshot_dir"] = str(hardware_snapshot_dir)
                state["hardware_snapshot_collected_at_utc"] = timestamp()
                state["updated_at_utc"] = timestamp()
                write_json(state_path, state)
                log(
                    "HW",
                    (
                        "pressure-batch snapshot ready in "
                        f"{format_seconds(time.monotonic() - hardware_started)}"
                    ),
                )
        for index, segment in enumerate(pending, start=1):
            segment_id = str(segment["segment_id"])
            previous = state["segments"].get(segment_id, {})
            attempt = int(previous.get("attempt_count", 0)) + 1
            event_base = {
                "program_id": program["program_id"],
                "batch_id": args.batch_id,
                "segment_id": segment_id,
                "attempt_id": f"{segment_id}::attempt-{attempt:02d}",
                "attempt": attempt,
            }
            state["segments"][segment_id] = {
                **previous,
                "status": "running",
                "attempt_count": attempt,
                "started_at_utc": timestamp(),
                "execution_count": int(segment["execution_count"]),
            }
            append_event(events_path, {**event_base, "event": "started", "at_utc": timestamp()})
            write_json(state_path, state)
            log("SEGMENT", f"{index}/{len(pending)} start {segment_id} attempt={attempt}")
            completed_records = completed_checkpoint_records(
                checkpoint_paths(
                    runs_root=runs_root,
                    batch_ids=runnable_batch_ids,
                    current_state_dir=state_dir,
                    include_current=contributes_to_program_progress,
                ),
                require_artifact=not args.dry_run,
            )
            current_program_progress = progress_snapshot(
                rows=matrix_rows,
                completed=completed_records,
                runnable_batch_ids=runnable_batch_ids,
            )
            current_batch_completed = {
                slot_id
                for slot_id in completed_records
                if slot_id in batch_rows_by_slot
            }
            current_batch_completed_work = sum(
                float_value(
                    batch_rows_by_slot[slot_id].get(
                        "planned_work_units"
                    ),
                    1.0,
                )
                for slot_id in current_batch_completed
            )
            segment_rows = rows_for_segment(
                batch_rows=batch_rows,
                segment=segment,
            )
            segment_rows_by_slot = {
                str(row.get("execution_slot_id", "")): row
                for row in segment_rows
            }
            initial_segment_completed = {
                slot_id
                for slot_id in completed_records
                if slot_id in segment_rows_by_slot
            }
            initial_segment_completed_work = sum(
                float_value(
                    segment_rows_by_slot[slot_id].get(
                        "planned_work_units"
                    ),
                    1.0,
                )
                for slot_id in initial_segment_completed
            )
            next_heavy = next(
                (
                    item
                    for item in pending[index:]
                    if str(item.get("dataset_size_class", ""))
                    == "large"
                ),
                None,
            )
            next_heavy_dataset = (
                str(next_heavy.get("dataset_profile_id", "none"))
                if next_heavy
                else "none"
            )
            log(
                "SEGMENT",
                (
                    f"dataset={segment.get('dataset_profile_id', '')} "
                    f"size={segment.get('dataset_size_class', 'medium')} "
                    f"slots={segment['execution_count']} "
                    "work_units="
                    f"{float_value(segment.get('planned_work_units'), 0):.1f} "
                    f"next_heavy={next_heavy_dataset}"
                ),
            )
            try:
                segment_started = time.monotonic()
                artifact = run_streaming(
                    command_for(
                        program_id=str(program["program_id"]),
                        batch_id=args.batch_id,
                        segment=segment,
                        attempt=attempt,
                        dry_run=args.dry_run,
                        hardware_snapshot_dir=hardware_snapshot_dir,
                    ),
                    env={
                        **os.environ,
                        "PRESSURE_RAW_CHECKPOINT_FILE": str(
                            state_dir / "checkpoints" / f"{segment_id}.jsonl"
                        ),
                        "PRESSURE_PROGRAM_ID": str(program["program_id"]),
                        "PRESSURE_BATCH_ID": args.batch_id,
                        "PRESSURE_SEGMENT_ID": segment_id,
                        "PRESSURE_PROGRAM_ATTEMPT_ID": str(
                            event_base["attempt_id"]
                        ),
                        "PRESSURE_BATCH_SLOT_TOTAL": str(
                            len(batch_rows)
                        ),
                        "PRESSURE_BATCH_SLOT_OFFSET": str(
                            len(current_batch_completed)
                        ),
                        "PRESSURE_BATCH_WORK_TOTAL": str(
                            batch_total_work
                        ),
                        "PRESSURE_BATCH_WORK_OFFSET": str(
                            current_batch_completed_work
                        ),
                        "PRESSURE_SEGMENT_INITIAL_COMPLETED_SLOTS": str(
                            len(initial_segment_completed)
                        ),
                        "PRESSURE_SEGMENT_INITIAL_COMPLETED_WORK": str(
                            initial_segment_completed_work
                        ),
                        "PRESSURE_PROGRAM_SLOT_TOTAL": str(
                            current_program_progress[
                                "runnable_slot_count"
                            ]
                        ),
                        "PRESSURE_PROGRAM_SLOT_OFFSET": str(
                            current_program_progress[
                                "runnable_completed_slot_count"
                            ]
                        ),
                        "PRESSURE_PROGRAM_WORK_TOTAL": str(
                            current_program_progress[
                                "runnable_work_units"
                            ]
                        ),
                        "PRESSURE_PROGRAM_WORK_OFFSET": str(
                            current_program_progress[
                                "runnable_completed_work_units"
                            ]
                        ),
                        "PRESSURE_PROGRAM_BLOCKED_SLOTS": str(
                            current_program_progress[
                                "blocked_slot_count"
                            ]
                        ),
                        "PRESSURE_SECONDS_PER_WORK_UNIT": str(
                            current_program_progress.get(
                                "seconds_per_work_unit"
                            )
                            or ""
                        ),
                        "PRESSURE_ETA_SAMPLE_COUNT": str(
                            current_program_progress[
                                "eta_sample_count"
                            ]
                        ),
                        "PRESSURE_REMAINING_COST_CLASS_COUNTS": (
                            json.dumps(
                                current_program_progress[
                                    "remaining_cost_class_counts"
                                ],
                                sort_keys=True,
                            )
                        ),
                        "PRESSURE_REMAINING_DATASET_SIZE_COUNTS": (
                            json.dumps(
                                current_program_progress[
                                    "remaining_dataset_size_counts"
                                ],
                                sort_keys=True,
                            )
                        ),
                        "PRESSURE_PROGRESS_FILE": str(progress_path),
                        "PRESSURE_PROGRAM_PROGRESS_FILE": str(
                            program_progress_path
                        )
                        if contributes_to_program_progress
                        else "",
                    },
                )
            except BaseException as error:
                status = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
                state["segments"][segment_id].update(
                    {
                        "status": status,
                        "finished_at_utc": timestamp(),
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                )
                state["status"] = status
                state["updated_at_utc"] = timestamp()
                append_event(
                    events_path,
                    {
                        **event_base,
                        "event": status,
                        "at_utc": timestamp(),
                        "error": str(error),
                    },
                )
                write_json(state_path, state)
                raise
            expected_slots = {
                str(row.get("execution_slot_id", ""))
                for row in segment_rows
                if row.get("execution_slot_id")
            }
            valid_completed_slots = (
                completed_checkpoint_slots(
                    state_dir / "checkpoints" / f"{segment_id}.jsonl",
                    require_artifact=True,
                )
                & expected_slots
                if not args.dry_run
                else expected_slots
            )
            missing_slots = sorted(
                expected_slots - valid_completed_slots
            )
            segment_status = (
                "incomplete" if missing_slots else "completed"
            )
            state["segments"][segment_id].update(
                {
                    "status": segment_status,
                    "finished_at_utc": timestamp(),
                    "artifact": artifact,
                    "index_sources": index_sources_for_artifact(
                        artifact=artifact,
                        backend=str(segment["backend"]),
                        segment_id=segment_id,
                    )
                    if not args.dry_run
                    else [],
                    "error_type": "",
                    "error": "",
                    "completed_slot_count": len(valid_completed_slots),
                    "missing_slot_count": len(missing_slots),
                    "missing_execution_slot_ids": missing_slots,
                    "elapsed_seconds": round(
                        time.monotonic() - segment_started,
                        3,
                    ),
                }
            )
            append_event(
                events_path,
                {
                    **event_base,
                    "event": segment_status,
                    "at_utc": timestamp(),
                    "artifact": artifact,
                    "completed_slot_count": len(valid_completed_slots),
                    "missing_slot_count": len(missing_slots),
                },
            )
            state["updated_at_utc"] = timestamp()
            state["index_sources"] = [
                source
                for segment_state in state["segments"].values()
                for source in segment_state.get("index_sources", [])
            ]
            completed_records = completed_checkpoint_records(
                checkpoint_paths(
                    runs_root=runs_root,
                    batch_ids=runnable_batch_ids,
                    current_state_dir=state_dir,
                    include_current=contributes_to_program_progress,
                ),
                require_artifact=not args.dry_run,
            )
            final_program_progress = progress_snapshot(
                rows=matrix_rows,
                completed=completed_records,
                runnable_batch_ids=runnable_batch_ids,
            )
            state["progress"] = final_program_progress
            write_json(progress_path, final_program_progress)
            write_json(program_progress_path, final_program_progress)
            log_program_progress(final_program_progress)
            write_json(state_path, state)
            if missing_slots:
                state["status"] = "incomplete"
                state["updated_at_utc"] = timestamp()
                write_json(state_path, state)
                log(
                    "STOP",
                    (
                        f"segment={segment_id} incomplete "
                        f"completed={len(valid_completed_slots)}/"
                        f"{len(expected_slots)}; rerun the same command "
                        "to retry only missing slots"
                    ),
                )
                return 2
    except KeyboardInterrupt:
        log("STOP", "Ctrl+C recorded; rerun the same command to resume")
        return 130

    if not args.dry_run:
        log("CONSOLIDATE", "refresh program-level primary-only package")
        try:
            consolidation_out = run_streaming(
                [
                    sys.executable,
                    str(PROGRAM_CONSOLIDATOR),
                    "--program",
                    str(args.program.resolve()),
                    "--state-root",
                    str(runs_root),
                    "--allow-incomplete",
                ],
                env=dict(os.environ),
            )
        except BaseException as error:
            state["status"] = "consolidation_failed"
            state["updated_at_utc"] = timestamp()
            state["consolidation"] = {
                "gate": "NO_GO",
                "error_type": type(error).__name__,
                "error": str(error),
            }
            write_json(state_path, state)
            raise
        consolidation_manifest = load_yaml(
            Path(consolidation_out) / "consolidation_manifest.json"
        )
        state["consolidation"] = {
            "out_dir": consolidation_out,
            "gate": consolidation_manifest.get("gate", ""),
            "resolved_primary_slot_count": consolidation_manifest.get(
                "resolved_primary_slot_count",
                0,
            ),
            "expected_primary_slot_count": consolidation_manifest.get(
                "expected_primary_slot_count",
                0,
            ),
        }
    state["status"] = "dry_run_completed" if args.dry_run else "completed"
    state["updated_at_utc"] = timestamp()
    write_json(state_path, state)
    print(state_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
