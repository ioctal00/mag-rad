#!/usr/bin/env python3
"""Run and analyze the frozen exact aggregate feedback-loop addendum.

The script is intentionally separate from the adaptive runner.  All hypotheses,
states, ordering, and outcome rules are frozen before the first query result is
observed.  The execution plan is checkpointed after every indexed query and is
safe to resume.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from master_regimes.feedback_loop import (  # noqa: E402
    ContractError,
    classify_end_to_end_effect,
    classify_physical_transition,
    load_yaml,
)
from master_regimes.feedback_loop_live import (  # noqa: E402
    LIVE_CONTRACT_VERSION,
    STATE_FIELDS,
    analyze_state,
    append_decision,
    bootstrap_elapsed_gain,
    capture_initial_snapshot,
    capture_mutable_snapshot,
    decision_record,
    git_revision,
    read_csv,
    record_transition,
    refresh_checksums,
    result_consistency,
    sha256_file,
    utc_now,
    verify_contracts,
    write_csv,
    write_json,
)

DEFAULT_INFRA_ROOT = ROOT.parent / "master-regimes-infra"
DEFAULT_THESIS_ROOT = ROOT.parent / "master-regimes-thesis"
EXPERIMENT_DIR = ROOT / "experiments/feedback-loop-v1"
TRAJECTORY_ID = "trajectory_aggregate_exact_full_flow"
LOGICAL_QUESTION_ID = "event_exact_full_flow_summary"
INITIAL_FETCH_SIZE = 1000

INSTANCE_FIELDS = (
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
)

PLAN_FIELDS = (
    "execution_order",
    "block_index",
    "position_index",
    "state_id",
    "state_repetition_index",
    "template_id",
    "fetch_size",
    "wan_delay_ms",
    "instance_manifest",
    "status",
    "sweep_dir",
    "started_at_utc",
    "finished_at_utc",
)

OUTCOME_AXIS_FIELDS = (
    "decision_id",
    "trajectory_id",
    "source_state_id",
    "target_state_id",
    "action_id",
    "result_validity",
    "end_to_end_effect",
    "physical_transition",
    "elapsed_log2_gain",
    "elapsed_gain_interval_low",
    "elapsed_gain_interval_high",
    "legacy_outcome_label",
)


def run_command(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
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
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}: {command[0]}"
        )
    return completed


def sweep_path(output: str) -> Path:
    candidates = [
        Path(line.strip()) for line in output.splitlines() if line.strip().startswith("/")
    ]
    if not candidates:
        raise RuntimeError("query sweep did not print its artifact path")
    return candidates[-1]


def _ansible_psql(infra_root: Path, sql: str) -> subprocess.CompletedProcess[str]:
    escaped = sql.replace('"', '\\"')
    return run_command(
        [
            str(infra_root / "common-scripts/run_ansible.sh"),
            "ansible",
            "analytics_clients",
            "-b",
            "--become-user",
            "postgres",
            "-m",
            "shell",
            "-a",
            f'psql -XAt -v ON_ERROR_STOP=1 -d analytics -c "{escaped}"',
        ],
        cwd=infra_root,
    )


def set_fetch_size(
    *, infra_root: Path, run_root: Path, value: int, label: str
) -> dict[str, Any]:
    sql = (
        f"ALTER SERVER eu_citus OPTIONS (SET fetch_size '{value}'); "
        f"ALTER SERVER us_citus OPTIONS (SET fetch_size '{value}'); "
        "SELECT srvname, array_to_string(srvoptions, ',') "
        "FROM pg_foreign_server WHERE srvname IN ('eu_citus','us_citus') ORDER BY 1;"
    )
    completed = _ansible_psql(infra_root, sql)
    expected = f"fetch_size={value}"
    observed = [line for line in completed.stdout.splitlines() if "_citus|" in line]
    if len(observed) != 2 or any(expected not in line for line in observed):
        raise RuntimeError(
            f"FDW fetch_size verification failed for {value}: {observed!r}"
        )
    record = {
        "recorded_at_utc": utc_now(),
        "label": label,
        "requested_fetch_size": value,
        "verified_rows": observed,
    }
    path = run_root / "fdw_option_audit.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
    return record


def network_profile() -> dict[str, Any]:
    return {
        "id": "feedback-loop-aggregate-eu-delay-10ms",
        "target_region_ids": ["eu"],
        "scope": "region_egress_to_analytics",
        "configured_delay_ms": 10,
        "configured_jitter_ms": 0,
        "configured_loss_percent": 0,
        "configured_bandwidth_mbit": 0,
    }


def network_command(
    *, infra_root: Path, run_root: Path, action: str, label: str
) -> None:
    run_command(
        [
            sys.executable,
            str(infra_root / "common-scripts/manage_network_pressure.py"),
            "--action",
            action,
            "--profile-json",
            json.dumps(network_profile(), sort_keys=True),
            "--out-dir",
            str(run_root / "network_interventions"),
            "--label",
            label,
        ],
        cwd=infra_root,
    )


def _contract_source_map() -> dict[str, Path]:
    return {
        "FEEDBACK_LOOP_PROTOCOL.md": EXPERIMENT_DIR / "AGGREGATE_EXACT_PROTOCOL.md",
        "pressure_domain_manifest.yaml": EXPERIMENT_DIR / "pressure_domain_manifest.yaml",
        "intervention_catalog.yaml": EXPERIMENT_DIR / "intervention_catalog.yaml",
        "query_trajectory_manifest.yaml": EXPERIMENT_DIR
        / "aggregate_exact_query_manifest.yaml",
        "rollback_checklist.md": EXPERIMENT_DIR / "rollback_checklist.md",
        "RQ_H_MAPPING.md": EXPERIMENT_DIR / "RQ_H_MAPPING.md",
        "schemas/decision_log.schema.json": EXPERIMENT_DIR
        / "schemas/decision_log.schema.json",
        "aggregate_exact_addendum.yaml": EXPERIMENT_DIR / "aggregate_exact_addendum.yaml",
    }


def prepare_run(
    *, run_root: Path, infra_root: Path, thesis_root: Path
) -> dict[str, Any]:
    if run_root.exists() and any(run_root.iterdir()):
        raise ContractError(f"run root is not empty: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    contracts = run_root / "contracts"
    contracts.mkdir()
    hashes: dict[str, str] = {}
    for relative, source in _contract_source_map().items():
        target = contracts / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[relative] = sha256_file(target)

    manifest = load_yaml(contracts / "query_trajectory_manifest.yaml")
    trajectory = manifest["trajectories"][0]
    suite_path = ROOT / trajectory["suite"]
    suite = load_yaml(suite_path)
    rendered_dir = run_root / "rendered_sql"
    rendered_dir.mkdir()
    environment = Environment(undefined=StrictUndefined, autoescape=False)
    template_ids = [trajectory["baseline_template_id"]]
    template_ids.extend(trajectory["reviewed_equivalent_template_ids"])
    rendered: dict[str, str] = {}
    for template_id in template_ids:
        source = suite_path.parents[1] / suite["templates"][template_id]["file"]
        sql = environment.from_string(source.read_text(encoding="utf-8")).render(
            **trajectory.get("parameter_bindings", {})
        )
        target = rendered_dir / f"{template_id}.sql"
        target.write_text(sql.rstrip() + "\n", encoding="utf-8")
        rendered[template_id] = str(target)

    addendum = load_yaml(contracts / "aggregate_exact_addendum.yaml")
    live_contract = {
        "contract_version": "pressure-feedback-loop-aggregate-exact-live-v1",
        "created_at_utc": utc_now(),
        "source_contract_hashes": hashes,
        "frozen_experiment_id": addendum["experiment_id"],
        "topology_scope": addendum["scope"]["topology_id"],
        "dataset_mutation_allowed": False,
        "schema_mutation_allowed": False,
        "colocation_mutation_allowed": False,
        "index_mutation_allowed": False,
        "hardware_snapshot_policy": "once_before_first_execution",
        "future_outcomes_allowed": False,
        "parallel_queries_allowed": False,
        "total_execution_count": addendum["execution_order"]["total_execution_count"],
        "result_contract": addendum["scope"]["result_contract"],
        "outcome_axes": addendum["outcome_axes"],
        "rendered_sql": rendered,
    }
    write_json(run_root / "live_execution_contract.json", live_contract)
    (run_root / "decision_log.jsonl").touch()
    write_csv(run_root / "trajectory_states.csv", [], STATE_FIELDS)
    provenance = {
        "created_at_utc": utc_now(),
        "run_root": str(run_root),
        "repositories": [
            git_revision(ROOT),
            git_revision(infra_root),
            git_revision(thesis_root),
        ],
        "contract_hashes": hashes,
        "no_dataset_reload": True,
        "no_schema_or_placement_change": True,
    }
    write_json(run_root / "provenance.json", provenance)
    create_execution_plan(run_root)
    lock_hypotheses(run_root)
    return {"run_root": str(run_root), "execution_count": 25, "contracts": hashes}


def create_execution_plan(run_root: Path) -> Path:
    verify_contracts(run_root)
    addendum = load_yaml(run_root / "contracts/aggregate_exact_addendum.yaml")
    states = addendum["states"]
    template_aliases = addendum["templates"]
    template_ids = {
        "raw": "gac_fdw_multiregion_event_exact_raw_summary",
        "regional": "gac_fdw_multiregion_event_exact_regional_summary",
    }
    if template_aliases["raw"] != template_ids["raw"] or template_aliases[
        "regional"
    ] != template_ids["regional"]:
        raise ContractError("exact aggregate template aliases changed")

    plan_rows: list[dict[str, Any]] = []
    repetition_by_state: Counter[str] = Counter()
    manifest_dir = run_root / "instance_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    order = 0
    blocks = list(addendum["execution_order"]["blocks"])
    blocks.append(
        [addendum["execution_order"]["final_rollback_state"]]
        * int(addendum["execution_order"]["final_rollback_repetitions"])
    )
    for block_index, block in enumerate(blocks, start=1):
        for position_index, state_id in enumerate(block, start=1):
            order += 1
            repetition_by_state[state_id] += 1
            repetition = repetition_by_state[state_id]
            definition = states[state_id]
            template_id = template_ids[definition["template"]]
            slot = f"aggregate-exact-{order:02d}-{state_id.lower()}-r{repetition:02d}"
            instance_path = manifest_dir / f"order-{order:02d}.csv"
            instance = {
                "instance_id": slot,
                "template_id": template_id,
                "rendered_sql_path": str(run_root / "rendered_sql" / f"{template_id}.sql"),
                "execution_slot_id": slot,
                "repeat_id": f"r{repetition:02d}",
                "repetition_index": repetition - 1,
                "run_order": order,
                "logical_question_id": LOGICAL_QUESTION_ID,
                "condition_id": f"aggregate_exact_{state_id}",
                "pair_id": "aggregate-exact-confirmatory-v1",
                "variant": state_id,
                "intervention_role": "confirmatory_longitudinal_replay",
                "mitigation_action": state_id,
                "execution_scope": "gac_multi_edge",
                "target_scope": "global_end_to_end",
                "topology_id": addendum["scope"]["topology_id"],
                "dataset_profile_id": addendum["scope"]["dataset_profile_id"],
                "collection_contract_version": LIVE_CONTRACT_VERSION,
                "corpus_version": addendum["experiment_id"],
                "batch_id": "aggregate_exact_confirmatory",
                "cache_policy": "mixed_cache_first_observed",
                "order_policy": "frozen_williams_order",
                "planned_work_units": 1,
                "progress_cost_class": "aggregate_full_flow",
                "pg_options_json": "{}",
                "params": "{}",
            }
            write_csv(instance_path, [instance], INSTANCE_FIELDS)
            plan_rows.append(
                {
                    "execution_order": order,
                    "block_index": block_index,
                    "position_index": position_index,
                    "state_id": state_id,
                    "state_repetition_index": repetition,
                    "template_id": template_id,
                    "fetch_size": definition["fetch_size"],
                    "wan_delay_ms": definition["wan_delay_ms"],
                    "instance_manifest": str(instance_path),
                    "status": "planned",
                    "sweep_dir": "",
                    "started_at_utc": "",
                    "finished_at_utc": "",
                }
            )
    expected = int(addendum["execution_order"]["total_execution_count"])
    if len(plan_rows) != expected:
        raise ContractError(f"execution plan has {len(plan_rows)} rows, expected {expected}")
    expected_counts = {
        "A_raw_baseline": 5,
        "B_fetch_size": 5,
        "C_regional_aggregate": 5,
        "D_wan_delay": 5,
        "R0_prime_rollback": 5,
    }
    if dict(repetition_by_state) != expected_counts:
        raise ContractError(f"unexpected state counts: {dict(repetition_by_state)}")
    output = run_root / "frozen_execution_plan.csv"
    write_csv(output, plan_rows, PLAN_FIELDS)
    return output


def lock_hypotheses(run_root: Path) -> None:
    addendum = load_yaml(run_root / "contracts/aggregate_exact_addendum.yaml")
    direction_by_transition = {
        "aggregate-exact-fetch-size": {"remote_fdw_path": "decrease"},
        "aggregate-exact-pushdown": {
            "regional_reduction": "decrease",
            "remote_fdw_path": "decrease",
            "gac_finalization": "decrease",
        },
        "aggregate-exact-wan-delay": {"remote_fdw_path": "increase"},
    }
    identity_by_transition = {
        "aggregate-exact-fetch-size": "same_sql_declared_intervention",
        "aggregate-exact-pushdown": "manual_logical_question_link",
        "aggregate-exact-wan-delay": "same_sql_declared_intervention",
    }
    for step, transition in enumerate(addendum["transitions"], start=1):
        record = decision_record(
            decision_id=transition["id"],
            trajectory_id=TRAJECTORY_ID,
            step_index=step,
            source_state_id=transition["source"],
            action_id=transition["action_id"],
            hypothesis=transition["hypothesis"],
            target_domains=transition["target_domains"],
            expected_domain_directions=direction_by_transition[transition["id"]],
            expected_end_to_end_impact=transition["expected_runtime_direction"],
            known_risks=[
                "runtime effect may remain within the frozen noise envelope",
                "physical domains may move in conflicting directions",
            ],
            rollback_plan=(
                "Reset the EU and US FDW fetch_size to 1000, remove the frozen EU "
                "network profile, and rerun the exact raw baseline."
            ),
            evidence_snapshot_refs=[
                "contracts/aggregate_exact_addendum.yaml",
                "phase_a/initial_snapshot/snapshot_status.json",
            ],
            identity_mode=identity_by_transition[transition["id"]],
        )
        append_decision(run_root, record)


def execute_plan(*, run_root: Path, infra_root: Path) -> None:
    verify_contracts(run_root)
    plan_path = run_root / "frozen_execution_plan.csv"
    plan = read_csv(plan_path)
    if not (run_root / "phase_a/initial_snapshot/snapshot_status.json").exists():
        capture_initial_snapshot(run_root=run_root, infra_root=infra_root)
    network_active = False
    try:
        for row in plan:
            if row["status"] == "completed":
                continue
            order = int(row["execution_order"])
            total = len(plan)
            state_id = row["state_id"]
            label = f"aggregate-exact-{order:02d}-{state_id.lower()}"
            print(f"[AGGREGATE] {order}/{total} state={state_id}", flush=True)
            row["started_at_utc"] = utc_now()
            write_csv(plan_path, plan, PLAN_FIELDS)
            set_fetch_size(
                infra_root=infra_root,
                run_root=run_root,
                value=int(row["fetch_size"]),
                label=f"{label}-set-fetch-size",
            )
            if int(row["wan_delay_ms"]) > 0:
                network_command(
                    infra_root=infra_root,
                    run_root=run_root,
                    action="apply",
                    label=f"{label}-apply",
                )
                network_active = True
                network_command(
                    infra_root=infra_root,
                    run_root=run_root,
                    action="status",
                    label=f"{label}-status-before",
                )
            else:
                network_command(
                    infra_root=infra_root,
                    run_root=run_root,
                    action="reset",
                    label=f"{label}-preflight-reset",
                )
                network_active = False

            metadata = {
                "feedback_state_id": state_id,
                "logical_question_id": LOGICAL_QUESTION_ID,
                "fdw_fetch_size": int(row["fetch_size"]),
                "network_profile_id": (
                    network_profile()["id"] if int(row["wan_delay_ms"]) > 0 else "none"
                ),
                "configured_latency_ms": int(row["wan_delay_ms"]),
                "configured_jitter_ms": 0,
                "configured_loss_percent": 0,
                "configured_bandwidth_mbit": 0,
            }
            completed = run_command(
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
                    str(run_root / "checkpoints" / f"{label}.jsonl"),
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
                ],
                cwd=infra_root,
            )
            artifact = sweep_path(completed.stdout)
            if network_active:
                network_command(
                    infra_root=infra_root,
                    run_root=run_root,
                    action="reset",
                    label=f"{label}-reset",
                )
                network_active = False
            run_command(
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
            query_runs = read_csv(artifact / "_index/query_runs.csv")
            if len(query_runs) != 1 or query_runs[0].get("execution_status") != "completed":
                raise RuntimeError(f"collector/index verification failed for {artifact}")
            row["status"] = "completed"
            row["sweep_dir"] = str(artifact)
            row["finished_at_utc"] = utc_now()
            write_csv(plan_path, plan, PLAN_FIELDS)
            finished = sum(item["status"] == "completed" for item in plan)
            print(f"[AGGREGATE] progress={finished}/{total}", flush=True)
    finally:
        try:
            network_command(
                infra_root=infra_root,
                run_root=run_root,
                action="reset",
                label="aggregate-exact-finally-reset",
            )
        finally:
            set_fetch_size(
                infra_root=infra_root,
                run_root=run_root,
                value=INITIAL_FETCH_SIZE,
                label="aggregate-exact-finally-restore-fetch-size",
            )


def _state_sweeps(plan: list[dict[str, str]]) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    for row in plan:
        if row["status"] != "completed" or not row["sweep_dir"]:
            raise ContractError(f"incomplete execution slot: {row['execution_order']}")
        grouped[row["state_id"]].append(Path(row["sweep_dir"]))
    return grouped


def _write_outcome_axes(run_root: Path) -> list[dict[str, Any]]:
    transitions = read_csv(run_root / "trajectory_transitions.csv")
    rows: list[dict[str, Any]] = []
    for transition in transitions:
        profile = json.loads(
            (run_root / "states" / transition["target_state_id"] / "domain_profile.json").read_text(
                encoding="utf-8"
            )
        )
        coordinates = profile["views"]["previous_accepted_state"]["coordinates"]
        result_valid = transition["result_validation_status"] == "equivalent"
        rows.append(
            {
                "decision_id": transition["decision_id"],
                "trajectory_id": transition["trajectory_id"],
                "source_state_id": transition["source_state_id"],
                "target_state_id": transition["target_state_id"],
                "action_id": transition["action_id"],
                "result_validity": "equivalent" if result_valid else "non_equivalent",
                "end_to_end_effect": classify_end_to_end_effect(
                    result_valid=result_valid,
                    interval_low=(
                        float(transition["elapsed_gain_interval_low"])
                        if transition["elapsed_gain_interval_low"]
                        else None
                    ),
                    interval_high=(
                        float(transition["elapsed_gain_interval_high"])
                        if transition["elapsed_gain_interval_high"]
                        else None
                    ),
                ),
                "physical_transition": classify_physical_transition(coordinates),
                "elapsed_log2_gain": transition["elapsed_log2_gain"],
                "elapsed_gain_interval_low": transition["elapsed_gain_interval_low"],
                "elapsed_gain_interval_high": transition["elapsed_gain_interval_high"],
                "legacy_outcome_label": transition["outcome_label"],
            }
        )
    write_csv(run_root / "outcome_axes.csv", rows, OUTCOME_AXIS_FIELDS)
    return rows


def analyze_run(*, run_root: Path, infra_root: Path) -> dict[str, Any]:
    verify_contracts(run_root)
    plan = read_csv(run_root / "frozen_execution_plan.csv")
    grouped = _state_sweeps(plan)
    raw_template = "gac_fdw_multiregion_event_exact_raw_summary"
    regional_template = "gac_fdw_multiregion_event_exact_regional_summary"
    definitions = {
        "A_raw_baseline": (0, "baseline", raw_template, None, None, []),
        "B_fetch_size": (
            1,
            "fdw_fetch_size_10000",
            raw_template,
            "A_raw_baseline",
            "A_raw_baseline",
            ["A_raw_baseline"],
        ),
        "C_regional_aggregate": (
            2,
            "regional_pushdown_rewrite",
            regional_template,
            "A_raw_baseline",
            "B_fetch_size",
            ["A_raw_baseline", "B_fetch_size"],
        ),
        "D_wan_delay": (
            3,
            "wan_delay_10ms_probe",
            regional_template,
            "A_raw_baseline",
            "C_regional_aggregate",
            ["A_raw_baseline", "B_fetch_size", "C_regional_aggregate"],
        ),
        "R0_prime_rollback": (
            4,
            "full_rollback",
            raw_template,
            "A_raw_baseline",
            "A_raw_baseline",
            ["A_raw_baseline"],
        ),
    }
    if not (run_root / "states/A_raw_baseline/state_summary.json").exists():
        for state_id in definitions:
            step, action, template, origin, previous, history = definitions[state_id]
            analyze_state(
                run_root=run_root,
                state_id=state_id,
                phase="aggregate_exact_confirmatory",
                trajectory_id=TRAJECTORY_ID,
                step_index=step,
                action_id=action,
                template_id=template,
                sweep_dirs=grouped[state_id],
                origin_state_id=origin,
                previous_state_id=previous,
                accepted_history_state_ids=history,
            )

    # analyze_state predates the logical-question field in its state-level
    # output. The execution manifests already contain this identity; carry it
    # into the derived state index without altering any raw execution artifact.
    state_rows = read_csv(run_root / "trajectory_states.csv")
    for row in state_rows:
        row["logical_question_id"] = LOGICAL_QUESTION_ID
        summary_path = run_root / "states" / row["state_id"] / "state_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["logical_question_id"] = LOGICAL_QUESTION_ID
        write_json(summary_path, summary)
    write_csv(run_root / "trajectory_states.csv", state_rows, STATE_FIELDS)

    transition_specs = [
        ("aggregate-exact-fetch-size", 1, "A_raw_baseline", "B_fetch_size", "fdw_fetch_size_10000"),
        (
            "aggregate-exact-pushdown",
            2,
            "B_fetch_size",
            "C_regional_aggregate",
            "regional_pushdown_rewrite",
        ),
        (
            "aggregate-exact-wan-delay",
            3,
            "C_regional_aggregate",
            "D_wan_delay",
            "wan_delay_10ms_probe",
        ),
    ]
    if not (run_root / "trajectory_transitions.csv").exists():
        for decision_id, step, source, target, action in transition_specs:
            record_transition(
                run_root=run_root,
                decision_id=decision_id,
                trajectory_id=TRAJECTORY_ID,
                step_index=step,
                source_state_id=source,
                target_state_id=target,
                action_id=action,
                rollback_status="not_applicable",
                accept_state=target != "D_wan_delay",
            )
    axes = _write_outcome_axes(run_root)

    baseline_rows = read_csv(run_root / "states/A_raw_baseline/raw_signals.csv")
    rollback_rows = read_csv(run_root / "states/R0_prime_rollback/raw_signals.csv")
    baseline_result = result_consistency(baseline_rows)
    rollback_result = result_consistency(rollback_rows)
    rollback_equivalent = (
        baseline_result["status"] == "equivalent"
        and rollback_result["status"] == "equivalent"
        and baseline_result["ordered_sha256"] == rollback_result["ordered_sha256"]
        and baseline_result["multiset_sha256"] == rollback_result["multiset_sha256"]
    )
    rollback_gain = bootstrap_elapsed_gain(baseline_rows, rollback_rows)
    rollback_profile = json.loads(
        (run_root / "states/R0_prime_rollback/domain_profile.json").read_text(encoding="utf-8")
    )
    rollback_comparison = {
        "source_state_id": "A_raw_baseline",
        "target_state_id": "R0_prime_rollback",
        "result_validity": "equivalent" if rollback_equivalent else "non_equivalent",
        "end_to_end_effect": classify_end_to_end_effect(
            result_valid=rollback_equivalent,
            interval_low=rollback_gain.get("interval_low"),
            interval_high=rollback_gain.get("interval_high"),
        ),
        "physical_transition": classify_physical_transition(
            rollback_profile["views"]["previous_accepted_state"]["coordinates"]
        ),
        "gain": rollback_gain,
    }
    write_json(run_root / "rollback_comparison.json", rollback_comparison)

    network_command(
        infra_root=infra_root,
        run_root=run_root,
        action="reset",
        label="aggregate-exact-analysis-final-reset",
    )
    set_fetch_size(
        infra_root=infra_root,
        run_root=run_root,
        value=INITIAL_FETCH_SIZE,
        label="aggregate-exact-analysis-final-fetch-restore",
    )
    final_snapshot = capture_mutable_snapshot(
        run_root=run_root, infra_root=infra_root, label="aggregate_exact_final"
    )
    final_audit = {
        "captured_at_utc": utc_now(),
        "fdw_fetch_size_restored": True,
        "network_profile_reset": True,
        "hardware_snapshot_repeated": False,
        "mutable_snapshot": final_snapshot,
        "rollback_result_equivalent": rollback_equivalent,
        "gate": "GO" if rollback_equivalent else "STOP",
    }
    write_json(run_root / "infrastructure_final_audit.json", final_audit)

    state_rows = read_csv(run_root / "trajectory_states.csv")
    report_lines = [
        "# Exact aggregate longitudinal addendum",
        "",
        "The addendum used exact COUNT/MIN/MAX output and did not use floating-point tolerance.",
        "",
        "## States",
        "",
        "| State | Repetitions | Median seconds | Result |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in state_rows:
        report_lines.append(
            f"| {row['state_id']} | {row['repetition_count']} | "
            f"{float(row['elapsed_median_seconds']):.6f} | {row['result_status']} |"
        )
    report_lines.extend(
        [
            "",
            "## Independent outcome axes",
            "",
            "| Action | Result validity | End-to-end effect | Physical transition | log2 gain |",
            "| --- | --- | --- | --- | ---: |",
        ]
    )
    for row in axes:
        report_lines.append(
            f"| {row['action_id']} | {row['result_validity']} | "
            f"{row['end_to_end_effect']} | {row['physical_transition']} | "
            f"{float(row['elapsed_log2_gain']):.6f} |"
        )
    report_lines.extend(
        [
            "",
            "## Rollback",
            "",
            f"- Result validity: `{rollback_comparison['result_validity']}`",
            f"- Runtime comparison: `{rollback_comparison['end_to_end_effect']}`",
            f"- Physical comparison: `{rollback_comparison['physical_transition']}`",
            f"- Infrastructure gate: `{final_audit['gate']}`",
            "",
        ]
    )
    (run_root / "aggregate_exact_report.md").write_text(
        "\n".join(report_lines), encoding="utf-8"
    )
    refresh_checksums(run_root)
    return {
        "states": len(state_rows),
        "transitions": len(axes),
        "rollback": rollback_comparison,
        "gate": final_audit["gate"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("prepare", "run", "analyze", "all")
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--infra-root", type=Path, default=DEFAULT_INFRA_ROOT)
    parser.add_argument("--thesis-root", type=Path, default=DEFAULT_THESIS_ROOT)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    infra_root = args.infra_root.resolve()
    if args.command in {"prepare", "all"} and not run_root.exists():
        result = prepare_run(
            run_root=run_root,
            infra_root=infra_root,
            thesis_root=args.thesis_root.resolve(),
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "prepare":
        raise ContractError(f"run root already exists: {run_root}")
    if args.command in {"run", "all"}:
        execute_plan(run_root=run_root, infra_root=infra_root)
    if args.command in {"analyze", "all"}:
        result = analyze_run(run_root=run_root, infra_root=infra_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
