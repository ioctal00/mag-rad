from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis/scripts/agent/108_confirmatory_action_replication.py"


def load_module():
    specification = importlib.util.spec_from_file_location("confirmatory_108", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_manifest_contains_locked_15_by_4_by_5_panel(tmp_path: Path) -> None:
    module = load_module()
    contract = module.read_yaml(module.DEFAULT_CONTRACT)

    manifest, design, schedule = module.build_manifest(contract, tmp_path)

    assert len(manifest["cells"]) == 60
    assert len(design) == 60
    assert len(schedule) == 300
    assert schedule["query_id"].nunique() == 15
    assert set(schedule["treatment"]) == set(module.TREATMENTS)
    assert manifest["execution_policy"]["order_policy"] == "explicit_schedule"
    assert manifest["execution_policy"][
        "preserve_instance_order_across_runtime_configs"
    ] is True
    assert manifest["execution_policy"]["result_signature_scope"] == (
        "first_repetition_per_condition"
    )
    assert contract["model_freeze"]["refit"] is False


def test_williams_schedule_covers_each_scenario_treatment_and_repeat() -> None:
    module = load_module()
    contract = module.read_yaml(module.DEFAULT_CONTRACT)
    scenarios = module.validate_contract(contract)

    entries, audit = module.build_williams_schedule(scenarios, 5, 202608071)

    assert len(entries) == 300
    counts = audit.groupby(["query_id", "treatment"])["repetition_index"].nunique()
    assert counts.eq(5).all()
    blocks = audit.groupby(["repetition_index", "scenario_position"])
    assert all(set(group["treatment"]) == set(module.TREATMENTS) for _, group in blocks)
    position_counts = audit.groupby(["treatment", "treatment_position"]).size()
    spreads = position_counts.groupby(level=0).agg(lambda values: values.max() - values.min())
    assert spreads.le(1).all()


def test_new_shapes_do_not_overlap_original_final_panel() -> None:
    module = load_module()
    contract = module.read_yaml(module.DEFAULT_CONTRACT)
    old = module.read_yaml(ROOT / "configs/validation/dba_local_memory_panel_v1.yml")

    new_shapes = {row["query_shape"] for row in module.validate_contract(contract)}
    old_shapes = {row["query_shape"] for row in old["scenarios"]}

    assert not new_shapes & old_shapes


def test_summary_keeps_abstention_out_of_top1_denominator() -> None:
    module = load_module()
    rows = pd.DataFrame(
        [
            {
                "mode": "frozen",
                "recommended_action": "",
                "top1_correct": False,
                "tie_aware_top1": False,
                "regret_log2": float("nan"),
                "nearest_distance": 3.0,
            },
            {
                "mode": "frozen",
                "recommended_action": "a",
                "top1_correct": True,
                "tie_aware_top1": True,
                "regret_log2": 0.0,
                "nearest_distance": 1.0,
            },
        ]
    )

    summary = module._summary(rows).iloc[0]

    assert summary["coverage"] == 0.5
    assert summary["strict_top1"] == 1.0
    assert summary["mean_regret_log2"] == 0.0


def test_partial_feedback_reveal_does_not_fabricate_unobserved_actions() -> None:
    module = load_module()
    outcomes = pd.DataFrame(
        [
            {
                "episode_id": "e1",
                "mitigation_action": action,
                "target_log2_gain": float(index),
            }
            for index, action in enumerate(module.ACTIONS)
        ]
    )

    revealed = outcomes[outcomes["mitigation_action"].eq(module.ACTIONS[1])]

    assert len(revealed) == 1
    assert set(revealed["mitigation_action"]) == {module.ACTIONS[1]}


def test_scenario_summary_preserves_strict_and_tie_aware_winners() -> None:
    module = load_module()
    outcomes = pd.DataFrame(
        [
            {
                "episode_id": "e1",
                "query_id": "q16",
                "mitigation_action": action,
                "target_log2_gain": gain,
                "tie_acceptable": action != module.ACTIONS[2],
                "winner_count_of_five": count,
            }
            for action, gain, count in zip(
                module.ACTIONS,
                (2.0, 1.98, 0.1),
                (4, 1, 0),
                strict=True,
            )
        ]
    )

    row = module._scenario_outcome_summary(outcomes).iloc[0]

    assert row["strict_best_action"] == module.ACTIONS[0]
    assert row["runner_up_action"] == module.ACTIONS[1]
    assert abs(row["winner_margin_log2"] - 0.02) < 1e-12
    assert row["strict_winner_repeat_count"] == 4
    assert row["tie_acceptable_actions"] == ",".join(sorted(module.ACTIONS[:2]))


def test_cluster_bootstrap_reports_coverage_and_recommendation_intervals() -> None:
    module = load_module()
    rows = pd.DataFrame(
        [
            {
                "mode": "frozen",
                "query_id": f"q{index}",
                "recommended_action": "" if index == 0 else "a",
                "top1_correct": index > 1,
                "tie_aware_top1": index > 1,
                "regret_log2": 0.0 if index > 1 else 1.0,
            }
            for index in range(4)
        ]
    )

    result = module._bootstrap_summary(rows, samples=100, seed=7).iloc[0]

    assert result["bootstrap_clusters"] == 4
    assert 0.0 <= result["coverage_ci_low"] <= result["coverage_ci_high"] <= 1.0
    assert 0.0 <= result["strict_top1_ci_low"] <= result["strict_top1_ci_high"] <= 1.0


def test_leakage_audit_accepts_reference_memory_without_sql_hash() -> None:
    module = load_module()
    events = pd.DataFrame(
        [{"episode_id": "e1", "query_id": "q16", "normalized_sql_hash": "new"}]
    )
    outcomes = pd.DataFrame(
        [
            {"episode_id": "e1", "mitigation_action": action}
            for action in module.ACTIONS
        ]
    )
    reference = pd.DataFrame([{"episode_id": "old", "query_id": "reference-s1"}])
    predictions = pd.DataFrame(
        [
            {
                "mode": "frozen_transfer",
                "episode_id": "e1",
                "memory_state_count": 1,
                "neighbors_json": (
                    '[{"query_id": "reference-s1", "action_gains": {}}]'
                ),
            }
        ]
    )

    audit = module._leakage_audit(
        events,
        outcomes,
        reference,
        predictions,
        ["elapsed_seconds", "edge_remote_bytes_sum"],
    )

    assert audit["status"] == "PASS"


def test_signature_component_identity_has_unique_execution_mapping() -> None:
    module = load_module()
    query_runs = pd.DataFrame(
        [
            {"query_run_id": "run-1", "result_signature_status": "completed"},
            {"query_run_id": "run-2", "result_signature_status": "completed"},
        ]
    )
    executions = pd.DataFrame(
        [
            {"query_run_id": "run-1", "component_match_id": "confirmatory_q16"},
            {"query_run_id": "run-2", "component_match_id": "confirmatory_q17"},
        ]
    )

    signatures = module._signature_rows(query_runs, executions)

    assert signatures["component_match_id"].tolist() == [
        "confirmatory_q16",
        "confirmatory_q17",
    ]


def test_hardware_snapshot_gate_accepts_one_stable_snapshot_per_attempt() -> None:
    module = load_module()
    rows = []
    for attempt in ("attempt-1", "attempt-2"):
        for index in range(10):
            rows.append(
                {
                    "database_sweep_id": attempt,
                    "hardware_snapshot_id": f"{attempt}-snapshot",
                    "node_name": f"node-{index}",
                    "hostname": f"host-{index}",
                    "kernel": "kernel",
                    "cpu_model": "cpu",
                    "logical_cpus": 1,
                    "physical_cores": 1,
                    "sockets": 1,
                    "cores_per_socket": 1,
                    "threads_per_core": 1,
                    "hypervisor_vendor": "vendor",
                    "ram_total_bytes": 1024,
                    "disk_count": 1,
                    "disk_total_bytes": 2048,
                    "storage_classes": "virtual",
                    "root_storage_class": "virtual",
                    "postgres_storage_class": "virtual",
                }
            )

    assert module._hardware_snapshots_are_attempt_scoped(pd.DataFrame(rows))
