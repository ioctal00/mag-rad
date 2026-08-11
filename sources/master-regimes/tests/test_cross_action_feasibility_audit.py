from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "analysis/scripts/agent/98_cross_action_feasibility_audit.py"
    spec = importlib.util.spec_from_file_location("cross_action_feasibility", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pair_rows() -> pd.DataFrame:
    common = {
        "gain_pair_status": "strict_eligible",
        "logical_question_id": "question-a",
        "dataset_profile_id": "dataset-a",
        "dataset_size_class": "small",
        "target_log2_gain_median": 1.0,
        "topology_id": "n2",
        "execution_scope": "gac",
        "stressed_template_id": "template-a",
    }
    return pd.DataFrame(
        [
            {
                **common,
                "pair_id": "pair-a",
                "mitigation_action": "action-a",
                "stressed_config_json": '{"runtime":"a"}',
            },
            {
                **common,
                "pair_id": "pair-b",
                "mitigation_action": "action-b",
                "stressed_config_json": '{"runtime":"b"}',
            },
        ]
    )


def stressed_context() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pair_id": "pair-a",
                "logical_question_id": "question-a",
                "dataset_profile_id": "dataset-a",
                "dataset_size_class": "small",
                "param_json": "{}",
                "topology_id": "n2",
                "execution_scope": "gac",
                "stressed_template_id_observed": "template-a",
            },
            {
                "pair_id": "pair-b",
                "logical_question_id": "question-a",
                "dataset_profile_id": "dataset-a",
                "dataset_size_class": "small",
                "param_json": "{}",
                "topology_id": "n2",
                "execution_scope": "gac",
                "stressed_template_id_observed": "template-a",
            },
        ]
    )


def contract() -> dict:
    return {
        "inputs": {"required_gain_pair_status": "strict_eligible"},
        "scenario_identity": {
            "exact_fields": [
                "logical_question_id",
                "dataset_profile_id",
                "param_json",
                "stressed_config_json",
            ],
            "semantic_fields": [
                "logical_question_id",
                "dataset_profile_id",
                "param_json",
            ],
        },
    }


def test_different_stressed_configs_share_semantics_but_not_exact_baseline() -> None:
    module = load_module()
    result = module.attach_scenario_ids(pair_rows(), stressed_context(), contract())

    assert result["semantic_scenario_id"].nunique() == 1
    assert result["exact_scenario_id"].nunique() == 2


def test_action_matrix_does_not_claim_ranking_without_shared_baseline() -> None:
    module = load_module()
    pairs = module.attach_scenario_ids(pair_rows(), stressed_context(), contract())
    actions = pd.DataFrame(
        [
            {"mitigation_action": "action-a", "action_kind": "deployable_action"},
            {"mitigation_action": "action-b", "action_kind": "deployable_action"},
            {"mitigation_action": "action-c", "action_kind": "policy_member"},
        ]
    )

    matrix = module.build_action_matrix(pairs, actions).set_index("mitigation_action")

    assert matrix.loc["action-a", "status"] == "tested"
    assert matrix.loc["action-b", "status"] == "tested"
    assert matrix.loc["action-c", "status"] == "semantic_rewrite_unavailable"
    assert not bool(matrix["ranking_comparable"].any())
