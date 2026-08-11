from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
INFRA_ROOT = WORKSPACE_ROOT / "master-regimes-infra"
DEFAULT_PROGRAM = (
    REPO_ROOT
    / "generated/corpus/pressure-intervention-v1/pressure_intervention_program.yml"
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


def resolve_workspace(raw_path: str) -> Path:
    path = Path(raw_path)
    return path.resolve() if path.is_absolute() else (WORKSPACE_ROOT / path).resolve()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def assert_smoke_gate(program: dict[str, Any]) -> None:
    gate = program["smoke_gate"]
    report = REPO_ROOT / str(gate["report"])
    if not report.exists():
        raise FileNotFoundError(f"Smoke gate report not found: {report}")
    with report.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_axis = {str(row["pressure_axis"]): row for row in rows}
    errors: list[str] = []
    for axis in gate["required_axes"]:
        row = by_axis.get(str(axis))
        if row is None:
            errors.append(f"{axis}: missing")
            continue
        if row.get("status") != gate["required_status"]:
            errors.append(f"{axis}: status={row.get('status')}")
        if gate.get("require_training_eligible") and not truthy(
            row.get("training_eligible", "")
        ):
            errors.append(f"{axis}: training_eligible=false")
    if errors:
        raise RuntimeError("Smoke gate failed: " + ", ".join(errors))


def initial_state(program: dict[str, Any]) -> dict[str, Any]:
    return {
        "program_id": program["program_id"],
        "created_at_utc": timestamp(),
        "updated_at_utc": timestamp(),
        "status": "not_started",
        "segments": {},
    }


def load_state(path: Path, program: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return initial_state(program)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("program_id") != program["program_id"]:
        raise RuntimeError(
            f"State belongs to {value.get('program_id')}, not {program['program_id']}"
        )
    return value


def run_streaming(command: list[str], *, component: str) -> Path | None:
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        stripped = line.strip()
        if stripped:
            if stripped.startswith("["):
                print(stripped, flush=True)
            else:
                log(component, stripped)
    returncode = process.wait()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, command)
    for line in reversed(lines):
        candidate = line.strip()
        if candidate.startswith("/"):
            return Path(candidate)
    return None


def segment_command(
    *,
    program: dict[str, Any],
    segment: dict[str, Any],
    attempt: int,
) -> list[str]:
    segment_id = str(segment["segment_id"])
    backend = str(segment["backend"])
    if backend == "standard_corpus":
        return [
            sys.executable,
            str(INFRA_ROOT / "common-scripts/run_corpus_execution_plan.py"),
            "--plan",
            str(resolve_workspace(str(segment["plan"]))),
            "--group-id",
            str(segment["group_id"]),
            "--label",
            f"{segment_id}-attempt-{attempt:02d}",
            "--logical-run-id",
            f"{program['program_id']}-standard",
            "--rerun-of",
            f"{program['program_id']}-standard",
        ]
    if backend == "placement_aware_worker":
        return [
            sys.executable,
            str(
                INFRA_ROOT
                / "common-scripts/run_confirmatory_skew_capability_smoke.py"
            ),
            "--config",
            str(resolve_workspace(str(segment["config"]))),
            "--plan",
            str(resolve_workspace(str(segment["plan"]))),
            "--label",
            f"{segment_id}-attempt-{attempt:02d}",
            "--hard-timeout-seconds",
            "900",
            "--timeout-grace-seconds",
            "30",
        ]
    raise RuntimeError(
        f"Segment {segment_id} uses unsupported or blocked backend {backend}"
    )


def selected_segments(
    program: dict[str, Any],
    *,
    requested_ids: set[str],
    max_segments: int | None,
) -> list[dict[str, Any]]:
    segments = [
        segment
        for segment in program["segments"]
        if not requested_ids or str(segment["segment_id"]) in requested_ids
    ]
    found = {str(segment["segment_id"]) for segment in segments}
    missing = sorted(requested_ids - found)
    if missing:
        raise ValueError(f"Unknown segment IDs: {missing}")
    if max_segments is not None:
        segments = segments[:max_segments]
    return segments


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the generated pressure-intervention program one restart-safe "
            "segment at a time. Successful raw artifacts are never deleted."
        )
    )
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--segment-id", action="append", default=[])
    parser.add_argument("--max-segments", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()

    program_path = args.program.resolve()
    program = load_yaml(program_path)
    assert_smoke_gate(program)
    state_dir = (
        args.state_dir.resolve()
        if args.state_dir
        else REPO_ROOT
        / "generated/pressure-intervention-runs"
        / str(program["program_id"])
    )
    state_path = state_dir / "status.json"
    state = load_state(state_path, program)
    if args.status_only:
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0

    segments = selected_segments(
        program,
        requested_ids=set(args.segment_id),
        max_segments=args.max_segments,
    )
    completed = {
        segment_id
        for segment_id, result in state["segments"].items()
        if result.get("status") == "completed"
    }
    ready = [
        segment
        for segment in segments
        if segment.get("status") == "ready"
        and str(segment["segment_id"]) not in completed
    ]
    blocked = [
        segment
        for segment in segments
        if segment.get("status") != "ready"
    ]
    total_instances = sum(int(segment["execution_count"]) for segment in ready)
    log(
        "PROGRAM",
        (
            f"program={program['program_id']} selected={len(segments)} "
            f"remaining_ready={len(ready)} instances={total_instances} "
            f"already_completed={len(completed)} blocked={len(blocked)} "
            f"dry_run={args.dry_run}"
        ),
    )
    for segment in blocked:
        log(
            "BLOCKED",
            (
                f"{segment['segment_id']} status={segment['status']} "
                f"instances={segment['execution_count']}"
            ),
        )
    if args.dry_run:
        for index, segment in enumerate(ready, start=1):
            log(
                "DRY-RUN",
                (
                    f"{index}/{len(ready)} {segment['segment_id']} "
                    f"backend={segment['backend']} "
                    f"instances={segment['execution_count']}"
                ),
            )
        dry_run_path = state_dir / "dry_run_status.json"
        write_json(
            dry_run_path,
            {
                "program_id": program["program_id"],
                "created_at_utc": timestamp(),
                "selected_segment_count": len(segments),
                "ready_segment_count": len(ready),
                "ready_execution_count": total_instances,
                "blocked_segments": [
                    str(segment["segment_id"]) for segment in blocked
                ],
                "status": "dry_run",
            },
        )
        print(str(dry_run_path), flush=True)
        return 0

    state["status"] = "running"
    state["updated_at_utc"] = timestamp()
    write_json(state_path, state)
    try:
        completed_instances = 0
        for index, segment in enumerate(ready, start=1):
            segment_id = str(segment["segment_id"])
            previous = state["segments"].get(segment_id, {})
            attempt = int(previous.get("attempt_count", 0)) + 1
            state["segments"][segment_id] = {
                **previous,
                "status": "running",
                "attempt_count": attempt,
                "execution_count": int(segment["execution_count"]),
                "started_at_utc": timestamp(),
            }
            state["updated_at_utc"] = timestamp()
            write_json(state_path, state)
            log(
                "SEGMENT",
                (
                    f"{index}/{len(ready)} start id={segment_id} "
                    f"backend={segment['backend']} "
                    f"instances={segment['execution_count']} "
                    f"progress={completed_instances}/{total_instances}"
                ),
            )
            try:
                artifact = run_streaming(
                    segment_command(
                        program=program,
                        segment=segment,
                        attempt=attempt,
                    ),
                    component="CHILD",
                )
            except BaseException as exc:
                state["segments"][segment_id].update(
                    {
                        "status": (
                            "interrupted"
                            if isinstance(exc, KeyboardInterrupt)
                            else "failed"
                        ),
                        "finished_at_utc": timestamp(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                state["status"] = state["segments"][segment_id]["status"]
                state["updated_at_utc"] = timestamp()
                write_json(state_path, state)
                raise
            state["segments"][segment_id].update(
                {
                    "status": "completed",
                    "finished_at_utc": timestamp(),
                    "artifact": "" if artifact is None else str(artifact),
                    "error_type": "",
                    "error": "",
                }
            )
            completed_instances += int(segment["execution_count"])
            state["updated_at_utc"] = timestamp()
            write_json(state_path, state)
            log(
                "SEGMENT",
                (
                    f"{index}/{len(ready)} completed id={segment_id} "
                    f"progress={completed_instances}/{total_instances}"
                ),
            )
    except KeyboardInterrupt:
        log(
            "PROGRAM",
            "interrupted; rerun the same command to continue from the next incomplete segment",
        )
        return 130

    state["status"] = "completed_ready_segments"
    state["updated_at_utc"] = timestamp()
    write_json(state_path, state)
    print(str(state_path), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
