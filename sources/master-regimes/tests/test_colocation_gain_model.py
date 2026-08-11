from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "analysis/scripts/agent/91_colocation_gain_model.py"
    spec = importlib.util.spec_from_file_location("colocation_gain_model", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_contract():
    return yaml.safe_load(
        (ROOT / "configs/models/colocation_gain_v1.yml").read_text(encoding="utf-8")
    )


def test_feature_contract_excludes_identity_and_target_fields() -> None:
    module = load_module()
    names = module.feature_names(load_contract())

    assert "template_id" not in names
    assert "dataset_profile_id" not in names
    assert not any("target_" in name for name in names)
    assert len(names) == 19


def test_pair_matrix_uses_only_stressed_repetitions_and_median() -> None:
    module = load_module()
    contract = load_contract()
    names = module.feature_names(contract)
    training_rows = []
    execution_rows = []
    for variant in ("stressed", "mitigated"):
        for repetition in range(3):
            query_run_id = f"{variant}-{repetition}"
            training_rows.append(
                {
                    "pair_id": "pair-1",
                    "query_run_id": query_run_id,
                    "variant": variant,
                    "template_id": "template-a",
                    "dataset_profile_id": "dataset-a",
                    "scenario_level": "broad",
                    "dataset_size_class": "small",
                }
            )
            row = {"query_run_id": query_run_id}
            row.update(
                {
                    name: (repetition + 1 if variant == "stressed" else 1000)
                    for name in names
                }
            )
            execution_rows.append(row)
    pairs = pd.DataFrame(
        [
            {
                "pair_id": "pair-1",
                "mitigation_action": "use_colocated_distribution",
                "intervention_role": "positive_case",
                "strict_gain_eligible": True,
                "stressed_template_id": "template-a",
                "dataset_profile_id": "dataset-a",
                "logical_question_id": "question-a",
                "target_log2_gain_median": 2.0,
                "correctness_recovery_applied": False,
            }
        ]
    )

    result = module.build_pair_matrix(
        pd.DataFrame(training_rows),
        pd.DataFrame(execution_rows),
        pairs,
        contract,
    ).iloc[0]

    assert result["coordinator_non_foreign_time_share_proxy"] == 2.0
    assert result["coordinator_fanin_rows"] == pytest.approx(2.0)
    assert result["target_log2_gain"] == 2.0
    assert result["scenario_level"] == "broad"
    assert result["dataset_size_class"] == "small"
