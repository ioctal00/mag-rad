from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "analysis/scripts/agent/92_mitigation_modeling_decision.py"
    spec = importlib.util.spec_from_file_location("mitigation_modeling_decision", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summary_row(
    identifier: str,
    role: str,
    *,
    strict_pairs: int = 24,
    templates: int = 4,
    datasets: int = 3,
    median_speedup: float = 2.0,
) -> dict[str, object]:
    return {
        "identifier": identifier,
        "intervention_role": role,
        "strict_pair_count": strict_pairs,
        "stressed_template_count": templates,
        "dataset_count": datasets,
        "median_log2_gain": 1.0,
        "median_speedup": median_speedup,
    }


def test_decisions_keep_one_primary_model_and_explicit_negative_results() -> None:
    module = load_module()
    action_rows = [
        summary_row(
            "use_colocated_distribution",
            "positive_case",
            strict_pairs=75,
            templates=4,
            datasets=6,
            median_speedup=32.0,
        ),
        summary_row("mitigate_remote_path_bundle", "positive_case"),
        summary_row(
            "disperse_hot_shards", "positive_case", strict_pairs=49, median_speedup=1.0
        ),
        summary_row(
            "increase_regional_work_mem",
            "positive_case",
            strict_pairs=54,
            median_speedup=1.05,
        ),
        summary_row(
            "increase_gac_work_mem",
            "positive_case",
            strict_pairs=15,
            templates=1,
            median_speedup=1.08,
        ),
    ]
    policy_rows = [
        summary_row(
            "gac_regional_reduction",
            "positive_case",
            strict_pairs=60,
            templates=4,
        ),
        summary_row(
            "remote_transport_calibration",
            "calibration",
            strict_pairs=45,
            templates=5,
            datasets=2,
        ),
    ]
    actions = pd.DataFrame(action_rows).rename(columns={"identifier": "mitigation_action"})
    policies = pd.DataFrame(policy_rows).rename(columns={"identifier": "policy_id"})

    decisions = module.build_decisions(
        actions,
        policies,
        {
            "gate": "MIXED_MODEL_EVIDENCE",
            "mitigation_action": "use_colocated_distribution",
        },
    ).set_index("entity_id")

    assert decisions.loc["use_colocated_distribution", "category"] == (
        "primary_predictive_result"
    )
    assert decisions.loc["use_colocated_distribution", "model_status"] == (
        "MIXED_MODEL_EVIDENCE"
    )
    assert decisions.loc["mitigate_remote_path_bundle", "model_status"] == (
        "model_deferred"
    )
    assert decisions.loc["gac_regional_reduction", "category"] == (
        "deterministically_routed_policy"
    )
    assert decisions.loc["disperse_hot_shards", "category"] == (
        "negative_end_to_end_result"
    )
    assert decisions.loc["increase_regional_work_mem", "category"] == (
        "negative_end_to_end_result"
    )
