from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "analysis/scripts/agent/88_mitigation_action_audit.py"
    spec = importlib.util.spec_from_file_location("mitigation_action_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_contract():
    path = ROOT / "configs/validation/mitigation_action_audit_v1.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def execution_pair() -> pd.DataFrame:
    rows = []
    for variant, template, runtime, work_mem in (
        ("stressed", "gac-memory", "low-memory", "64kB"),
        ("mitigated", "gac-memory", "high-memory", "256MB"),
    ):
        for repetition in range(3):
            rows.append(
                {
                    "pair_id": "pair-1",
                    "variant": variant,
                    "mitigation_action": "increase_gac_work_mem",
                    "pressure_axis": "gac_finalization",
                    "intervention_role": "positive_case",
                    "template_id": template,
                    "logical_question_id": "memory-question",
                    "dataset_profile_id": "dataset-v1",
                    "dataset_size_class": "small",
                    "condition_id": f"condition-{variant}",
                    "runtime_config_id": runtime,
                    "work_mem": work_mem,
                    "target_scope": "",
                    "coordinator_node": "eu-analytics-1",
                    "execution_strategy": "multiregion_union",
                    "repetition_index": str(repetition),
                }
            )
    return pd.DataFrame(rows)


def test_pair_design_infers_global_scope_and_observes_action_change() -> None:
    module = load_module()
    result = module.build_pair_design(execution_pair()).iloc[0]

    assert result["target_scope_canonical"] == "global_query"
    assert result["target_scope_source"] == "inferred_from_gac_execution"
    assert result["stressed_execution_count"] == 3
    assert result["mitigated_execution_count"] == 3
    assert set(result["changed_fields"].split("|")) == {
        "runtime_config_id",
        "work_mem",
    }


def test_pair_audit_keeps_result_and_action_contracts_separate() -> None:
    module = load_module()
    contract = load_contract()
    pair_design = module.build_pair_design(execution_pair())
    pair_summary = pd.DataFrame(
        [
            {
                "pair_id": "pair-1",
                "pressure_axis": "gac_finalization",
                "intervention_role": "positive_case",
                "target_metric": "global_gac_mitigation_gain_log2",
                "repeat_count": 3,
                "complete_repeat_count": 3,
                "elapsed_ratio_median": 2.0,
                "elapsed_ratio_min": 1.9,
                "elapsed_ratio_max": 2.1,
                "target_log2_gain_median": 1.0,
                "target_log2_gain_std": 0.05,
                "positive_repeat_share": 1.0,
                "result_equivalence_status": "exact_multiset",
                "same_row_count": True,
                "exact_multiset_hash": True,
            }
        ]
    )
    result = module.build_pair_audit(
        pair_design,
        pair_summary,
        module.action_contract_frame(contract),
        contract,
    ).iloc[0]

    assert result["gain_pair_status"] == "strict_eligible"
    assert bool(result["strict_gain_eligible"])
    assert result["change_contract_status"] == "ok_expected_change"
    assert result["policy_id"] == "gac_memory"


def test_correctness_recovery_promotes_review_pair_and_keeps_provenance() -> None:
    module = load_module()
    contract = load_contract()
    pairs = pd.DataFrame(
        [
            {
                "pair_id": "pair-1",
                "policy_id": "remote_transport_bundle",
                "mitigation_action": "mitigate_remote_path_bundle",
                "result_equivalence_status": "same_row_count_hash_diff_review",
                "gain_pair_status": "review_only",
                "strict_gain_eligible": False,
                "review_gain_eligible": True,
            }
        ]
    )
    recovery = pd.DataFrame(
        [
            {
                "pair_id": "pair-1",
                "correctness_recovery_status": "tolerance_equivalent",
            }
        ]
    )

    result = module.apply_correctness_recovery(pairs, recovery, contract).iloc[0]

    assert result["original_result_equivalence_status"] == (
        "same_row_count_hash_diff_review"
    )
    assert result["result_equivalence_status"] == "recovery_tolerance_equivalent"
    assert result["gain_pair_status"] == "strict_eligible"
    assert bool(result["strict_gain_eligible"])
    assert bool(result["correctness_recovery_applied"])


def test_policy_template_holdout_marks_only_same_role_action_confounding() -> None:
    module = load_module()
    contract = load_contract()
    rows = []
    for policy_id, role, actions in (
        ("gac_regional_reduction", "positive_case", ("a1", "a2", "a3")),
        ("repartition_colocation", "positive_case", ("colocated",)),
    ):
        for action_index, action in enumerate(actions):
            for pair_index in range(2):
                rows.append(
                    {
                        "policy_id": policy_id,
                        "intervention_role": role,
                        "mitigation_action": action,
                        "stressed_template_id": f"template-{action_index}",
                        "logical_question_id": f"question-{action_index}",
                        "dataset_profile_id": f"dataset-{pair_index}",
                        "dataset_size_class": f"size-{pair_index}",
                        "strict_gain_eligible": True,
                    }
                )
    result = module.build_holdout_feasibility(pd.DataFrame(rows), contract)
    template_rows = result[
        result["entity_type"].eq("policy")
        & result["holdout_type"].eq("leave_stressed_template_out")
    ].set_index("entity_id")

    assert (
        template_rows.loc["gac_regional_reduction", "holdout_status"]
        == "structurally_feasible_action_confounded"
    )
    assert template_rows.loc["repartition_colocation", "holdout_status"] == "not_feasible"
