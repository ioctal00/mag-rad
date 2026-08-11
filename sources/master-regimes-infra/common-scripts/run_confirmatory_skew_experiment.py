#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
MASTER_REGIMES_ROOT = WORKSPACE_ROOT / "master-regimes"
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"
CAPABILITY_CHECKPOINT = (
    MASTER_REGIMES_ROOT
    / "llmcontext"
    / "plans"
    / "checkpoints"
    / "confirmatory-skew-v1-capability-smoke.yml"
)


def capability_module() -> ModuleType:
    path = REPO_ROOT / "common-scripts" / "run_confirmatory_skew_capability_smoke.py"
    spec = importlib.util.spec_from_file_location("confirmatory_skew_capability", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load capability helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAP = capability_module()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Execute the preregistered 48-slot confirmatory-skew experiment. "
            "This runner never trains or refits a model."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=MASTER_REGIMES_ROOT
        / "configs"
        / "validation"
        / "confirmatory_skew_v1.yml",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=MASTER_REGIMES_ROOT
        / "generated"
        / "corpus"
        / "confirmatory-skew-v1"
        / "corpus_execution_plan.yml",
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT
        / "generated"
        / "runs"
        / "confirmatory-skew-experiments",
    )
    parser.add_argument("--label", default="confirmatory-skew-v1-attempt-01")
    parser.add_argument(
        "--load-method",
        choices=("sql", "csv", "copy_pipe"),
        default="copy_pipe",
    )
    parser.add_argument("--hard-timeout-seconds", type=int, default=300)
    parser.add_argument("--timeout-grace-seconds", type=int, default=30)
    parser.add_argument("--ssh-user", default="root")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_state(path: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return {"commit": commit, "dirty": bool(status.strip())}


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path.resolve())


def plan_group(plan: dict[str, Any], state_id: str) -> dict[str, Any]:
    matches = [
        group
        for group in plan["groups"]
        if str(group.get("state_id", "")) == state_id
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one group for state {state_id}, got {len(matches)}"
        )
    return matches[0]


def profile_for_group(group: dict[str, Any]) -> Path:
    sweep_path = WORKSPACE_ROOT / str(group["sweep_config"])
    sweep = CAP.load_yaml(sweep_path)
    datasets = sweep.get("datasets", [])
    if len(datasets) != 1:
        raise RuntimeError(f"Expected one dataset in {sweep_path}")
    return (WORKSPACE_ROOT / str(datasets[0]["profile"])).resolve()


def verify_frozen_contract(plan_path: Path) -> dict[str, Any]:
    contract_path = plan_path.parent / "frozen_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for name, artifact in contract["artifacts"].items():
        path = WORKSPACE_ROOT / str(artifact["path"])
        if sha256_file(path) != artifact["sha256"]:
            mismatches.append(name)
    if mismatches:
        raise RuntimeError(
            "Frozen model contract changed: " + ", ".join(sorted(mismatches))
        )
    return {
        "path": relative(contract_path),
        "sha256": sha256_file(contract_path),
        "model_id": contract["model_id"],
        "feature_count": contract["feature_count"],
        "artifact_hashes_verified": True,
    }


def reset_network(run_dir: Path) -> Path:
    profile = {
        "id": "confirmatory-skew-baseline",
        "enabled": True,
        "target_region_ids": ["eu", "us"],
        "configured_delay_ms": 0,
        "configured_jitter_ms": 0,
        "configured_loss_percent": 0,
        "scope": "analytics_to_region_coordinators",
    }
    return CAP.run_streaming_path(
        [
            sys.executable,
            str(REPO_ROOT / "common-scripts" / "manage_network_latency.py"),
            "--action",
            "reset",
            "--profile-json",
            json.dumps(profile, sort_keys=True),
            "--label",
            "confirmatory-skew-v1-preflight-reset",
            "--out-dir",
            str(run_dir / "network-interventions"),
        ],
        component="NET",
    )


def load_state_dataset(
    *,
    state_id: str,
    profile: Path,
    load_method: str,
) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for region in ("eu", "us"):
        CAP.log_event("DATASET", f"state={state_id} clean load region={region}")
        output = CAP.run_streaming_path(
            [
                sys.executable,
                str(REPO_ROOT / "common-scripts" / "apply_dataset_profile.py"),
                "--profile",
                str(profile),
                "--region",
                region,
                "--load-method",
                load_method,
            ],
            component=f"DATASET-{state_id}-{region.upper()}",
        )
        outputs[region] = str(output)
    return outputs


def bootstrap_fdw(*, run_id: str, state_id: str) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for region in ("eu", "us"):
        CAP.log_event("FDW", f"state={state_id} bootstrap region={region}")
        output = CAP.run_streaming_path(
            [
                sys.executable,
                str(REPO_ROOT / "common-scripts" / "run_gac_fdw_bootstrap.py"),
                "--label",
                f"{run_id}-{state_id.lower()}-fdw-{region}",
                "--region",
                region,
            ],
            component=f"FDW-{state_id}-{region.upper()}",
        )
        outputs[region] = str(output)
    return outputs


def audit_state(
    *,
    state_id: str,
    coordinators: dict[str, dict[str, Any]],
    hot_ids: dict[str, set[int]],
    ssh_user: str,
    key_file: Path | None,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, str]]],
]:
    summaries: dict[str, dict[str, Any]] = {}
    tenant_rows: dict[str, list[dict[str, Any]]] = {}
    placement_rows: dict[str, list[dict[str, str]]] = {}
    for region in ("eu", "us"):
        summary, rows, placements = CAP.audit_region(
            region=region,
            coordinator=coordinators[region],
            hot_tenant_ids=hot_ids[region],
            user=ssh_user,
            key_file=key_file,
        )
        summaries[region] = summary
        tenant_rows[region] = rows
        placement_rows[region] = placements
        CAP.log_event(
            "AUDIT",
            (
                f"state={state_id} region={region} "
                f"events={summary['table_counts']['events']} "
                f"hot_share={summary['hot_event_share']:.4f} "
                f"dominant_hot_worker_share="
                f"{summary['dominant_hot_worker_hot_event_share']:.4f}"
            ),
        )
    return summaries, tenant_rows, placement_rows


def run_state_queries(
    *,
    state_id: str,
    group: dict[str, Any],
    run_dir: Path,
    hard_timeout_seconds: int,
    timeout_grace_seconds: int,
) -> tuple[Path, Path]:
    manifest = WORKSPACE_ROOT / str(group["instance_manifest"])
    sweep_dir = CAP.run_streaming_path(
        [
            sys.executable,
            str(REPO_ROOT / "common-scripts" / "run_query_collection_sweep.py"),
            "--instance-manifest",
            str(manifest),
            "--label",
            f"confirmatory-skew-v1-state-{state_id.lower()}",
            "--max-instances",
            "12",
            "--global-stats-scope",
            "none",
            "--target-group",
            "analytics_clients",
            "--hard-timeout-seconds",
            str(hard_timeout_seconds),
            "--timeout-grace-seconds",
            str(timeout_grace_seconds),
            "--cache-policy",
            "mixed_cache_confirmatory_first_observed",
            "--order-policy",
            "manifest_order",
            "--fdw-auto-explain",
            "--out-root",
            str(run_dir / "query-sweeps"),
        ],
        component=f"QUERY-{state_id}",
    )
    index_dir = CAP.run_streaming_path(
        [
            "uv",
            "run",
            "--project",
            str(MASTER_REGIMES_ROOT),
            "master-regimes",
            "index-query-sweep",
            "--sweep-dir",
            str(sweep_dir),
        ],
        component=f"INDEX-{state_id}",
    )
    return sweep_dir, index_dir


def write_ground_truth(
    *,
    run_dir: Path,
    audits: dict[str, dict[str, dict[str, Any]]],
    config: dict[str, Any],
) -> None:
    rows: list[dict[str, Any]] = []
    for state_id in ("A", "B", "C", "restored_B", "D"):
        if state_id not in audits:
            continue
        for region in ("eu", "us"):
            item = audits[state_id][region]
            rows.append(
                {
                    "state_id": state_id,
                    "region_id": region,
                    "tenants": item["table_counts"]["tenants"],
                    "events": item["table_counts"]["events"],
                    "users": item["table_counts"]["users"],
                    "global_users": item["table_counts"]["global_users"],
                    "hot_event_share": item["hot_event_share"],
                    "dominant_hot_worker": item["dominant_hot_worker"],
                    "dominant_hot_worker_hot_event_share": item[
                        "dominant_hot_worker_hot_event_share"
                    ],
                    "tenant_distribution_sha256": item[
                        "tenant_distribution_sha256"
                    ],
                    "event_placement_sha256": item["event_placement_sha256"],
                    "event_shard_count": item["event_shard_count"],
                }
            )
    CAP.write_csv(
        run_dir / "state_ground_truth.csv",
        rows,
        fieldnames=list(rows[0]),
    )
    CAP.write_json(run_dir / "state_audits.json", audits)
    CAP.write_json(
        run_dir / "dataset_invariant_contract.json",
        {
            "b_c_fields": [
                "table_counts",
                "hot_tenant_ids",
                "hot_tenant_event_counts",
                "hot_event_share",
                "tenant_distribution_sha256",
            ],
            "b_dispersed_max": config["placement"]["dispersed"][
                "dominant_hot_event_share_max"
            ],
            "c_concentrated_min": config["placement"]["concentrated"][
                "dominant_hot_event_share_min"
            ],
        },
    )


def write_running_status(
    path: Path,
    *,
    run_id: str,
    completed_states: list[str],
) -> None:
    CAP.write_json(
        path,
        {
            "run_id": run_id,
            "status": "running",
            "completed_states": completed_states,
            "updated_at_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        },
    )


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    plan_path = args.plan.resolve()
    config = CAP.load_yaml(config_path)
    plan = CAP.load_yaml(plan_path)
    checkpoint = CAP.load_yaml(CAPABILITY_CHECKPOINT)
    if checkpoint.get("decision") != "GO" or int(checkpoint.get("next_plan", 0)) != 11:
        raise RuntimeError("Plan 10 checkpoint does not authorize Plan 11")
    if int(plan.get("execution_count", 0)) != 48:
        raise RuntimeError("Expected exactly 48 preregistered execution slots")
    if not bool(plan.get("placement_aware_runner_required")):
        raise RuntimeError("Expected placement-aware execution contract")

    frozen_contract = verify_frozen_contract(plan_path)
    inventory = json.loads(args.inventory.resolve().read_text(encoding="utf-8"))
    env = {**CAP.load_shell_env(args.env_file), **os.environ}
    key_text = env.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    key_file = Path(key_text).expanduser() if key_text else None
    if key_file is not None and not key_file.exists():
        raise FileNotFoundError(f"SSH key not found: {key_file}")

    run_id = f"{CAP.utc_timestamp()}-{args.label}"
    run_dir = (args.out_root / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    status_path = run_dir / "confirmatory_skew_execution_status.json"
    manifest_path = run_dir / "confirmatory_skew_execution_manifest.json"
    started = time.monotonic()
    write_running_status(status_path, run_id=run_id, completed_states=[])

    coordinators: dict[str, dict[str, Any]] = {}
    nodes_by_region: dict[str, list[dict[str, str]]] = {}
    for region in ("eu", "us"):
        _, coordinator = CAP.coordinator_inventory(inventory, region=region)
        coordinators[region] = coordinator
        nodes_by_region[region] = CAP.node_rows(
            coordinator=coordinator,
            user=args.ssh_user,
            key_file=key_file,
        )

    hot_ids = {
        "eu": {
            int(value)
            for value in config["hot_tenant_contract"]["eu_hot_tenant_ids"]
        },
        "us": {
            int(value)
            for value in config["hot_tenant_contract"]["us_hot_tenant_ids"]
        },
    }
    groups = {state: plan_group(plan, state) for state in ("A", "B", "C", "D")}
    profiles = {
        state: profile_for_group(groups[state]) for state in ("A", "B", "D")
    }
    audits: dict[str, dict[str, dict[str, Any]]] = {}
    query_sweeps: dict[str, dict[str, str]] = {}
    dataset_loads: dict[str, dict[str, str]] = {}
    fdw_bootstraps: dict[str, dict[str, str]] = {}
    b_setup_moves: list[dict[str, Any]] = []
    c_moves: list[dict[str, Any]] = []
    restore_moves: list[dict[str, Any]] = []
    c_restored = False
    completed_states: list[str] = []
    error: BaseException | None = None
    network_reset_dir: Path | None = None

    try:
        CAP.log_event("EXPERIMENT", f"run_id={run_id} slots=48 states=A,B,C,D")
        network_reset_dir = reset_network(run_dir)

        dataset_loads["A"] = load_state_dataset(
            state_id="A",
            profile=profiles["A"],
            load_method=args.load_method,
        )
        fdw_bootstraps["A"] = bootstrap_fdw(run_id=run_id, state_id="A")
        audits["A"], _, _ = audit_state(
            state_id="A",
            coordinators=coordinators,
            hot_ids=hot_ids,
            ssh_user=args.ssh_user,
            key_file=key_file,
        )
        sweep, index = run_state_queries(
            state_id="A",
            group=groups["A"],
            run_dir=run_dir,
            hard_timeout_seconds=args.hard_timeout_seconds,
            timeout_grace_seconds=args.timeout_grace_seconds,
        )
        query_sweeps["A"] = {"sweep_dir": str(sweep), "index_dir": str(index)}
        completed_states.append("A")
        write_running_status(
            status_path,
            run_id=run_id,
            completed_states=completed_states,
        )

        dataset_loads["B"] = load_state_dataset(
            state_id="B",
            profile=profiles["B"],
            load_method=args.load_method,
        )
        fdw_bootstraps["B"] = bootstrap_fdw(run_id=run_id, state_id="B")
        audits["initial_B"], initial_rows, initial_placements = audit_state(
            state_id="initial_B",
            coordinators=coordinators,
            hot_ids=hot_ids,
            ssh_user=args.ssh_user,
            key_file=key_file,
        )
        for region in ("eu", "us"):
            assignment = CAP.greedy_hot_shard_assignment(
                shard_mass=CAP.hot_shard_mass(initial_rows[region]),
                workers=[row["node_name"] for row in nodes_by_region[region]],
            )
            b_setup_moves.extend(
                CAP.apply_assignment(
                    region=region,
                    phase="establish_b",
                    assignment=assignment,
                    placements=initial_placements[region],
                    coordinator=coordinators[region],
                    nodes=nodes_by_region[region],
                    user=args.ssh_user,
                    key_file=key_file,
                )
            )
        audits["B"], b_rows, b_placements = audit_state(
            state_id="B",
            coordinators=coordinators,
            hot_ids=hot_ids,
            ssh_user=args.ssh_user,
            key_file=key_file,
        )
        b_max = float(
            config["placement"]["dispersed"]["dominant_hot_event_share_max"]
        )
        if any(
            audits["B"][region]["dominant_hot_worker_hot_event_share"] > b_max
            for region in ("eu", "us")
        ):
            raise RuntimeError("B dispersed placement threshold failed")
        sweep, index = run_state_queries(
            state_id="B",
            group=groups["B"],
            run_dir=run_dir,
            hard_timeout_seconds=args.hard_timeout_seconds,
            timeout_grace_seconds=args.timeout_grace_seconds,
        )
        query_sweeps["B"] = {"sweep_dir": str(sweep), "index_dir": str(index)}
        completed_states.append("B")
        write_running_status(
            status_path,
            run_id=run_id,
            completed_states=completed_states,
        )

        for region in ("eu", "us"):
            designated = sorted(
                row["node_name"] for row in nodes_by_region[region]
            )[0]
            assignment = {
                shard_id: designated
                for shard_id in sorted(CAP.hot_shard_mass(b_rows[region]))
            }
            c_moves.extend(
                CAP.apply_assignment(
                    region=region,
                    phase="concentrate_c",
                    assignment=assignment,
                    placements=b_placements[region],
                    coordinator=coordinators[region],
                    nodes=nodes_by_region[region],
                    user=args.ssh_user,
                    key_file=key_file,
                )
            )
        audits["C"], _, _ = audit_state(
            state_id="C",
            coordinators=coordinators,
            hot_ids=hot_ids,
            ssh_user=args.ssh_user,
            key_file=key_file,
        )
        equal, differences = CAP.invariants_equal(audits["B"], audits["C"])
        if not equal:
            raise RuntimeError("B/C invariants differ: " + ", ".join(differences))
        c_min = float(
            config["placement"]["concentrated"]["dominant_hot_event_share_min"]
        )
        if any(
            audits["C"][region]["dominant_hot_worker_hot_event_share"] < c_min
            for region in ("eu", "us")
        ):
            raise RuntimeError("C concentrated placement threshold failed")
        sweep, index = run_state_queries(
            state_id="C",
            group=groups["C"],
            run_dir=run_dir,
            hard_timeout_seconds=args.hard_timeout_seconds,
            timeout_grace_seconds=args.timeout_grace_seconds,
        )
        query_sweeps["C"] = {"sweep_dir": str(sweep), "index_dir": str(index)}
        completed_states.append("C")
        write_running_status(
            status_path,
            run_id=run_id,
            completed_states=completed_states,
        )

        restore_moves = CAP.inverse_moves(
            moves=c_moves,
            coordinators=coordinators,
            nodes_by_region=nodes_by_region,
            user=args.ssh_user,
            key_file=key_file,
        )
        audits["restored_B"], _, _ = audit_state(
            state_id="restored_B",
            coordinators=coordinators,
            hot_ids=hot_ids,
            ssh_user=args.ssh_user,
            key_file=key_file,
        )
        if any(
            audits["restored_B"][region]["event_placement_sha256"]
            != audits["B"][region]["event_placement_sha256"]
            for region in ("eu", "us")
        ):
            raise RuntimeError("Restored B placement hash mismatch")
        c_restored = True

        dataset_loads["D"] = load_state_dataset(
            state_id="D",
            profile=profiles["D"],
            load_method=args.load_method,
        )
        fdw_bootstraps["D"] = bootstrap_fdw(run_id=run_id, state_id="D")
        audits["D"], _, _ = audit_state(
            state_id="D",
            coordinators=coordinators,
            hot_ids=hot_ids,
            ssh_user=args.ssh_user,
            key_file=key_file,
        )
        sweep, index = run_state_queries(
            state_id="D",
            group=groups["D"],
            run_dir=run_dir,
            hard_timeout_seconds=args.hard_timeout_seconds,
            timeout_grace_seconds=args.timeout_grace_seconds,
        )
        query_sweeps["D"] = {"sweep_dir": str(sweep), "index_dir": str(index)}
        completed_states.append("D")
    except BaseException as exc:
        error = exc
    finally:
        if c_moves and not c_restored:
            try:
                restore_moves = CAP.inverse_moves(
                    moves=c_moves,
                    coordinators=coordinators,
                    nodes_by_region=nodes_by_region,
                    user=args.ssh_user,
                    key_file=key_file,
                )
                c_restored = True
            except BaseException as restore_exc:
                if error is None:
                    error = restore_exc
                else:
                    CAP.log_event("RESTORE", f"failed after error: {restore_exc}")

        if audits:
            write_ground_truth(run_dir=run_dir, audits=audits, config=config)
        CAP.write_yaml(
            run_dir / "placement_intervention_manifest.yml",
            {
                "experiment_id": config["analysis_id"],
                "b_setup_moves": b_setup_moves,
                "c_concentration_moves": c_moves,
                "restore_moves": restore_moves,
                "restore_status": (
                    "inverse_moves_completed" if c_restored else "not_completed"
                ),
            },
        )
        manifest = {
            "experiment_id": config["analysis_id"],
            "run_id": run_id,
            "status": "completed" if error is None else "failed",
            "error": "" if error is None else str(error),
            "state_order": ["A", "B", "C", "D"],
            "completed_states": completed_states,
            "expected_execution_count": 48,
            "database_result_rows_stored": False,
            "network_reset_dir": (
                "" if network_reset_dir is None else str(network_reset_dir)
            ),
            "dataset_loads": dataset_loads,
            "fdw_bootstraps": fdw_bootstraps,
            "query_sweeps": query_sweeps,
            "frozen_contract": frozen_contract,
            "repository_state": {
                "master-regimes": git_state(MASTER_REGIMES_ROOT),
                "master-regimes-infra": git_state(REPO_ROOT),
            },
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        CAP.write_json(manifest_path, manifest)
        CAP.write_json(
            status_path,
            {
                "run_id": run_id,
                "status": manifest["status"],
                "error": manifest["error"],
                "completed_states": completed_states,
                "updated_at_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
                "restore_status": (
                    "inverse_moves_completed" if c_restored else "not_completed"
                ),
            },
        )

    print(str(run_dir), flush=True)
    if error is not None:
        raise error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
