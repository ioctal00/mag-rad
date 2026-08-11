from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis/scripts/agent/105_representation_ablation_e1_e4.py"


def load_module():
    specification = importlib.util.spec_from_file_location(
        "representation_ablation_e1_e4_105", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_contract_freezes_e1_e4_and_common_policy() -> None:
    module = load_module()
    contract = module.read_yaml(module.DEFAULT_CONTRACT)
    base = module.read_yaml(
        module.resolve_input(contract["inputs"]["base_ablation_contract"])
    )

    module.validate_contract(contract, base)

    assert set(contract["evaluations"]) == {"E1", "E2", "E3", "E4"}
    assert contract["policy"]["neighbors"] == 5
    assert contract["policy"]["exclude_same_query_id"]
    assert contract["policy"]["exclude_same_logical_identity"]


def test_frozen_transformer_applies_saved_pipeline_without_fit() -> None:
    module = load_module()

    class Memory:
        @staticmethod
        def transform_values(frame, _specifications, prefix):
            return pd.DataFrame(
                {
                    "x": pd.to_numeric(frame[f"{prefix}x"], errors="coerce"),
                    "y": pd.to_numeric(frame[f"{prefix}y"], errors="coerce"),
                }
            )

    artifact = {
        "active_features": ["x", "y"],
        "imputer_statistics": [2.0, 3.0],
        "scaler_mean": [1.0, 1.0],
        "scaler_scale": [2.0, 4.0],
        "family_weights": [1.0, 0.5],
        "pca_mean": [0.0, 0.0],
        "pca_components": [[1.0, 0.0], [0.0, 1.0]],
    }
    transformer = module.FrozenFullTransformer(
        {"x": {}, "y": {}}, artifact, Memory
    )
    frame = pd.DataFrame([{"before__x": np.nan, "before__y": 9.0}])

    result = transformer.transform(frame)

    assert np.allclose(result, [[0.5, 1.0]])


def test_summary_keeps_abstentions_out_of_top1_denominator() -> None:
    module = load_module()
    results = pd.DataFrame(
        [
            {
                "evaluation": "E1",
                "representation": "R1_sql_structural",
                "predicted_action": "action",
                "top1_correct": True,
                "regret_log2": 0.0,
                "nearest_distance": 1.0,
                "coverage_threshold": 2.0,
            },
            {
                "evaluation": "E1",
                "representation": "R1_sql_structural",
                "predicted_action": "",
                "top1_correct": False,
                "regret_log2": np.nan,
                "nearest_distance": 3.0,
                "coverage_threshold": 2.0,
            },
        ]
    )

    row = module.summarize_results(results).iloc[0]

    assert row["coverage"] == 0.5
    assert row["recommendation_count"] == 1
    assert row["abstention_count"] == 1
    assert row["top1_accuracy"] == 1.0


def test_rank_disagreement_is_zero_for_same_order_and_one_for_reverse() -> None:
    module = load_module()
    ascending = np.asarray([1.0, 2.0, 3.0])

    assert module._rank_disagreement(ascending, ascending) == 0.0
    assert module._rank_disagreement(ascending, ascending[::-1]) == 1.0


def test_logical_identity_prefers_cross_topology_hash() -> None:
    module = load_module()
    frame = pd.DataFrame(
        [
            {
                "logical_query_hash": "logical",
                "normalized_sql_hash": "physical-n3-sql",
            }
        ]
    )

    assert module._logical_identity(frame).tolist() == ["logical"]


def test_json_safe_replaces_non_finite_values() -> None:
    module = load_module()
    value = {
        "nan": float("nan"),
        "positive_infinity": float("inf"),
        "nested": [np.float64("-inf"), np.float64(1.25)],
    }

    result = module._json_safe(value)

    assert result == {
        "nan": None,
        "positive_infinity": None,
        "nested": [None, 1.25],
    }
    json.dumps(result, allow_nan=False)
