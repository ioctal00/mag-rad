#!/usr/bin/env python3
"""Execute the frozen feedback-loop replay without adaptive decisions."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INFRA_ROOT = ROOT.parent / "master-regimes-infra"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def pg_option_args(raw_options: str) -> list[str]:
    options = json.loads(raw_options or "{}")
    result: list[str] = []
    for key, value in sorted(options.items()):
        result.extend(("--pg-option", f"{key}={value}"))
    return result


def verify_effective_pg_options(artifact: Path, expected_raw: str) -> None:
    expected = json.loads(expected_raw or "{}")
    rows = read_csv(artifact / "_index/query_runs.csv")
    if len(rows) != 1:
        raise RuntimeError(f"expected one indexed replay execution in {artifact}")
    observed = json.loads(rows[0].get("pg_options_json") or "{}")
    mismatches = {
        key: {"expected": str(value), "observed": observed.get(key)}
        for key, value in expected.items()
        if str(observed.get(key, "")).lower() != str(value).lower()
    }
    if mismatches:
        raise RuntimeError(
            "frozen replay session options were not applied: "
            + json.dumps(mismatches, sort_keys=True)
        )


def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(completed.stdout, end="", flush=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {command[0]}")
    return completed


def network_command(
    *,
    infra_root: Path,
    run_root: Path,
    action: str,
    profile: dict[str, Any],
    label: str,
) -> None:
    run(
        [
            sys.executable,
            str(infra_root / "common-scripts/manage_network_pressure.py"),
            "--action",
            action,
            "--profile-json",
            json.dumps(profile, sort_keys=True),
            "--out-dir",
            str(run_root / "network_interventions/replay"),
            "--label",
            label,
        ],
        cwd=infra_root,
    )


def sweep_path(output: str) -> Path:
    candidates = [
        Path(line.strip()) for line in output.splitlines() if line.strip().startswith("/")
    ]
    if not candidates:
        raise RuntimeError("query sweep did not print its artifact path")
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--infra-root", type=Path, default=DEFAULT_INFRA_ROOT)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    infra_root = args.infra_root.resolve()
    plan_path = run_root / "frozen_replay_execution_plan.csv"
    replay = yaml.safe_load((run_root / "frozen_replay_manifest.yaml").read_text(encoding="utf-8"))
    states = replay["state_definitions"]
    plan = read_csv(plan_path)
    if not plan:
        raise RuntimeError("frozen replay execution plan is empty")

    total = len(plan)
    completed_before = sum(row["status"] == "completed" for row in plan)
    print(
        f"[REPLAY] frozen slots={total} completed_before={completed_before} "
        f"remaining={total - completed_before}",
        flush=True,
    )
    network_active = False
    active_profile: dict[str, Any] | None = None
    try:
        for row in plan:
            if row["status"] == "completed":
                continue
            order = int(row["execution_order"])
            state_id = row["replay_state_id"]
            definition = states[state_id]
            profile = definition.get("network_profile")
            attempt_id = int(row.get("attempt_id") or 1)
            label = f"replay-r{attempt_id}-{order:02d}-{state_id.lower()}"
            print(
                f"[REPLAY] slot={order}/{total} state={state_id} role={row['role']}",
                flush=True,
            )
            metadata: dict[str, Any] = {}
            if profile:
                network_command(
                    infra_root=infra_root,
                    run_root=run_root,
                    action="apply",
                    profile=profile,
                    label=f"{label}-apply",
                )
                network_active = True
                active_profile = profile
                network_command(
                    infra_root=infra_root,
                    run_root=run_root,
                    action="status",
                    profile=profile,
                    label=f"{label}-status-before",
                )
                metadata = {
                    "network_profile_id": profile["id"],
                    "network_profile_json": json.dumps(profile, sort_keys=True),
                    "configured_latency_ms": profile["configured_delay_ms"],
                    "configured_jitter_ms": profile["configured_jitter_ms"],
                    "configured_loss_percent": profile["configured_loss_percent"],
                    "configured_bandwidth_mbit": profile["configured_bandwidth_mbit"],
                }
            completed = run(
                [
                    sys.executable,
                    str(infra_root / "common-scripts/run_query_collection_sweep.py"),
                    "--instance-manifest",
                    row["instance_manifest"],
                    "--label",
                    label,
                    "--out-root",
                    str(run_root / "sweeps"),
                    "--target-group",
                    "analytics_clients",
                    "--target-host",
                    "eu-analytics-1",
                    "--checkpoint-file",
                    str(run_root / f"checkpoints/{label}.jsonl"),
                    "--hard-timeout-seconds",
                    "900",
                    "--timeout-grace-seconds",
                    "30",
                    "--global-stats-scope",
                    "none",
                    "--cache-policy",
                    "mixed_cache_first_observed",
                    "--order-policy",
                    "frozen_williams_order",
                    "--fdw-auto-explain",
                    "--fdw-auto-explain-region",
                    "eu",
                    "--fdw-auto-explain-region",
                    "us",
                    "--os-sampler",
                    "--os-sampler-node-group",
                    "eu",
                    "--os-sampler-node-group",
                    "us",
                    "--result-signature",
                    "--result-signature-scope",
                    "every_execution",
                    "--remote-edge-context",
                    "--execution-metadata-json",
                    json.dumps(metadata, sort_keys=True),
                    *pg_option_args(row.get("pg_options_json", "{}")),
                ],
                cwd=infra_root,
            )
            artifact = sweep_path(completed.stdout)
            if network_active and active_profile is not None:
                network_command(
                    infra_root=infra_root,
                    run_root=run_root,
                    action="reset",
                    profile=active_profile,
                    label=f"{label}-reset",
                )
                network_active = False
                network_command(
                    infra_root=infra_root,
                    run_root=run_root,
                    action="status",
                    profile=active_profile,
                    label=f"{label}-status-after",
                )
                active_profile = None
            run(
                [
                    "uv",
                    "run",
                    "master-regimes",
                    "index-query-sweep",
                    "--sweep-dir",
                    str(artifact),
                ],
                cwd=ROOT,
            )
            verify_effective_pg_options(artifact, row.get("pg_options_json", "{}"))
            row["status"] = "completed"
            row["sweep_dir"] = str(artifact)
            write_csv(plan_path, plan)
            finished = sum(item["status"] == "completed" for item in plan)
            print(f"[REPLAY] progress={finished}/{total}", flush=True)
    finally:
        if network_active and active_profile is not None:
            network_command(
                infra_root=infra_root,
                run_root=run_root,
                action="reset",
                profile=active_profile,
                label="emergency-finally-reset",
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
