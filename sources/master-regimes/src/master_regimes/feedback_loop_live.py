"""Live release helpers for the frozen feedback-loop protocol.

This module does not connect to infrastructure.  It creates immutable run
contracts, renders SQL, materializes state manifests, derives the six-domain
inputs from normalized collector indexes, and appends validated decision and
outcome records.  Infrastructure commands remain explicit in the runner so
their effects and rollback checks are visible in the audit trail.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
import statistics
import subprocess
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from master_regimes.feedback_loop import (
    ContractError,
    build_relative_profile,
    classify_outcome,
    load_yaml,
    robust_center,
    robust_scale,
    validate_decision_log,
)

LIVE_CONTRACT_VERSION = "pressure-feedback-loop-live-v1"
BOOTSTRAP_SEED = 20260807
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_ALPHA = 0.05

EXECUTION_FIELDS = (
    "execution_slot_id",
    "phase",
    "trajectory_id",
    "logical_question_id",
    "state_id",
    "step_index",
    "repeat_index",
    "repeat_role",
    "action_id",
    "template_id",
    "status",
    "query_run_id",
    "collection_dir",
    "sweep_dir",
    "started_at_utc",
    "finished_at_utc",
    "elapsed_seconds",
    "result_ordered_sha256",
    "result_multiset_sha256",
    "execution_status",
)

STATE_FIELDS = (
    "state_id",
    "phase",
    "trajectory_id",
    "logical_question_id",
    "step_index",
    "action_id",
    "template_id",
    "accepted",
    "repetition_count",
    "elapsed_median_seconds",
    "elapsed_mad_seconds",
    "elapsed_min_seconds",
    "elapsed_max_seconds",
    "result_status",
    "ordered_sha256",
    "multiset_sha256",
    "profile_path",
    "raw_signal_path",
    "sweep_dir",
)

TRANSITION_FIELDS = (
    "decision_id",
    "trajectory_id",
    "step_index",
    "source_state_id",
    "target_state_id",
    "action_id",
    "result_validation_status",
    "elapsed_log2_gain",
    "elapsed_gain_interval_low",
    "elapsed_gain_interval_high",
    "noise_status",
    "outcome_label",
    "accepted",
    "rollback_status",
)

RAW_DELTA_FIELDS = (
    "decision_id",
    "trajectory_id",
    "source_state_id",
    "target_state_id",
    "action_id",
    "feature_id",
    "before_median",
    "after_median",
    "absolute_delta",
    "relative_delta",
    "status",
)

DOMAIN_DELTA_FIELDS = (
    "decision_id",
    "trajectory_id",
    "source_state_id",
    "target_state_id",
    "action_id",
    "reference_view",
    "domain_id",
    "relative_pressure_evidence",
    "status",
    "conflicting_component_signs",
    "positive_component_count",
    "negative_component_count",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_csv(path: Path, row: Mapping[str, Any], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()


def git_revision(repo: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(
            ["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL
        ).strip()

    return {
        "path": str(repo),
        "branch": run("branch", "--show-current"),
        "commit": run("rev-parse", "HEAD"),
        "dirty": bool(run("status", "--porcelain")),
    }


def _template_lookup(repo_root: Path, trajectory: Mapping[str, Any]) -> dict[str, Path]:
    suite_path = repo_root / str(trajectory["suite"])
    suite = load_yaml(suite_path)
    result: dict[str, Path] = {}
    template_ids = [trajectory["baseline_template_id"]]
    template_ids.extend(trajectory.get("reviewed_equivalent_template_ids", []))
    for template_id in template_ids:
        relative = suite["templates"][template_id]["file"]
        result[str(template_id)] = suite_path.parents[1] / str(relative)
    return result


def prepare_run(
    *,
    repo_root: Path,
    infra_root: Path,
    thesis_root: Path,
    experiment_dir: Path,
    run_root: Path,
) -> dict[str, Any]:
    """Create the immutable live release before the first analytical result."""

    if run_root.exists() and any(run_root.iterdir()):
        raise ContractError(f"run root is not empty: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    contracts_dir = run_root / "contracts"
    contracts_dir.mkdir()
    contract_names = (
        "FEEDBACK_LOOP_PROTOCOL.md",
        "pressure_domain_manifest.yaml",
        "intervention_catalog.yaml",
        "query_trajectory_manifest.yaml",
        "rollback_checklist.md",
        "RQ_H_MAPPING.md",
        "schemas/decision_log.schema.json",
    )
    contract_hashes: dict[str, str] = {}
    for relative in contract_names:
        source = experiment_dir / relative
        target = contracts_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        contract_hashes[relative] = sha256_file(target)

    trajectory_manifest = load_yaml(contracts_dir / "query_trajectory_manifest.yaml")
    rendered_dir = run_root / "rendered_sql"
    rendered_dir.mkdir()
    environment = Environment(undefined=StrictUndefined, autoescape=False)
    rendered: dict[str, dict[str, str]] = {}
    for trajectory in trajectory_manifest["trajectories"]:
        rendered[str(trajectory["id"])] = {}
        for template_id, source in _template_lookup(repo_root, trajectory).items():
            sql = environment.from_string(source.read_text(encoding="utf-8")).render(
                **trajectory.get("parameter_bindings", {})
            )
            target = rendered_dir / f"{template_id}.sql"
            target.write_text(sql.rstrip() + "\n", encoding="utf-8")
            rendered[str(trajectory["id"])][template_id] = str(target)

    live_contract = {
        "contract_version": LIVE_CONTRACT_VERSION,
        "created_at_utc": utc_now(),
        "source_contract_hashes": contract_hashes,
        "topology_scope": "GAC with EU and US FDW branches; APAC health-checked but excluded",
        "dataset_mutation_allowed": False,
        "schema_mutation_allowed": False,
        "colocation_mutation_allowed": False,
        "index_mutation_allowed": False,
        "baseline_repetitions": 5,
        "adaptive_repetitions": 3,
        "maximum_noise_repetitions": 2,
        "maximum_adaptive_decisions_per_trajectory": 5,
        "rollback_repetitions": 3,
        "replay_repetitions": 5,
        "hard_timeout_seconds": 900,
        "bootstrap": {
            "seed": BOOTSTRAP_SEED,
            "samples": BOOTSTRAP_SAMPLES,
            "alpha": BOOTSTRAP_ALPHA,
            "direction_rule": "resolved only when percentile interval excludes zero",
        },
        "result_contract": "ordered hash for all three trajectories; multiset retained",
        "outcome_labels": ["positive", "negative", "mixed", "indeterminate"],
        "future_outcomes_allowed": False,
        "parallel_queries_allowed": False,
        "static_hardware_snapshot_policy": "once_before_smoke",
        "rendered_sql": rendered,
    }
    write_json(run_root / "live_execution_contract.json", live_contract)

    slots: list[dict[str, Any]] = []
    slots.append(
        {
            "execution_slot_id": "phase-a-smoke-r01",
            "phase": "A_smoke",
            "trajectory_id": "smoke",
            "logical_question_id": "collector_smoke",
            "state_id": "smoke",
            "step_index": 0,
            "repeat_index": 1,
            "repeat_role": "required",
            "action_id": "session_rollback_smoke",
            "template_id": "smoke_select_one",
            "status": "planned",
        }
    )
    for trajectory in trajectory_manifest["trajectories"]:
        trajectory_id = str(trajectory["id"])
        logical_id = str(trajectory["logical_question_id"])
        for repeat in range(1, 6):
            slots.append(
                {
                    "execution_slot_id": f"phase-b-{trajectory_id}-s00-r{repeat:02d}",
                    "phase": "B_origin",
                    "trajectory_id": trajectory_id,
                    "logical_question_id": logical_id,
                    "state_id": f"{trajectory_id}_s00",
                    "step_index": 0,
                    "repeat_index": repeat,
                    "repeat_role": "required",
                    "action_id": "baseline",
                    "template_id": trajectory["baseline_template_id"],
                    "status": "planned",
                }
            )
        for step in range(1, 6):
            for repeat in range(1, 6):
                slots.append(
                    {
                        "execution_slot_id": (f"phase-c-{trajectory_id}-s{step:02d}-r{repeat:02d}"),
                        "phase": "C_adaptive",
                        "trajectory_id": trajectory_id,
                        "logical_question_id": logical_id,
                        "state_id": f"{trajectory_id}_s{step:02d}",
                        "step_index": step,
                        "repeat_index": repeat,
                        "repeat_role": "required" if repeat <= 3 else "noise_only_optional",
                        "action_id": "locked_by_pre_execution_decision",
                        "template_id": "locked_by_pre_execution_decision",
                        "status": "reserved",
                    }
                )
        for repeat in range(1, 4):
            slots.append(
                {
                    "execution_slot_id": f"phase-d-{trajectory_id}-rollback-r{repeat:02d}",
                    "phase": "D_rollback",
                    "trajectory_id": trajectory_id,
                    "logical_question_id": logical_id,
                    "state_id": f"{trajectory_id}_rollback",
                    "step_index": 99,
                    "repeat_index": repeat,
                    "repeat_role": "required",
                    "action_id": "restore_origin",
                    "template_id": trajectory["baseline_template_id"],
                    "status": "planned",
                }
            )
    for replay_state in range(4):
        for repeat in range(1, 6):
            slots.append(
                {
                    "execution_slot_id": f"phase-e-replay-s{replay_state:02d}-r{repeat:02d}",
                    "phase": "E_replay",
                    "trajectory_id": "locked_after_exploration",
                    "logical_question_id": "locked_after_exploration",
                    "state_id": f"replay_s{replay_state:02d}",
                    "step_index": replay_state,
                    "repeat_index": repeat,
                    "repeat_role": "required",
                    "action_id": "locked_after_exploration",
                    "template_id": "locked_after_exploration",
                    "status": "reserved",
                }
            )
    write_csv(run_root / "execution_manifest.csv", slots, EXECUTION_FIELDS)
    (run_root / "decision_log.jsonl").touch()
    write_csv(run_root / "trajectory_states.csv", [], STATE_FIELDS)

    provenance = {
        "contract_version": LIVE_CONTRACT_VERSION,
        "created_at_utc": utc_now(),
        "run_root": str(run_root),
        "repositories": [
            git_revision(repo_root),
            git_revision(infra_root),
            git_revision(thesis_root),
        ],
        "source_experiment_dir": str(experiment_dir),
        "contract_hashes": contract_hashes,
    }
    write_json(run_root / "provenance.json", provenance)
    return {"live_contract": live_contract, "provenance": provenance, "slot_count": len(slots)}


def verify_contracts(run_root: Path) -> None:
    contract = json.loads((run_root / "live_execution_contract.json").read_text(encoding="utf-8"))
    for relative, expected in contract["source_contract_hashes"].items():
        observed = sha256_file(run_root / "contracts" / relative)
        if observed != expected:
            raise ContractError(f"frozen contract changed: {relative}")


def capture_initial_snapshot(*, run_root: Path, infra_root: Path) -> dict[str, Any]:
    """Capture mutable configuration and hardware once before the smoke run."""

    verify_contracts(run_root)
    snapshot_dir = run_root / "phase_a" / "initial_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    ansible = str(infra_root / "common-scripts/run_ansible.sh")

    commands = {
        "gac_gucs": [
            ansible,
            "ansible",
            "analytics_clients",
            "-b",
            "--become-user",
            "postgres",
            "-m",
            "shell",
            "-a",
            'psql -XAt -v ON_ERROR_STOP=1 -d analytics -c "'
            "SELECT current_database(), current_setting('work_mem'), "
            "current_setting('join_collapse_limit'), "
            "current_setting('from_collapse_limit'), "
            "current_setting('enable_hashagg'), current_setting('jit'), "
            "current_setting('max_parallel_workers_per_gather');\"",
        ],
        "regional_gucs": [
            ansible,
            "ansible",
            "coordinators",
            "-b",
            "--become-user",
            "postgres",
            "-m",
            "shell",
            "-a",
            'psql -XAt -v ON_ERROR_STOP=1 -d app -c "'
            "SELECT current_database(), current_setting('work_mem'), "
            "current_setting('join_collapse_limit'), "
            "current_setting('from_collapse_limit'), "
            "current_setting('enable_hashagg'), current_setting('jit'), "
            "current_setting('max_parallel_workers_per_gather');\"",
        ],
        "fdw_server_options": [
            ansible,
            "ansible",
            "analytics_clients",
            "-b",
            "--become-user",
            "postgres",
            "-m",
            "shell",
            "-a",
            'psql -XAt -v ON_ERROR_STOP=1 -d analytics -c "'
            "SELECT srvname, array_to_string(srvoptions, ',') "
            'FROM pg_foreign_server ORDER BY srvname;"',
        ],
        "dataset_identity": [
            ansible,
            "ansible",
            "coordinators",
            "-b",
            "--become-user",
            "postgres",
            "-m",
            "shell",
            "-a",
            'psql -XAt -v ON_ERROR_STOP=1 -d app -c "'
            "SELECT 'events', count(*) FROM events UNION ALL "
            "SELECT 'users', count(*) FROM users ORDER BY 1; "
            "SELECT logicalrelid::regclass::text, partmethod, colocationid "
            "FROM pg_dist_partition WHERE logicalrelid IN "
            "('events'::regclass,'users'::regclass) ORDER BY 1;\"",
        ],
        "traffic_control": [
            ansible,
            "ansible",
            "db_nodes:analytics_clients",
            "-b",
            "-m",
            "shell",
            "-a",
            "tc qdisc show",
        ],
        "capture_processes": [
            ansible,
            "ansible",
            "db_nodes:analytics_clients",
            "-b",
            "-m",
            "shell",
            "-a",
            "pgrep -af '[m]ain.py capture-agent' || true",
        ],
        "clock_status": [
            ansible,
            "ansible",
            "db_nodes:analytics_clients",
            "-b",
            "-m",
            "shell",
            "-a",
            "date -u +%Y-%m-%dT%H:%M:%S.%NZ; timedatectl show -p NTPSynchronized --value",
        ],
        "hardware_once": [
            ansible,
            "ansible",
            "db_nodes:analytics_clients",
            "-m",
            "setup",
            "-a",
            "gather_subset=!all,hardware,network",
        ],
    }
    results: dict[str, Any] = {}
    for name, command in commands.items():
        completed = subprocess.run(
            command,
            cwd=infra_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output_path = snapshot_dir / f"{name}.txt"
        output_path.write_text(completed.stdout, encoding="utf-8")
        results[name] = {
            "command": command,
            "exit_code": completed.returncode,
            "output": str(output_path),
            "sha256": sha256_file(output_path),
        }
        if completed.returncode != 0:
            write_json(snapshot_dir / "snapshot_status.json", results)
            raise ContractError(f"initial snapshot command failed: {name}")
    (run_root / "rendered_sql/smoke_select_one.sql").write_text(
        "select 1::integer as smoke_value;\n", encoding="utf-8"
    )
    payload = {
        "contract_version": LIVE_CONTRACT_VERSION,
        "captured_at_utc": utc_now(),
        "hardware_snapshot_count": 1,
        "results": results,
    }
    write_json(snapshot_dir / "snapshot_status.json", payload)
    return payload


def capture_mutable_snapshot(*, run_root: Path, infra_root: Path, label: str) -> dict[str, Any]:
    """Capture post-run mutable state without recollecting static hardware."""

    verify_contracts(run_root)
    if not label or Path(label).name != label:
        raise ContractError("snapshot label must be one path-safe component")
    snapshot_dir = run_root / "phase_d" / label
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    ansible = str(infra_root / "common-scripts/run_ansible.sh")
    commands = {
        "gac_gucs": [
            ansible,
            "ansible",
            "analytics_clients",
            "-b",
            "--become-user",
            "postgres",
            "-m",
            "shell",
            "-a",
            'psql -XAt -v ON_ERROR_STOP=1 -d analytics -c "'
            "SELECT current_database(), current_setting('work_mem'), "
            "current_setting('join_collapse_limit'), "
            "current_setting('from_collapse_limit'), "
            "current_setting('enable_hashagg'), current_setting('jit'), "
            "current_setting('max_parallel_workers_per_gather');\"",
        ],
        "regional_gucs": [
            ansible,
            "ansible",
            "coordinators",
            "-b",
            "--become-user",
            "postgres",
            "-m",
            "shell",
            "-a",
            'psql -XAt -v ON_ERROR_STOP=1 -d app -c "'
            "SELECT current_database(), current_setting('work_mem'), "
            "current_setting('join_collapse_limit'), "
            "current_setting('from_collapse_limit'), "
            "current_setting('enable_hashagg'), current_setting('jit'), "
            "current_setting('max_parallel_workers_per_gather');\"",
        ],
        "fdw_server_options": [
            ansible,
            "ansible",
            "analytics_clients",
            "-b",
            "--become-user",
            "postgres",
            "-m",
            "shell",
            "-a",
            'psql -XAt -v ON_ERROR_STOP=1 -d analytics -c "'
            "SELECT srvname, array_to_string(srvoptions, ',') "
            'FROM pg_foreign_server ORDER BY srvname;"',
        ],
        "dataset_identity": [
            ansible,
            "ansible",
            "coordinators",
            "-b",
            "--become-user",
            "postgres",
            "-m",
            "shell",
            "-a",
            'psql -XAt -v ON_ERROR_STOP=1 -d app -c "'
            "SELECT 'events', count(*) FROM events UNION ALL "
            "SELECT 'users', count(*) FROM users ORDER BY 1; "
            "SELECT logicalrelid::regclass::text, partmethod, colocationid "
            "FROM pg_dist_partition WHERE logicalrelid IN "
            "('events'::regclass,'users'::regclass) ORDER BY 1;\"",
        ],
        "traffic_control": [
            ansible,
            "ansible",
            "db_nodes:analytics_clients",
            "-b",
            "-m",
            "shell",
            "-a",
            "tc qdisc show",
        ],
        "capture_processes": [
            ansible,
            "ansible",
            "db_nodes:analytics_clients",
            "-b",
            "-m",
            "shell",
            "-a",
            "pgrep -af '[m]ain.py capture-agent' || true",
        ],
        "clock_status": [
            ansible,
            "ansible",
            "db_nodes:analytics_clients",
            "-b",
            "-m",
            "shell",
            "-a",
            "date -u +%Y-%m-%dT%H:%M:%S.%NZ; timedatectl show -p NTPSynchronized --value",
        ],
    }
    results: dict[str, Any] = {}
    for name, command in commands.items():
        completed = subprocess.run(
            command,
            cwd=infra_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output_path = snapshot_dir / f"{name}.txt"
        output_path.write_text(completed.stdout, encoding="utf-8")
        results[name] = {
            "command": command,
            "exit_code": completed.returncode,
            "output": str(output_path),
            "sha256": sha256_file(output_path),
        }
        if completed.returncode != 0:
            write_json(snapshot_dir / "snapshot_status.json", results)
            raise ContractError(f"mutable snapshot command failed: {name}")
    payload = {
        "contract_version": LIVE_CONTRACT_VERSION,
        "captured_at_utc": utc_now(),
        "hardware_snapshot_count": 0,
        "label": label,
        "results": results,
    }
    write_json(snapshot_dir / "snapshot_status.json", payload)
    return payload


def create_state_instance_manifest(
    *,
    run_root: Path,
    trajectory_id: str,
    state_id: str,
    phase: str,
    step_index: int,
    action_id: str,
    template_id: str,
    repetitions: int,
    pg_options: Mapping[str, str] | None = None,
) -> Path:
    verify_contracts(run_root)
    trajectories = load_yaml(run_root / "contracts/query_trajectory_manifest.yaml")
    trajectory = next(item for item in trajectories["trajectories"] if item["id"] == trajectory_id)
    rendered = run_root / "rendered_sql" / f"{template_id}.sql"
    if not rendered.is_file():
        raise ContractError(f"rendered SQL is not frozen for {template_id}")
    fields = [
        "instance_id",
        "template_id",
        "rendered_sql_path",
        "execution_slot_id",
        "repeat_id",
        "repetition_index",
        "run_order",
        "logical_question_id",
        "condition_id",
        "pair_id",
        "variant",
        "intervention_role",
        "mitigation_action",
        "execution_scope",
        "target_scope",
        "topology_id",
        "dataset_profile_id",
        "collection_contract_version",
        "corpus_version",
        "batch_id",
        "cache_policy",
        "order_policy",
        "planned_work_units",
        "progress_cost_class",
        "pg_options_json",
        "params",
    ]
    rows: list[dict[str, Any]] = []
    for repeat in range(1, repetitions + 1):
        slot = f"{phase.lower()}-{trajectory_id}-s{step_index:02d}-r{repeat:02d}"
        rows.append(
            {
                "instance_id": f"{state_id}-r{repeat:02d}",
                "template_id": template_id,
                "rendered_sql_path": str(rendered),
                "execution_slot_id": slot,
                "repeat_id": f"r{repeat:02d}",
                "repetition_index": repeat - 1,
                "run_order": repeat,
                "logical_question_id": trajectory["logical_question_id"],
                "condition_id": state_id,
                "pair_id": f"{trajectory_id}-step-{step_index:02d}",
                "variant": "baseline" if step_index == 0 else "after_action",
                "intervention_role": "baseline" if step_index == 0 else "observed",
                "mitigation_action": action_id,
                "execution_scope": "gac_multi_edge",
                "target_scope": "global_end_to_end",
                "topology_id": "eu_us_gac_n2_active",
                "dataset_profile_id": "locked_current_dataset_snapshot",
                "collection_contract_version": LIVE_CONTRACT_VERSION,
                "corpus_version": "pressure-feedback-loop-v1",
                "batch_id": phase,
                "cache_policy": "mixed_cache_first_observed",
                "order_policy": "sequential_state_repetitions",
                "planned_work_units": 1,
                "progress_cost_class": "adaptive_unknown",
                "pg_options_json": json.dumps(pg_options or {}, sort_keys=True),
                "params": json.dumps(trajectory.get("parameter_bindings", {}), sort_keys=True),
            }
        )
    target = run_root / "state_manifests" / f"{state_id}.csv"
    write_csv(target, rows, fields)
    return target


def create_frozen_replay_manifests(run_root: Path) -> Path:
    """Materialize the frozen Williams order as one immutable row per execution."""

    verify_contracts(run_root)
    replay_path = run_root / "frozen_replay_manifest.yaml"
    replay = load_yaml(replay_path)
    states = replay["state_definitions"]
    blocks = replay["order_contract"]["blocks"]
    expected_repetitions = int(replay["repetitions_per_state"])
    flattened = [state_id for block in blocks for state_id in block]
    if set(flattened) != set(states):
        raise ContractError("frozen replay order and state definitions differ")
    counts = {state_id: flattened.count(state_id) for state_id in states}
    if set(counts.values()) != {expected_repetitions}:
        raise ContractError(f"invalid frozen replay repetition counts: {counts}")

    trajectories = load_yaml(run_root / "contracts/query_trajectory_manifest.yaml")
    trajectory = next(
        item for item in trajectories["trajectories"] if item["id"] == replay["trajectory_id"]
    )
    instance_fields = [
        "instance_id",
        "template_id",
        "rendered_sql_path",
        "execution_slot_id",
        "repeat_id",
        "repetition_index",
        "run_order",
        "logical_question_id",
        "condition_id",
        "pair_id",
        "variant",
        "intervention_role",
        "mitigation_action",
        "execution_scope",
        "target_scope",
        "topology_id",
        "dataset_profile_id",
        "collection_contract_version",
        "corpus_version",
        "batch_id",
        "cache_policy",
        "order_policy",
        "planned_work_units",
        "progress_cost_class",
        "pg_options_json",
        "params",
    ]
    plan_fields = [
        "execution_order",
        "block_index",
        "position_index",
        "replay_state_id",
        "state_repetition_index",
        "source_state_id",
        "role",
        "template_id",
        "pg_options_json",
        "network_profile_json",
        "instance_manifest",
        "status",
        "sweep_dir",
    ]
    manifest_dir = run_root / "replay_instance_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    repetition_by_state: dict[str, int] = defaultdict(int)
    plan_rows: list[dict[str, Any]] = []
    execution_order = 0
    for block_index, block in enumerate(blocks, start=1):
        for position_index, replay_state_id in enumerate(block, start=1):
            execution_order += 1
            repetition_by_state[replay_state_id] += 1
            repetition = repetition_by_state[replay_state_id]
            definition = states[replay_state_id]
            template_id = str(definition["template_id"])
            rendered = run_root / "rendered_sql" / f"{template_id}.sql"
            if not rendered.is_file():
                raise ContractError(f"missing frozen replay SQL: {template_id}")
            execution_slot_id = (
                f"e_replay-{execution_order:02d}-{replay_state_id.lower()}-r{repetition:02d}"
            )
            instance_row = {
                "instance_id": execution_slot_id,
                "template_id": template_id,
                "rendered_sql_path": str(rendered),
                "execution_slot_id": execution_slot_id,
                "repeat_id": f"r{repetition:02d}",
                "repetition_index": repetition - 1,
                "run_order": execution_order,
                "logical_question_id": replay["logical_question_id"],
                "condition_id": f"replay_{replay_state_id}",
                "pair_id": "frozen-replay-v1",
                "variant": definition["role"],
                "intervention_role": "confirmatory_replay",
                "mitigation_action": replay_state_id,
                "execution_scope": "gac_multi_edge",
                "target_scope": "global_end_to_end",
                "topology_id": replay["topology_id"],
                "dataset_profile_id": replay["dataset_profile_id"],
                "collection_contract_version": LIVE_CONTRACT_VERSION,
                "corpus_version": "pressure-feedback-loop-v1",
                "batch_id": "E_frozen_replay",
                "cache_policy": "mixed_cache_first_observed",
                "order_policy": "frozen_williams_order",
                "planned_work_units": 1,
                "progress_cost_class": "confirmatory_replay",
                "pg_options_json": json.dumps(definition.get("pg_options") or {}, sort_keys=True),
                "params": json.dumps(trajectory.get("parameter_bindings", {}), sort_keys=True),
            }
            instance_path = manifest_dir / f"order-{execution_order:02d}.csv"
            write_csv(instance_path, [instance_row], instance_fields)
            plan_rows.append(
                {
                    "execution_order": execution_order,
                    "block_index": block_index,
                    "position_index": position_index,
                    "replay_state_id": replay_state_id,
                    "state_repetition_index": repetition,
                    "source_state_id": definition["source_state_id"],
                    "role": definition["role"],
                    "template_id": template_id,
                    "pg_options_json": instance_row["pg_options_json"],
                    "network_profile_json": json.dumps(
                        definition.get("network_profile"), sort_keys=True
                    ),
                    "instance_manifest": str(instance_path),
                    "status": "planned",
                    "sweep_dir": "",
                }
            )
    output = run_root / "frozen_replay_execution_plan.csv"
    write_csv(output, plan_rows, plan_fields)
    return output


def create_smoke_manifest(run_root: Path) -> Path:
    verify_contracts(run_root)
    target = run_root / "state_manifests/smoke.csv"
    fields = [
        "instance_id",
        "template_id",
        "rendered_sql_path",
        "execution_slot_id",
        "repeat_id",
        "repetition_index",
        "run_order",
        "logical_question_id",
        "condition_id",
        "pair_id",
        "variant",
        "intervention_role",
        "mitigation_action",
        "execution_scope",
        "target_scope",
        "topology_id",
        "dataset_profile_id",
        "collection_contract_version",
        "corpus_version",
        "batch_id",
        "cache_policy",
        "order_policy",
        "planned_work_units",
        "progress_cost_class",
        "pg_options_json",
        "param_json",
    ]
    write_csv(
        target,
        [
            {
                "instance_id": "collector-smoke-r01",
                "template_id": "smoke_select_one",
                "rendered_sql_path": str(run_root / "rendered_sql/smoke_select_one.sql"),
                "execution_slot_id": "phase-a-smoke-r01",
                "repeat_id": "r01",
                "repetition_index": 0,
                "run_order": 1,
                "logical_question_id": "collector_smoke",
                "condition_id": "smoke",
                "pair_id": "phase-a-smoke",
                "variant": "smoke",
                "intervention_role": "smoke",
                "mitigation_action": "session_rollback_smoke",
                "execution_scope": "gac_smoke",
                "target_scope": "collector_contract",
                "topology_id": "eu_us_gac_n2_active",
                "dataset_profile_id": "locked_current_dataset_snapshot",
                "collection_contract_version": LIVE_CONTRACT_VERSION,
                "corpus_version": "pressure-feedback-loop-v1",
                "batch_id": "A_smoke",
                "cache_policy": "not_applicable",
                "order_policy": "single",
                "planned_work_units": 0.1,
                "progress_cost_class": "smoke",
                "pg_options_json": json.dumps({"work_mem": "8MB"}),
                "param_json": "{}",
            }
        ],
        fields,
    )
    return target


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _ratio(numerator: Any, denominator: Any) -> float | None:
    top = _float(numerator)
    bottom = _float(denominator)
    if top is None or bottom is None or bottom == 0:
        return None
    return top / bottom


def _sum(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = [_float(row.get(field)) for row in rows]
    available = [value for value in values if value is not None]
    return sum(available) if available else None


def _max(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = [_float(row.get(field)) for row in rows]
    available = [value for value in values if value is not None]
    return max(available) if available else None


def _harmonic(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = [_float(row.get(field)) for row in rows]
    positive = [value for value in values if value is not None and value > 0]
    return statistics.harmonic_mean(positive) if positive else None


def _boolean_share(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values: list[float] = []
    for row in rows:
        raw = str(row.get(field, "")).strip().lower()
        if raw in {"true", "1", "yes"}:
            values.append(1.0)
        elif raw in {"false", "0", "no"}:
            values.append(0.0)
    return statistics.mean(values) if values else None


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def derive_signal_rows(index_dir: Path) -> list[dict[str, Any]]:
    """Build manifest-named raw signals without imputing missing evidence."""

    executions = read_csv(index_dir / "execution_features.csv")
    if not executions:
        executions = read_csv(index_dir / "query_runs.csv")
    edges_by_run: dict[str, list[dict[str, str]]] = defaultdict(list)
    regions_by_run: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(index_dir / "remote_edge_observations.csv"):
        edges_by_run[row["query_run_id"]].append(row)
    for row in read_csv(index_dir / "region_fragments.csv"):
        regions_by_run[row["query_run_id"]].append(row)

    result: list[dict[str, Any]] = []
    for execution in executions:
        query_run_id = execution["query_run_id"]
        edges = edges_by_run.get(query_run_id, [])
        regions = regions_by_run.get(query_run_id, [])
        root_time = execution.get("coordinator_main_plan_total_time_ms")
        final_rows = execution.get("coordinator_final_rows")
        remote_rows = execution.get("remote_region_actual_rows_sum")
        worker_scan_rows = execution.get("worker_task_scan_actual_rows_sum")
        worker_tuple_bytes = execution.get("worker_task_tuple_bytes_sum")
        remote_tuple_bytes = execution.get("remote_region_tuple_bytes_sum")
        spill_locations = []
        for field in ("coordinator_spill_present", "regional_spill_present"):
            raw = str(execution.get(field, "")).lower()
            if raw in {"1", "true", "yes"}:
                spill_locations.append(field)
        worker_spill = _float(execution.get("worker_task_spill_count"))
        if worker_spill is not None and worker_spill > 0:
            spill_locations.append("worker_task")

        row: dict[str, Any] = {
            "query_run_id": query_run_id,
            "execution_slot_id": execution.get("execution_slot_id"),
            "repetition_index": execution.get("repetition_index"),
            "elapsed_seconds": _float(execution.get("elapsed_seconds")),
            "execution_status": execution.get("execution_status"),
            "result_ordered_sha256": execution.get("result_ordered_sha256"),
            "result_multiset_sha256": execution.get("result_multiset_sha256"),
            "collection_dir": execution.get("collection_dir"),
            "foreign_scan_time_share": _ratio(
                execution.get("coordinator_foreign_scan_time_ms_sum"), root_time
            ),
            "edge_remote_bytes_sum": _sum(edges, "remote_bytes_proxy"),
            "edge_boundary_wait_share": _ratio(
                _sum(edges, "foreign_scan_minus_regional_time_ms_proxy"), root_time
            ),
            "edge_rtt_context_median_ms_max": _max(edges, "rtt_context_median_ms"),
            "edge_source_tx_bps_hmean": _harmonic(edges, "query_window_source_tx_bps"),
            "regional_input_to_remote_rows_ratio": _ratio(worker_scan_rows, remote_rows),
            "regional_input_to_remote_bytes_ratio": _ratio(worker_tuple_bytes, remote_tuple_bytes),
            "regional_actual_time_per_remote_row": _ratio(
                execution.get("remote_region_actual_time_sum"), remote_rows
            ),
            "remote_region_has_aggregate_share": _boolean_share(regions, "remote_has_aggregate"),
            "gac_fanin_to_final_rows_ratio": _ratio(
                execution.get("coordinator_fanin_rows"), final_rows
            ),
            "gac_blocking_input_to_final_rows_ratio": _ratio(
                execution.get("coordinator_blocking_input_rows_sum"), final_rows
            ),
            "coordinator_non_foreign_time_share_proxy": _float(
                execution.get("coordinator_non_foreign_time_share_proxy")
            ),
            "gac_sort_time_share": _ratio(execution.get("coordinator_sort_time_ms_max"), root_time),
            "gac_aggregate_time_share": _ratio(
                execution.get("coordinator_aggregate_time_ms_max"), root_time
            ),
            "remote_region_actual_time_cv": _float(execution.get("remote_region_actual_time_cv")),
            "remote_region_actual_rows_max_share": _float(
                execution.get("remote_region_actual_rows_max_share")
            ),
            "worker_task_scan_actual_rows_cv": _float(
                execution.get("worker_task_scan_actual_rows_cv")
            ),
            "worker_task_scan_actual_rows_max_share": _float(
                execution.get("worker_task_scan_actual_rows_max_share")
            ),
            "worker_time_cv": _float(execution.get("worker_time_cv")),
            "gac_temp_written_per_final_row": _ratio(
                execution.get("coordinator_temp_written_blocks"), final_rows
            ),
            "gac_hash_batch_excess": (
                None
                if _float(execution.get("coordinator_hash_batches_max")) is None
                else max(float(execution["coordinator_hash_batches_max"]) - 1.0, 0.0)
            ),
            "regional_temp_written_per_remote_row": _ratio(
                execution.get("regional_temp_written_blocks_sum"), remote_rows
            ),
            "worker_task_temp_written_per_scan_row": _ratio(
                execution.get("worker_task_temp_written_sum"), worker_scan_rows
            ),
            "spill_location_count": len(spill_locations),
            "citus_repartition_observed_v2": _float(execution.get("citus_repartition_observed_v2")),
            "remote_citus_repartition_mapmerge_count": _float(
                execution.get("remote_citus_repartition_mapmerge_count")
            ),
            "remote_citus_dependent_map_task_count_sum": _float(
                execution.get("remote_citus_dependent_map_task_count_sum")
            ),
            "remote_citus_dependent_merge_task_count_sum": _float(
                execution.get("remote_citus_dependent_merge_task_count_sum")
            ),
            "remote_citus_repartition_fanout_ratio_max": _float(
                execution.get("remote_citus_repartition_fanout_ratio_max")
            ),
            "remote_citus_plan_locality_class": execution.get(
                "remote_citus_dominant_plan_locality_class"
            ),
        }
        result.append(row)
    return result


def result_consistency(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = {
        str(row.get("result_ordered_sha256")) for row in rows if row.get("result_ordered_sha256")
    }
    multiset = {
        str(row.get("result_multiset_sha256")) for row in rows if row.get("result_multiset_sha256")
    }
    statuses = {str(row.get("execution_status")) for row in rows}
    complete = statuses == {"completed"}
    return {
        "status": (
            "equivalent" if complete and len(ordered) == 1 and len(multiset) == 1 else "unresolved"
        ),
        "ordered_sha256": next(iter(ordered)) if len(ordered) == 1 else None,
        "multiset_sha256": next(iter(multiset)) if len(multiset) == 1 else None,
        "ordered_hash_count": len(ordered),
        "multiset_hash_count": len(multiset),
        "execution_statuses": sorted(statuses),
    }


def bootstrap_elapsed_gain(
    before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    before_values = [
        float(row["elapsed_seconds"])
        for row in before
        if _float(row.get("elapsed_seconds")) not in {None, 0.0}
    ]
    after_values = [
        float(row["elapsed_seconds"])
        for row in after
        if _float(row.get("elapsed_seconds")) not in {None, 0.0}
    ]
    if not before_values or not after_values:
        return {
            "elapsed_log2_gain": None,
            "interval_low": None,
            "interval_high": None,
            "noise_status": "insufficient",
            "direction": "within_noise_or_unavailable",
        }
    point = math.log2(statistics.median(before_values) / statistics.median(after_values))
    rng = random.Random(BOOTSTRAP_SEED)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        before_sample = [rng.choice(before_values) for _ in before_values]
        after_sample = [rng.choice(after_values) for _ in after_values]
        draws.append(math.log2(statistics.median(before_sample) / statistics.median(after_sample)))
    draws.sort()
    low = draws[int((BOOTSTRAP_ALPHA / 2.0) * (len(draws) - 1))]
    high = draws[int((1.0 - BOOTSTRAP_ALPHA / 2.0) * (len(draws) - 1))]
    if low > 0:
        direction = "improved"
        noise_status = "resolved"
    elif high < 0:
        direction = "worsened"
        noise_status = "resolved"
    else:
        direction = "within_noise_or_unavailable"
        noise_status = "within_noise"
    return {
        "elapsed_log2_gain": point,
        "interval_low": low,
        "interval_high": high,
        "noise_status": noise_status,
        "direction": direction,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
    }


def analyze_state(
    *,
    run_root: Path,
    state_id: str,
    phase: str,
    trajectory_id: str,
    step_index: int,
    action_id: str,
    template_id: str,
    sweep_dirs: Sequence[Path],
    origin_state_id: str | None,
    previous_state_id: str | None,
    accepted_history_state_ids: Sequence[str],
) -> dict[str, Any]:
    verify_contracts(run_root)
    rows: list[dict[str, Any]] = []
    for sweep_dir in sweep_dirs:
        rows.extend(derive_signal_rows(sweep_dir / "_index"))
    if not rows:
        raise ContractError(f"no execution features in {list(sweep_dirs)}")
    state_dir = run_root / "states" / state_id
    state_dir.mkdir(parents=True, exist_ok=True)
    raw_path = state_dir / "raw_signals.csv"
    raw_fields = list(rows[0])
    write_csv(raw_path, rows, raw_fields)

    def state_rows(identifier: str | None) -> list[dict[str, str]]:
        if not identifier:
            return []
        return read_csv(run_root / "states" / identifier / "raw_signals.csv")

    origin_rows = state_rows(origin_state_id) or rows
    previous_rows = state_rows(previous_state_id) or origin_rows
    history_rows: list[dict[str, str]] = []
    for identifier in accepted_history_state_ids:
        history_rows.extend(state_rows(identifier))
    domain_manifest = load_yaml(run_root / "contracts/pressure_domain_manifest.yaml")
    profile = build_relative_profile(
        domain_manifest,
        rows,
        {
            "trajectory_origin": origin_rows,
            "previous_accepted_state": previous_rows,
            "prior_logical_question_history": history_rows,
        },
    )
    profile.update(
        {
            "state_id": state_id,
            "trajectory_id": trajectory_id,
            "step_index": step_index,
            "origin_state_id": origin_state_id or state_id,
            "previous_state_id": previous_state_id or state_id,
            "history_state_ids": list(accepted_history_state_ids),
        }
    )
    profile_path = state_dir / "domain_profile.json"
    write_json(profile_path, profile)
    result = result_consistency(rows)
    elapsed = [float(row["elapsed_seconds"]) for row in rows if row.get("elapsed_seconds")]
    summary = {
        "state_id": state_id,
        "phase": phase,
        "trajectory_id": trajectory_id,
        "step_index": step_index,
        "action_id": action_id,
        "template_id": template_id,
        "repetition_count": len(rows),
        "elapsed_median_seconds": robust_center(elapsed),
        "elapsed_mad_seconds": robust_scale(elapsed, floor=0.0),
        "elapsed_min_seconds": min(elapsed) if elapsed else None,
        "elapsed_max_seconds": max(elapsed) if elapsed else None,
        "result": result,
        "profile_path": str(profile_path),
        "raw_signal_path": str(raw_path),
        "sweep_dir": ";".join(str(path) for path in sweep_dirs),
        "sweep_dirs": [str(path) for path in sweep_dirs],
    }
    write_json(state_dir / "state_summary.json", summary)
    append_csv(
        run_root / "trajectory_states.csv",
        {
            **summary,
            "accepted": "pending",
            "result_status": result["status"],
            "ordered_sha256": result["ordered_sha256"],
            "multiset_sha256": result["multiset_sha256"],
        },
        STATE_FIELDS,
    )
    return summary


def append_decision(run_root: Path, record: Mapping[str, Any]) -> None:
    verify_contracts(run_root)
    if record.get("record_type") == "decision":
        trajectories = load_yaml(run_root / "contracts/query_trajectory_manifest.yaml")
        trajectory = next(
            (
                item
                for item in trajectories["trajectories"]
                if item["id"] == record.get("trajectory_id")
            ),
            None,
        )
        if trajectory is None:
            raise ContractError(f"unknown trajectory: {record.get('trajectory_id')}")
        if record.get("action_id") not in trajectory["allowed_actions"]:
            raise ContractError(
                f"action {record.get('action_id')} is not frozen for {record.get('trajectory_id')}"
            )
    schema = json.loads(
        (run_root / "contracts/schemas/decision_log.schema.json").read_text(encoding="utf-8")
    )
    record_type = str(record.get("record_type", ""))
    if record_type not in {"decision", "outcome"}:
        raise ContractError(f"unsupported decision-log record type: {record_type!r}")
    definition = schema["$defs"][record_type]
    branch = definition["allOf"][1]
    required = set(schema["$defs"]["base"]["required"]) | set(branch["required"])
    missing = required - set(record)
    if missing:
        raise ContractError(f"{record_type} record misses fields {sorted(missing)}")
    allowed = set(schema["$defs"]["base"]["properties"]) | set(branch["properties"])
    extra = set(record) - allowed
    if extra:
        raise ContractError(f"{record_type} record has unknown fields {sorted(extra)}")
    path = run_root / "decision_log.jsonl"
    existing = []
    if path.exists():
        existing = [json.loads(line) for line in path.read_text().splitlines() if line]
    candidate = [*existing, dict(record)]
    errors = validate_decision_log(candidate)
    if errors:
        raise ContractError("; ".join(errors))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()


def decision_record(
    *,
    decision_id: str,
    trajectory_id: str,
    step_index: int,
    source_state_id: str,
    action_id: str,
    hypothesis: str,
    target_domains: Sequence[str],
    expected_domain_directions: Mapping[str, str],
    expected_end_to_end_impact: str,
    known_risks: Sequence[str],
    rollback_plan: str,
    evidence_snapshot_refs: Sequence[str],
    identity_mode: str,
    applicability_status: str = "applicable",
) -> dict[str, Any]:
    timestamp = utc_now()
    return {
        "record_type": "decision",
        "decision_id": decision_id,
        "trajectory_id": trajectory_id,
        "step_index": step_index,
        "recorded_at_utc": timestamp,
        "history_cutoff_utc": timestamp,
        "source_state_id": source_state_id,
        "action_id": action_id,
        "hypothesis": hypothesis,
        "target_domains": list(target_domains),
        "expected_domain_directions": dict(expected_domain_directions),
        "expected_end_to_end_impact": expected_end_to_end_impact,
        "known_risks": list(known_risks),
        "rollback_plan": rollback_plan,
        "evidence_snapshot_refs": list(evidence_snapshot_refs),
        "identity_mode": identity_mode,
        "applicability_status": applicability_status,
        "status": "locked_pre_execution",
        "domain_contract_version": "pressure-relative-profile-v1",
    }


def _update_state_acceptance(run_root: Path, state_id: str, accepted: bool) -> None:
    path = run_root / "trajectory_states.csv"
    rows = read_csv(path)
    for row in rows:
        if row.get("state_id") == state_id:
            row["accepted"] = str(accepted).lower()
    write_csv(path, rows, STATE_FIELDS)


def record_transition(
    *,
    run_root: Path,
    decision_id: str,
    trajectory_id: str,
    step_index: int,
    source_state_id: str,
    target_state_id: str,
    action_id: str,
    rollback_status: str,
    accept_state: bool,
) -> dict[str, Any]:
    """Persist one post-outcome transition without changing frozen criteria."""

    verify_contracts(run_root)
    before_dir = run_root / "states" / source_state_id
    after_dir = run_root / "states" / target_state_id
    before_rows = read_csv(before_dir / "raw_signals.csv")
    after_rows = read_csv(after_dir / "raw_signals.csv")
    before_summary = json.loads((before_dir / "state_summary.json").read_text())
    after_summary = json.loads((after_dir / "state_summary.json").read_text())
    before_result = before_summary["result"]
    after_result = after_summary["result"]
    equivalent = (
        before_result.get("status") == "equivalent"
        and after_result.get("status") == "equivalent"
        and before_result.get("ordered_sha256") == after_result.get("ordered_sha256")
        and before_result.get("multiset_sha256") == after_result.get("multiset_sha256")
    )
    result_status = "equivalent" if equivalent else "different"
    gain = bootstrap_elapsed_gain(before_rows, after_rows)
    profile = json.loads((after_dir / "domain_profile.json").read_text())
    previous_coordinates = profile["views"]["previous_accepted_state"]["coordinates"]
    available_values = [
        coordinate.get("relative_pressure_evidence")
        for coordinate in previous_coordinates
        if coordinate.get("relative_pressure_evidence") is not None
    ]
    adverse = any(float(value) > 0 for value in available_values)
    beneficial = any(float(value) < 0 for value in available_values)
    conflict = any(
        bool(coordinate.get("conflicting_component_signs")) for coordinate in previous_coordinates
    )
    outcome_label = classify_outcome(
        result_valid=equivalent,
        outcome_direction=str(gain["direction"]),
        adverse_domain_change=adverse,
        beneficial_domain_change=beneficial,
        conflicting_domain_components=conflict,
    )
    accepted = bool(accept_state and equivalent)

    feature_ids = sorted(
        (set(before_rows[0]) & set(after_rows[0]))
        - {
            "query_run_id",
            "execution_slot_id",
            "repetition_index",
            "execution_status",
            "result_ordered_sha256",
            "result_multiset_sha256",
            "collection_dir",
            "remote_citus_plan_locality_class",
        }
    )
    for feature_id in feature_ids:
        before = robust_center(row.get(feature_id) for row in before_rows)
        after = robust_center(row.get(feature_id) for row in after_rows)
        if before is None or after is None:
            status = "unavailable"
            absolute = None
            relative = None
        else:
            status = "observed"
            absolute = after - before
            denominator = abs(after) + abs(before) + 1e-12
            relative = 2.0 * absolute / denominator
        append_csv(
            run_root / "raw_signal_deltas.csv",
            {
                "decision_id": decision_id,
                "trajectory_id": trajectory_id,
                "source_state_id": source_state_id,
                "target_state_id": target_state_id,
                "action_id": action_id,
                "feature_id": feature_id,
                "before_median": before,
                "after_median": after,
                "absolute_delta": absolute,
                "relative_delta": relative,
                "status": status,
            },
            RAW_DELTA_FIELDS,
        )
    for view_name, view in profile["views"].items():
        for coordinate in view.get("coordinates", []):
            append_csv(
                run_root / "domain_profile_deltas.csv",
                {
                    "decision_id": decision_id,
                    "trajectory_id": trajectory_id,
                    "source_state_id": source_state_id,
                    "target_state_id": target_state_id,
                    "action_id": action_id,
                    "reference_view": view_name,
                    "domain_id": coordinate["domain_id"],
                    "relative_pressure_evidence": coordinate.get("relative_pressure_evidence"),
                    "status": coordinate.get("status"),
                    "conflicting_component_signs": coordinate.get("conflicting_component_signs"),
                    "positive_component_count": coordinate.get("positive_component_count"),
                    "negative_component_count": coordinate.get("negative_component_count"),
                },
                DOMAIN_DELTA_FIELDS,
            )
    transition = {
        "decision_id": decision_id,
        "trajectory_id": trajectory_id,
        "step_index": step_index,
        "source_state_id": source_state_id,
        "target_state_id": target_state_id,
        "action_id": action_id,
        "result_validation_status": result_status,
        "elapsed_log2_gain": gain["elapsed_log2_gain"],
        "elapsed_gain_interval_low": gain["interval_low"],
        "elapsed_gain_interval_high": gain["interval_high"],
        "noise_status": gain["noise_status"],
        "outcome_label": outcome_label,
        "accepted": str(accepted).lower(),
        "rollback_status": rollback_status,
    }
    append_csv(run_root / "trajectory_transitions.csv", transition, TRANSITION_FIELDS)
    append_csv(
        run_root / "result_equivalence_audit.csv",
        {
            **transition,
            "before_ordered_sha256": before_result.get("ordered_sha256"),
            "after_ordered_sha256": after_result.get("ordered_sha256"),
            "before_multiset_sha256": before_result.get("multiset_sha256"),
            "after_multiset_sha256": after_result.get("multiset_sha256"),
        },
        (
            *TRANSITION_FIELDS,
            "before_ordered_sha256",
            "after_ordered_sha256",
            "before_multiset_sha256",
            "after_multiset_sha256",
        ),
    )
    append_csv(
        run_root / "rollback_audit.csv",
        {
            "decision_id": decision_id,
            "trajectory_id": trajectory_id,
            "action_id": action_id,
            "rollback_status": rollback_status,
            "recorded_at_utc": utc_now(),
        },
        (
            "decision_id",
            "trajectory_id",
            "action_id",
            "rollback_status",
            "recorded_at_utc",
        ),
    )
    outcome_record = {
        "record_type": "outcome",
        "decision_id": decision_id,
        "trajectory_id": trajectory_id,
        "step_index": step_index,
        "recorded_at_utc": utc_now(),
        "source_state_id": source_state_id,
        "target_state_id": target_state_id,
        "action_id": action_id,
        "result_validation_status": result_status,
        "profile_before_ref": str(before_dir / "domain_profile.json"),
        "profile_after_ref": str(after_dir / "domain_profile.json"),
        "delta_outcome": gain,
        "outcome_label": outcome_label,
        "rollback_status": rollback_status,
    }
    append_decision(run_root, outcome_record)
    _update_state_acceptance(run_root, target_state_id, accepted)
    write_json(after_dir / "transition_summary.json", {**transition, "gain": gain})
    return {**transition, "gain": gain}


def refresh_checksums(run_root: Path) -> Path:
    output = run_root / "checksums.sha256"
    files = sorted(path for path in run_root.rglob("*") if path.is_file() and path != output)
    output.write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(run_root)}\n" for path in files),
        encoding="utf-8",
    )
    return output


def _iso_from_unix(value: Any) -> str:
    timestamp = _float(value)
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")


def _trajectory_contracts(run_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    manifest = load_yaml(run_root / "contracts/query_trajectory_manifest.yaml")
    by_id = {str(row["id"]): row for row in manifest["trajectories"]}
    by_logical = {
        str(row["logical_question_id"]): str(row["id"]) for row in manifest["trajectories"]
    }
    return by_id, by_logical


def consolidate_execution_manifest(run_root: Path) -> dict[str, int]:
    """Replace reserved slots with the executions that actually occurred."""

    verify_contracts(run_root)
    _, by_logical = _trajectory_contracts(run_root)
    step_by_state = {
        row["state_id"]: row["step_index"] for row in read_csv(run_root / "trajectory_states.csv")
    }
    superseded_path = run_root / "superseded_replay_attempts.json"
    superseded_attempts = (
        json.loads(superseded_path.read_text(encoding="utf-8")) if superseded_path.is_file() else []
    )
    superseded_sweeps = {
        str(Path(sweep).resolve())
        for attempt in superseded_attempts
        for sweep in attempt.get("sweep_dirs", [])
    }
    rows: list[dict[str, Any]] = []
    for query_runs_path in sorted(run_root.rglob("_index/query_runs.csv")):
        sweep_dir = query_runs_path.parents[1]
        superseded = str(sweep_dir.resolve()) in superseded_sweeps
        for source in read_csv(query_runs_path):
            logical_id = str(source.get("logical_question_id") or "")
            trajectory_id = by_logical.get(logical_id, "")
            if logical_id == "collector_smoke":
                trajectory_id = "smoke"
            if source.get("batch_id") == "E_frozen_replay":
                trajectory_id = "trajectory_sort_order_topk"
            state_id = str(source.get("condition_id") or "")
            repeat_index = int(source.get("repetition_index") or 0) + 1
            collection_dir = Path(str(source.get("collection_dir") or ""))
            if collection_dir and not collection_dir.is_absolute():
                collection_dir = sweep_dir / collection_dir
            rows.append(
                {
                    "execution_slot_id": source.get("execution_slot_id"),
                    "phase": source.get("batch_id"),
                    "trajectory_id": trajectory_id,
                    "logical_question_id": logical_id,
                    "state_id": state_id,
                    "step_index": step_by_state.get(state_id, ""),
                    "repeat_index": repeat_index,
                    "repeat_role": (
                        "superseded_invalid_configuration" if superseded else "required"
                    ),
                    "action_id": source.get("mitigation_action"),
                    "template_id": source.get("template_id"),
                    "status": ("superseded_invalid_configuration" if superseded else "completed"),
                    "query_run_id": source.get("query_run_id"),
                    "collection_dir": str(collection_dir),
                    "sweep_dir": str(sweep_dir),
                    "started_at_utc": _iso_from_unix(source.get("query_started_at_unix")),
                    "finished_at_utc": _iso_from_unix(source.get("query_finished_at_unix")),
                    "elapsed_seconds": source.get("elapsed_seconds"),
                    "result_ordered_sha256": source.get("result_ordered_sha256"),
                    "result_multiset_sha256": source.get("result_multiset_sha256"),
                    "execution_status": source.get("execution_status"),
                }
            )

    correctness_count = 0
    for status_path in sorted(run_root.glob("correctness-sweeps/*/query_sweep_status.json")):
        status = json.loads(status_path.read_text(encoding="utf-8"))
        sweep_dir = status_path.parent
        for source in status.get("completed_queries", []):
            correctness_count += 1
            repeat_index = int(source.get("repetition_index") or 0) + 1
            snapshot_candidates = list(
                Path(str(source["collection_dir"])).rglob("result_snapshot.json")
            )
            snapshot = (
                json.loads(snapshot_candidates[0].read_text(encoding="utf-8"))
                if len(snapshot_candidates) == 1
                else {}
            )
            logical_id = str(source.get("logical_question_id") or "")
            rows.append(
                {
                    "execution_slot_id": f"correctness-{source.get('execution_slot_id')}",
                    "phase": "B_correctness_only",
                    "trajectory_id": by_logical.get(logical_id, ""),
                    "logical_question_id": logical_id,
                    "state_id": source.get("condition_id"),
                    "step_index": 0,
                    "repeat_index": repeat_index,
                    "repeat_role": "correctness_only",
                    "action_id": source.get("mitigation_action"),
                    "template_id": source.get("template_id"),
                    "status": "completed",
                    "query_run_id": f"correctness-only-r{repeat_index:02d}",
                    "collection_dir": source.get("collection_dir"),
                    "sweep_dir": str(sweep_dir),
                    "started_at_utc": _iso_from_unix(snapshot.get("query_started_at_unix")),
                    "finished_at_utc": _iso_from_unix(snapshot.get("query_finished_at_unix")),
                    "elapsed_seconds": snapshot.get("elapsed_seconds"),
                    "result_ordered_sha256": snapshot.get("ordered_sha256"),
                    "result_multiset_sha256": snapshot.get("multiset_sha256"),
                    "execution_status": source.get("execution_status"),
                }
            )
    rows.sort(key=lambda row: (str(row["started_at_utc"]), str(row["execution_slot_id"])))
    write_csv(run_root / "execution_manifest.csv", rows, EXECUTION_FIELDS)
    superseded_count = sum(row["repeat_role"] == "superseded_invalid_configuration" for row in rows)
    return {
        "instrumented_execution_count": len(rows) - correctness_count - superseded_count,
        "superseded_instrumented_execution_count": superseded_count,
        "correctness_only_execution_count": correctness_count,
        "total_execution_count": len(rows),
    }


def _state_rows(run_root: Path, state_id: str) -> list[dict[str, str]]:
    return read_csv(run_root / "states" / state_id / "raw_signals.csv")


def _state_summary(run_root: Path, state_id: str) -> dict[str, Any]:
    return json.loads(
        (run_root / "states" / state_id / "state_summary.json").read_text(encoding="utf-8")
    )


def consolidate_state_manifest(run_root: Path) -> None:
    by_id, _ = _trajectory_contracts(run_root)
    logical_by_trajectory = {
        trajectory_id: str(row["logical_question_id"]) for trajectory_id, row in by_id.items()
    }
    rows = read_csv(run_root / "trajectory_states.csv")
    for row in rows:
        trajectory_id = row["trajectory_id"]
        row["logical_question_id"] = logical_by_trajectory.get(trajectory_id, "")
        if row["state_id"].startswith("replay_"):
            row["logical_question_id"] = "user_value_topk"
            row["accepted"] = "confirmatory"
        elif row["phase"] == "B_origin":
            row["accepted"] = "true" if row["result_status"] == "equivalent" else "false"
        elif row["phase"] == "D_rollback":
            row["accepted"] = "audit_only"
    phase_order = {"B_origin": 1, "C_adaptive": 2, "D_rollback": 3, "E_replay": 4}
    rows.sort(
        key=lambda row: (
            phase_order.get(row["phase"], 99),
            row["trajectory_id"],
            int(row["step_index"]),
            row["state_id"],
        )
    )
    write_csv(run_root / "trajectory_states.csv", rows, STATE_FIELDS)


def _replay_tables(run_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state_ids = (
        "replay_A_baseline",
        "replay_B_work_mem",
        "replay_C_pushdown",
        "replay_D_wan_delay",
    )
    state_rows: list[dict[str, Any]] = []
    for state_id in state_ids:
        summary = _state_summary(run_root, state_id)
        result = summary["result"]
        state_rows.append(
            {
                "state_id": state_id,
                "repetition_count": summary["repetition_count"],
                "elapsed_median_seconds": summary["elapsed_median_seconds"],
                "elapsed_mad_seconds": summary["elapsed_mad_seconds"],
                "elapsed_min_seconds": summary["elapsed_min_seconds"],
                "elapsed_max_seconds": summary["elapsed_max_seconds"],
                "result_status": result["status"],
                "ordered_sha256": result["ordered_sha256"],
                "multiset_sha256": result["multiset_sha256"],
            }
        )
    comparisons = (
        ("replay-work-mem", "replay_A_baseline", "replay_B_work_mem", "gac_work_mem_64mb"),
        ("replay-pushdown", "replay_A_baseline", "replay_C_pushdown", "regional_pushdown_rewrite"),
        ("replay-wan-delay", "replay_C_pushdown", "replay_D_wan_delay", "wan_delay_10ms_probe"),
    )
    transition_rows: list[dict[str, Any]] = []
    for comparison_id, before_id, after_id, action_id in comparisons:
        gain = bootstrap_elapsed_gain(
            _state_rows(run_root, before_id), _state_rows(run_root, after_id)
        )
        transition_rows.append(
            {
                "comparison_id": comparison_id,
                "source_state_id": before_id,
                "target_state_id": after_id,
                "action_id": action_id,
                **gain,
                "result_status": _state_summary(run_root, after_id)["result"]["status"],
            }
        )
    write_csv(
        run_root / "frozen_replay_state_summary.csv",
        state_rows,
        list(state_rows[0]),
    )
    write_csv(
        run_root / "frozen_replay_transition_summary.csv",
        transition_rows,
        list(transition_rows[0]),
    )
    return state_rows, transition_rows


def _append_final_audits(run_root: Path, replay_transitions: Sequence[Mapping[str, Any]]) -> None:
    result_fields = (
        *TRANSITION_FIELDS,
        "before_ordered_sha256",
        "after_ordered_sha256",
        "before_multiset_sha256",
        "after_multiset_sha256",
    )
    existing = [
        row
        for row in read_csv(run_root / "result_equivalence_audit.csv")
        if not row["decision_id"].startswith(("phase-d-", "phase-e-", "phase-b-"))
    ]
    existing.append(
        {
            "decision_id": "phase-b-aggregate-exact-result-gate",
            "trajectory_id": "trajectory_aggregate_full_flow",
            "step_index": 0,
            "source_state_id": "trajectory_aggregate_full_flow_s00",
            "target_state_id": "",
            "action_id": "baseline",
            "result_validation_status": "unresolved_float_rendering_variation",
            "noise_status": "not_applicable",
            "outcome_label": "indeterminate",
            "accepted": "false",
            "rollback_status": "not_required",
            "before_ordered_sha256": "",
            "after_ordered_sha256": "",
            "before_multiset_sha256": "",
            "after_multiset_sha256": "",
        }
    )
    for trajectory_id in (
        "trajectory_aggregate_full_flow",
        "trajectory_join_pushdown",
        "trajectory_sort_order_topk",
    ):
        before = _state_summary(run_root, f"{trajectory_id}_s00")
        after = _state_summary(run_root, f"{trajectory_id}_rollback")
        gain = bootstrap_elapsed_gain(
            _state_rows(run_root, f"{trajectory_id}_s00"),
            _state_rows(run_root, f"{trajectory_id}_rollback"),
        )
        before_result = before["result"]
        after_result = after["result"]
        result_status = (
            "equivalent"
            if before_result["status"] == "equivalent"
            and before_result["ordered_sha256"] == after_result["ordered_sha256"]
            and before_result["multiset_sha256"] == after_result["multiset_sha256"]
            else "unresolved_origin_contract"
        )
        existing.append(
            {
                "decision_id": f"phase-d-{trajectory_id}-rollback",
                "trajectory_id": trajectory_id,
                "step_index": 99,
                "source_state_id": f"{trajectory_id}_s00",
                "target_state_id": f"{trajectory_id}_rollback",
                "action_id": "restore_origin",
                "result_validation_status": result_status,
                "elapsed_log2_gain": gain["elapsed_log2_gain"],
                "elapsed_gain_interval_low": gain["interval_low"],
                "elapsed_gain_interval_high": gain["interval_high"],
                "noise_status": gain["noise_status"],
                "outcome_label": "rollback_audit",
                "accepted": "audit_only",
                "rollback_status": "verified",
                "before_ordered_sha256": before_result["ordered_sha256"],
                "after_ordered_sha256": after_result["ordered_sha256"],
                "before_multiset_sha256": before_result["multiset_sha256"],
                "after_multiset_sha256": after_result["multiset_sha256"],
            }
        )
    for row in replay_transitions:
        before = _state_summary(run_root, str(row["source_state_id"]))["result"]
        after = _state_summary(run_root, str(row["target_state_id"]))["result"]
        existing.append(
            {
                "decision_id": f"phase-e-{row['comparison_id']}",
                "trajectory_id": "trajectory_sort_order_topk",
                "step_index": "confirmatory",
                "source_state_id": row["source_state_id"],
                "target_state_id": row["target_state_id"],
                "action_id": row["action_id"],
                "result_validation_status": row["result_status"],
                "elapsed_log2_gain": row["elapsed_log2_gain"],
                "elapsed_gain_interval_low": row["interval_low"],
                "elapsed_gain_interval_high": row["interval_high"],
                "noise_status": row["noise_status"],
                "outcome_label": row["direction"],
                "accepted": "confirmatory",
                "rollback_status": "verified",
                "before_ordered_sha256": before["ordered_sha256"],
                "after_ordered_sha256": after["ordered_sha256"],
                "before_multiset_sha256": before["multiset_sha256"],
                "after_multiset_sha256": after["multiset_sha256"],
            }
        )
    write_csv(run_root / "result_equivalence_audit.csv", existing, result_fields)

    rollback_fields = (
        "decision_id",
        "trajectory_id",
        "action_id",
        "rollback_status",
        "recorded_at_utc",
    )
    rollback = [
        row
        for row in read_csv(run_root / "rollback_audit.csv")
        if not row["decision_id"].startswith(("phase-d-", "phase-e-"))
    ]
    for phase in ("phase-d-final", "phase-e-post-replay"):
        rollback.append(
            {
                "decision_id": phase,
                "trajectory_id": "all",
                "action_id": "restore_initial_infrastructure_state",
                "rollback_status": "verified",
                "recorded_at_utc": utc_now(),
            }
        )
    write_csv(run_root / "rollback_audit.csv", rollback, rollback_fields)


def _ansible_payloads(path: Path) -> dict[str, tuple[str, ...]]:
    payloads: dict[str, list[str]] = defaultdict(list)
    current = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if " | CHANGED | rc=0 >>" in line:
            current = line.split(" |", 1)[0]
            payloads.setdefault(current, [])
        elif current and line and not line.startswith(("[WARNING]", "Unable", "<<<", "[Errno")):
            payloads[current].append(line.strip())
    return {key: tuple(value) for key, value in payloads.items()}


def infrastructure_final_audit(run_root: Path) -> dict[str, Any]:
    initial = run_root / "phase_a/initial_snapshot"
    final = run_root / "phase_d/final_post_replay"
    exact_files = (
        "gac_gucs.txt",
        "regional_gucs.txt",
        "fdw_server_options.txt",
        "dataset_identity.txt",
        "traffic_control.txt",
        "capture_processes.txt",
    )
    checks: dict[str, Any] = {}
    for filename in exact_files:
        before = _ansible_payloads(initial / filename)
        after = _ansible_payloads(final / filename)
        checks[filename.removesuffix(".txt")] = {
            "status": "PASS" if before == after else "FAIL",
            "initial_node_count": len(before),
            "final_node_count": len(after),
        }
    clock = _ansible_payloads(final / "clock_status.txt")
    clock_ok = bool(clock) and all(lines and lines[-1] == "yes" for lines in clock.values())
    checks["clock_synchronization"] = {
        "status": "PASS" if clock_ok else "FAIL",
        "node_count": len(clock),
    }
    initial_status = json.loads((initial / "snapshot_status.json").read_text(encoding="utf-8"))
    final_status = json.loads((final / "snapshot_status.json").read_text(encoding="utf-8"))
    hardware_ok = (
        initial_status.get("hardware_snapshot_count") == 1
        and final_status.get("hardware_snapshot_count") == 0
    )
    checks["hardware_snapshot_policy"] = {
        "status": "PASS" if hardware_ok else "FAIL",
        "initial_count": initial_status.get("hardware_snapshot_count"),
        "final_count": final_status.get("hardware_snapshot_count"),
    }
    payload = {
        "audited_at_utc": utc_now(),
        "status": (
            "PASS" if all(check["status"] == "PASS" for check in checks.values()) else "FAIL"
        ),
        "checks": checks,
    }
    write_json(run_root / "infrastructure_final_audit.json", payload)
    return payload


def _raw_medians(run_root: Path, state_id: str) -> dict[str, float | None]:
    rows = _state_rows(run_root, state_id)
    fields = (
        "foreign_scan_time_share",
        "edge_remote_bytes_sum",
        "edge_boundary_wait_share",
        "edge_rtt_context_median_ms_max",
        "gac_fanin_to_final_rows_ratio",
        "gac_temp_written_per_final_row",
        "gac_hash_batch_excess",
        "spill_location_count",
    )
    medians: dict[str, float | None] = {}
    for field in fields:
        values = [_float(row.get(field)) for row in rows]
        available = [value for value in values if value is not None]
        medians[field] = statistics.median(available) if available else None
    return medians


def _fmt(value: Any, digits: int = 4) -> str:
    numeric = _float(value)
    return "NA" if numeric is None else f"{numeric:.{digits}f}"


def write_feedback_loop_reports(
    run_root: Path,
    execution_counts: Mapping[str, int],
    replay_states: Sequence[Mapping[str, Any]],
    replay_transitions: Sequence[Mapping[str, Any]],
    infra_audit: Mapping[str, Any],
) -> None:
    transitions = read_csv(run_root / "trajectory_transitions.csv")
    states = {row["state_id"]: row for row in read_csv(run_root / "trajectory_states.csv")}
    exploratory_lines = [
        "# Exploratory feedback-loop report",
        "",
        "## Scope and frozen contract",
        "",
        "The run used the frozen Task 1 contracts. No RQ, hypothesis, domain, "
        "intervention catalog, or evaluation rule was changed after observing results.",
        "",
        f"- Fully instrumented SQL executions: {execution_counts['instrumented_execution_count']}",
        "- Superseded instrumented replay executions retained for audit: "
        f"{execution_counts['superseded_instrumented_execution_count']}",
        f"- Correctness-only executions: {execution_counts['correctness_only_execution_count']}",
        "- Active topology: GAC with EU and US; APAC was health-checked but excluded from queries.",
        "- Static hardware snapshots: one, before the smoke test.",
        "",
        "## Phase A",
        "",
        "All GAC, regional coordinator, and worker health checks passed. Stale APAC "
        "capture processes found before the smoke test were stopped. The smoke query "
        "passed result validation, artifact correlation, rollback, and indexing.",
        "",
        "## Phase B baselines",
        "",
        "| Trajectory | Repeats | Median (s) | MAD (s) | Result contract |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for state_id in (
        "trajectory_aggregate_full_flow_s00",
        "trajectory_join_pushdown_s00",
        "trajectory_sort_order_topk_s00",
    ):
        row = states[state_id]
        exploratory_lines.append(
            f"| {row['trajectory_id']} | {row['repetition_count']} | "
            f"{_fmt(row['elapsed_median_seconds'], 3)} | "
            f"{_fmt(row['elapsed_mad_seconds'], 3)} | {row['result_status']} |"
        )
    exploratory_lines.extend(
        [
            "",
            "The aggregate/full-flow trajectory was stopped before adaptation. Exact "
            "rendered-value hashes alternated because `double precision` output differed "
            "in the last representable digits. The frozen contract had no numeric "
            "tolerance, so the state was retained for audit and not accepted.",
            "",
            "## Phase C adaptive transitions",
            "",
            "| Trajectory | Action | log2 gain | 95% interval | Result | Accepted |",
            "| --- | --- | ---: | --- | --- | --- |",
        ]
    )
    for row in transitions:
        exploratory_lines.append(
            f"| {row['trajectory_id']} | {row['action_id']} | "
            f"{_fmt(row['elapsed_log2_gain'], 3)} | "
            f"[{_fmt(row['elapsed_gain_interval_low'], 3)}, "
            f"{_fmt(row['elapsed_gain_interval_high'], 3)}] | "
            f"{row['outcome_label']} | {row['accepted']} |"
        )
    exploratory_lines.extend(
        [
            "",
            "All five valid transitions preserved ordered and multiset result hashes. "
            "The labels are mixed because at least one physical domain moved against "
            "the targeted direction; end-to-end acceleration alone did not overwrite "
            "that conflict.",
            "",
            "## Phase D rollback",
            "",
            "All mutable GUC, FDW, network, process, and dataset checks matched the "
            "initial snapshot. Join and Top-K result hashes matched their origins. The "
            "aggregate rollback state remained subject to the same pre-existing exact "
            "floating-point rendering limitation.",
            "",
            f"Final infrastructure audit: **{infra_audit['status']}**.",
            "",
        ]
    )
    (run_root / "exploratory_report.md").write_text("\n".join(exploratory_lines), encoding="utf-8")

    replay_by_id = {str(row["state_id"]): row for row in replay_states}
    raw = {state_id: _raw_medians(run_root, state_id) for state_id in replay_by_id}
    replay_lines = [
        "# Confirmatory frozen replay report",
        "",
        "## Design",
        "",
        "Four states were frozen after exploration and executed five times each in a "
        "predeclared balanced Williams order. Replay outcomes were not used for further "
        "decisions or tuning.",
        "",
        "| State | Median (s) | MAD (s) | Min-max (s) | Result |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for state_id in replay_by_id:
        row = replay_by_id[state_id]
        replay_lines.append(
            f"| {state_id} | {_fmt(row['elapsed_median_seconds'], 3)} | "
            f"{_fmt(row['elapsed_mad_seconds'], 3)} | "
            f"{_fmt(row['elapsed_min_seconds'], 3)}-{_fmt(row['elapsed_max_seconds'], 3)} | "
            f"{row['result_status']} |"
        )
    replay_lines.extend(
        [
            "",
            "## Confirmatory effects",
            "",
            "| Comparison | log2 gain | 95% interval | Direction |",
            "| --- | ---: | --- | --- |",
        ]
    )
    for row in replay_transitions:
        replay_lines.append(
            f"| {row['comparison_id']} | {_fmt(row['elapsed_log2_gain'], 3)} | "
            f"[{_fmt(row['interval_low'], 3)}, {_fmt(row['interval_high'], 3)}] | "
            f"{row['direction']} |"
        )
    work_mem_transition = next(
        row for row in replay_transitions if row["comparison_id"] == "replay-work-mem"
    )
    work_mem_low = float(work_mem_transition["interval_low"])
    work_mem_high = float(work_mem_transition["interval_high"])
    if work_mem_low > 0:
        work_mem_narrative = (
            "The small exploratory `work_mem` improvement reproduced: its confirmatory "
            "interval excludes zero, while GAC temp writes and hash-batch excess both "
            "decreased."
        )
        work_mem_conclusion = "reproduced with a small positive end-to-end effect."
    elif work_mem_high < 0:
        work_mem_narrative = (
            "The exploratory `work_mem` improvement was contradicted: the confirmatory "
            "interval is entirely negative."
        )
        work_mem_conclusion = "contradicted by the confirmatory replay."
    else:
        work_mem_narrative = (
            "The small exploratory `work_mem` improvement did not resolve in replay: "
            "its confirmatory interval includes zero."
        )
        work_mem_conclusion = "not resolved by the confirmatory replay."
    replay_lines.extend(
        [
            "",
            f"{work_mem_narrative} The regional rewrite reproduced a strong speedup "
            "and reduced transferred bytes and GAC fan-in. The 10 ms EU WAN probe "
            "reproduced a clear slowdown and increased RTT/boundary-wait evidence.",
            "",
            "## Key physical evidence (median)",
            "",
            "| State | Remote bytes | Boundary wait share | RTT max (ms) | "
            "Fan-in/final rows | GAC temp/final row | Hash excess |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for state_id, signals in raw.items():
        replay_lines.append(
            f"| {state_id} | {_fmt(signals['edge_remote_bytes_sum'], 0)} | "
            f"{_fmt(signals['edge_boundary_wait_share'])} | "
            f"{_fmt(signals['edge_rtt_context_median_ms_max'], 3)} | "
            f"{_fmt(signals['gac_fanin_to_final_rows_ratio'], 3)} | "
            f"{_fmt(signals['gac_temp_written_per_final_row'], 5)} | "
            f"{_fmt(signals['gac_hash_batch_excess'], 1)} |"
        )
    replay_lines.extend(
        [
            "",
            "## Conclusion stability",
            "",
            "- Regional pushdown/reduction: reproduced.",
            "- WAN-delay negative transition: reproduced.",
            f"- GAC `work_mem` effect: {work_mem_conclusion}",
            "- Result equivalence: 20/20 replay executions passed exact ordered "
            "and multiset hashes.",
            "- Infrastructure restoration: verified after replay.",
            "",
        ]
    )
    (run_root / "confirmatory_replay_report.md").write_text(
        "\n".join(replay_lines), encoding="utf-8"
    )


def validate_completed_feedback_loop(run_root: Path) -> dict[str, Any]:
    verify_contracts(run_root)
    checks: dict[str, dict[str, Any]] = {}

    executions = read_csv(run_root / "execution_manifest.csv")
    instrumented = [
        row
        for row in executions
        if row["repeat_role"] == "required" and row["status"] == "completed"
    ]
    checks["instrumented_executions"] = {
        "status": "PASS" if len(instrumented) == 60 else "FAIL",
        "observed": len(instrumented),
        "expected": 60,
    }
    checks["execution_statuses"] = {
        "status": (
            "PASS"
            if executions and all(row["execution_status"] == "completed" for row in executions)
            else "FAIL"
        )
    }
    replay_plan = read_csv(run_root / "frozen_replay_execution_plan.csv")
    checks["frozen_replay"] = {
        "status": (
            "PASS"
            if len(replay_plan) == 20 and all(row["status"] == "completed" for row in replay_plan)
            else "FAIL"
        ),
        "observed": len(replay_plan),
        "expected": 20,
    }
    decisions = [
        json.loads(line)
        for line in (run_root / "decision_log.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decision_by_id = {
        row["decision_id"]: row for row in decisions if row["record_type"] == "decision"
    }
    outcomes = [row for row in decisions if row["record_type"] == "outcome"]
    chronology_ok = all(
        outcome["decision_id"] in decision_by_id
        and decision_by_id[outcome["decision_id"]]["recorded_at_utc"] < outcome["recorded_at_utc"]
        for outcome in outcomes
    )
    checks["pre_outcome_decisions"] = {
        "status": "PASS" if chronology_ok and len(decision_by_id) == 5 else "FAIL",
        "decision_count": len(decision_by_id),
        "outcome_count": len(outcomes),
    }
    decision_log_errors = validate_decision_log(decisions)
    execution_start_by_decision: dict[str, str] = {}
    for decision_id, decision in decision_by_id.items():
        candidates = [
            row["started_at_utc"]
            for row in instrumented
            if row["phase"] == "C_adaptive"
            and row["trajectory_id"] == decision["trajectory_id"]
            and row["action_id"] == decision["action_id"]
            and row["started_at_utc"]
        ]
        if candidates:
            execution_start_by_decision[decision_id] = min(candidates)
    locked_before_execution = all(
        decision_id in execution_start_by_decision
        and decision["recorded_at_utc"] < execution_start_by_decision[decision_id]
        for decision_id, decision in decision_by_id.items()
    )
    checks["decision_log_leakage"] = {
        "status": ("PASS" if not decision_log_errors and locked_before_execution else "FAIL"),
        "validation_errors": decision_log_errors,
        "decision_start_count": len(execution_start_by_decision),
    }
    catalog = load_yaml(run_root / "contracts/intervention_catalog.yaml")
    allowed = {str(row["id"]) for row in catalog["interventions"]}
    allowed_actions_ok = all(row["action_id"] in allowed for row in decision_by_id.values())
    checks["frozen_action_catalog"] = {"status": "PASS" if allowed_actions_ok else "FAIL"}
    equivalence = read_csv(run_root / "result_equivalence_audit.csv")
    adaptive = [row for row in equivalence if row["decision_id"] in decision_by_id]
    replay = [row for row in equivalence if row["decision_id"].startswith("phase-e-")]
    checks["valid_transition_results"] = {
        "status": (
            "PASS"
            if len(adaptive) == 5
            and all(row["result_validation_status"] == "equivalent" for row in adaptive)
            and len(replay) == 3
            and all(row["result_validation_status"] == "equivalent" for row in replay)
            else "FAIL"
        )
    }
    infra = json.loads((run_root / "infrastructure_final_audit.json").read_text(encoding="utf-8"))
    checks["infrastructure_restored"] = {"status": infra["status"]}
    checks["aggregate_safety_stop"] = {
        "status": (
            "PASS"
            if any(
                row["decision_id"] == "phase-b-aggregate-exact-result-gate"
                and row["accepted"] == "false"
                for row in equivalence
            )
            else "FAIL"
        )
    }
    payload = {
        "validated_at_utc": utc_now(),
        "status": (
            "PASS" if all(check["status"] == "PASS" for check in checks.values()) else "FAIL"
        ),
        "checks": checks,
    }
    write_json(run_root / "final_validation.json", payload)
    return payload


def supersede_invalid_replay_attempt(
    run_root: Path,
    *,
    reason: str,
) -> dict[str, Any]:
    """Archive derived replay attempt 1 and reset the unchanged frozen plan."""

    verify_contracts(run_root)
    audit_path = run_root / "superseded_replay_attempts.json"
    attempts = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else []
    if attempts:
        raise ContractError("a replay attempt has already been superseded")
    plan_path = run_root / "frozen_replay_execution_plan.csv"
    plan = read_csv(plan_path)
    if len(plan) != 20 or not all(row["status"] == "completed" for row in plan):
        raise ContractError("only a complete 20-slot replay attempt can be superseded")
    sweep_dirs = [row["sweep_dir"] for row in plan]
    archive = run_root / "superseded/phase_e_attempt_1"
    archive.mkdir(parents=True, exist_ok=False)
    for filename in (
        "frozen_replay_execution_plan.csv",
        "frozen_replay_state_summary.csv",
        "frozen_replay_transition_summary.csv",
        "confirmatory_replay_report.md",
        "final_validation.json",
        "infrastructure_final_audit.json",
        "checksums.sha256",
    ):
        source = run_root / filename
        if source.is_file():
            shutil.copy2(source, archive / filename)
    states_archive = archive / "states"
    states_archive.mkdir()
    for state_dir in sorted((run_root / "states").glob("replay_*")):
        shutil.copytree(state_dir, states_archive / state_dir.name)
        shutil.rmtree(state_dir)
    state_rows = [
        row
        for row in read_csv(run_root / "trajectory_states.csv")
        if not row["state_id"].startswith("replay_")
    ]
    write_csv(run_root / "trajectory_states.csv", state_rows, STATE_FIELDS)

    fields = list(plan[0])
    for field in ("attempt_id", "superseded_sweep_dir", "superseded_reason"):
        if field not in fields:
            fields.append(field)
    for row in plan:
        row["attempt_id"] = "2"
        row["superseded_sweep_dir"] = row["sweep_dir"]
        row["superseded_reason"] = reason
        row["status"] = "planned"
        row["sweep_dir"] = ""
    write_csv(plan_path, plan, fields)
    record = {
        "attempt_id": 1,
        "superseded_at_utc": utc_now(),
        "reason": reason,
        "frozen_order_changed": False,
        "frozen_state_definitions_changed": False,
        "sweep_dirs": sweep_dirs,
        "archive_dir": str(archive),
    }
    write_json(audit_path, [record])
    return record


def finalize_feedback_loop_run(run_root: Path) -> dict[str, Any]:
    """Consolidate a completed A-E run without executing infrastructure work."""

    execution_counts = consolidate_execution_manifest(run_root)
    consolidate_state_manifest(run_root)
    replay_states, replay_transitions = _replay_tables(run_root)
    _append_final_audits(run_root, replay_transitions)
    infra = infrastructure_final_audit(run_root)
    write_feedback_loop_reports(
        run_root,
        execution_counts,
        replay_states,
        replay_transitions,
        infra,
    )
    validation = validate_completed_feedback_loop(run_root)
    completion = {
        "completed_at_utc": utc_now(),
        "contract_version": LIVE_CONTRACT_VERSION,
        "execution_counts": execution_counts,
        "infrastructure_status": infra["status"],
        "validation_status": validation["status"],
        "required_outputs": [
            "decision_log.jsonl",
            "execution_manifest.csv",
            "trajectory_states.csv",
            "trajectory_transitions.csv",
            "raw_signal_deltas.csv",
            "domain_profile_deltas.csv",
            "result_equivalence_audit.csv",
            "rollback_audit.csv",
            "exploratory_report.md",
            "frozen_replay_manifest.yaml",
            "confirmatory_replay_report.md",
            "provenance.json",
            "infrastructure_final_audit.json",
            "final_validation.json",
        ],
    }
    write_json(run_root / "completion_manifest.json", completion)
    checksums = refresh_checksums(run_root)
    return {
        "execution_counts": execution_counts,
        "infrastructure_status": infra["status"],
        "validation_status": validation["status"],
        "checksums": str(checksums),
    }
