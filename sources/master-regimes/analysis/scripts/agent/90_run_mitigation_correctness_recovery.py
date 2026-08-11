from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = ROOT.parent
INFRA_ROOT = WORKSPACE_ROOT / "master-regimes-infra"
DEFAULT_REPORT = ROOT / "analysis/reports/pressure-raw-v1-correctness-recovery"


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def completed_checkpoint_events(checkpoint_file: Path) -> dict[str, dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    if not checkpoint_file.is_file():
        return completed
    for line in checkpoint_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        recovery_id = str(event.get("execution_slot_id", ""))
        collection_dir = Path(str(event.get("collection_dir", "")))
        if (
            recovery_id
            and event.get("status") == "completed"
            and collection_dir.is_dir()
        ):
            completed[recovery_id] = event
    return completed


def snapshot_dir_for_collection(collection_dir: Path) -> Path:
    manifest_path = collection_dir / "execution_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("local_artifacts") or {}
    if not isinstance(artifacts, dict) or len(artifacts) != 1:
        raise ValueError(f"Expected one result-snapshot artifact in {manifest_path}")
    relative = next(iter(artifacts.values()))
    snapshot_dir = collection_dir / str(relative)
    if not (snapshot_dir / "results/result_snapshot.json").is_file():
        raise FileNotFoundError(snapshot_dir / "results/result_snapshot.json")
    return snapshot_dir.resolve()


def write_snapshot_locator(
    selection: pd.DataFrame,
    checkpoint_file: Path,
    out_path: Path,
) -> dict[str, Any]:
    events = completed_checkpoint_events(checkpoint_file)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for item in selection.itertuples(index=False):
        recovery_id = str(item.recovery_id)
        event = events.get(recovery_id)
        if event is None:
            continue
        collection_dir = Path(str(event["collection_dir"])).resolve()
        try:
            snapshot_dir = snapshot_dir_for_collection(collection_dir)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append({"recovery_id": recovery_id, "error": str(error)})
            continue
        rows.append(
            {
                "recovery_id": recovery_id,
                "pair_id": str(item.pair_id),
                "member": str(item.member),
                "backend": str(item.backend),
                "dataset_profile_id": str(item.dataset_profile_id),
                "collection_dir": str(collection_dir),
                "snapshot_dir": str(snapshot_dir),
                "completed_at_utc": str(event.get("completed_at_utc", "")),
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "recovery_id",
        "pair_id",
        "member",
        "backend",
        "dataset_profile_id",
        "collection_dir",
        "snapshot_dir",
        "completed_at_utc",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return {
        "expected_member_count": int(len(selection)),
        "located_member_count": len(rows),
        "missing_member_count": int(len(selection) - len(rows)),
        "invalid_snapshot_count": len(errors),
        "invalid_snapshots": errors,
        "locator": str(out_path),
    }


def run_command(command: list[str], env: dict[str, str], *, dry_run: bool) -> None:
    print("+ " + " ".join(command), flush=True)
    if dry_run:
        return
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the resumable 83-pair mitigation correctness recovery."
    )
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--backend",
        choices=("all", "standard", "placement"),
        default="all",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()

    report_dir = args.report_dir.resolve()
    selection_path = report_dir / "correctness_recovery_selection.csv"
    standard_plan_path = report_dir / "prepared/standard/corpus_execution_plan.yml"
    placement_plan_path = report_dir / "prepared/placement/placement_execution_plan.yml"
    checkpoint_file = report_dir / "execution/checkpoint.jsonl"
    locator_path = report_dir / "execution/snapshot_locator.csv"
    status_path = report_dir / "execution/recovery_status.json"
    selection = pd.read_csv(selection_path, low_memory=False)
    completed = completed_checkpoint_events(checkpoint_file)

    if not args.status_only:
        env = dict(os.environ)
        env["PRESSURE_RAW_CHECKPOINT_FILE"] = str(checkpoint_file)
        if args.backend in {"all", "standard"}:
            standard_ids = set(
                selection.loc[selection["backend"].eq("standard_corpus"), "recovery_id"].astype(str)
            )
            if not standard_ids.issubset(completed):
                run_command(
                    [
                        sys.executable,
                        str(INFRA_ROOT / "common-scripts/run_corpus_execution_plan.py"),
                        "--plan",
                        str(standard_plan_path),
                        "--label",
                        "mitigation-correctness-recovery-standard",
                        "--logical-run-id",
                        "mitigation-correctness-recovery-standard",
                        "--out-root",
                        str(INFRA_ROOT / "generated/runs/mitigation-correctness-recovery"),
                    ],
                    env,
                    dry_run=args.dry_run,
                )
                completed = completed_checkpoint_events(checkpoint_file)
            else:
                print("[RECOVERY] standard backend already complete", flush=True)

        if args.backend in {"all", "placement"}:
            placement_plan = load_yaml(placement_plan_path)
            for index, group in enumerate(placement_plan.get("groups") or [], start=1):
                dataset_id = str(group["dataset_profile_id"])
                dataset_ids = set(
                    selection.loc[
                        selection["backend"].eq("placement_aware_worker")
                        & selection["dataset_profile_id"].eq(dataset_id),
                        "recovery_id",
                    ].astype(str)
                )
                if dataset_ids.issubset(completed):
                    print(
                        f"[RECOVERY] placement {index}/{len(placement_plan['groups'])} "
                        f"dataset={dataset_id} already complete",
                        flush=True,
                    )
                    continue
                run_command(
                    [
                        sys.executable,
                        str(
                            INFRA_ROOT
                            / "common-scripts/run_confirmatory_skew_capability_smoke.py"
                        ),
                        "--config",
                        str(group["config"]),
                        "--plan",
                        str(group["plan"]),
                        "--label",
                        f"mitigation-correctness-recovery-{dataset_id}",
                        "--out-root",
                        str(
                            INFRA_ROOT
                            / "generated/runs/mitigation-correctness-recovery-placement"
                        ),
                        "--hard-timeout-seconds",
                        "1800",
                        "--timeout-grace-seconds",
                        "30",
                        "--result-snapshot-only",
                        "--result-snapshot-max-rows",
                        "100",
                        "--result-snapshot-max-bytes",
                        "10485760",
                    ],
                    env,
                    dry_run=args.dry_run,
                )
                completed = completed_checkpoint_events(checkpoint_file)

    locator_summary = write_snapshot_locator(selection, checkpoint_file, locator_path)
    status = {
        "contract_version": "mitigation-correctness-recovery-v1",
        "updated_at_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "backend_scope": args.backend,
        "dry_run": args.dry_run,
        **locator_summary,
        "status": (
            "COMPLETED"
            if locator_summary["missing_member_count"] == 0
            and locator_summary["invalid_snapshot_count"] == 0
            else "INCOMPLETE"
        ),
    }
    write_json_atomic(status_path, status)
    print(status_path)
    return 0 if args.status_only or args.dry_run or status["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
