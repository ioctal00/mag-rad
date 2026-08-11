from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "analysis/scripts/agent/64_semantic_v2_final_consistency.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("semantic_v2_consistency", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_mcnemar_matches_five_to_zero_discordant_pairs() -> None:
    module = load_module()

    assert module.exact_mcnemar_two_sided(5, 0) == 0.0625
    assert module.exact_mcnemar_two_sided(0, 0) == 1.0


def test_membership_frame_preserves_fuzzy_probabilities() -> None:
    module = load_module()
    memberships = np.array(
        [
            [0.7, 0.2, 0.05, 0.05],
            [0.25, 0.25, 0.25, 0.25],
        ]
    )
    distances = np.array(
        [
            [0.1, 0.4, 0.8, 0.9],
            [0.5, 0.5, 0.5, 0.5],
        ]
    )

    frame = module.membership_frame(
        pd.Series(["run-a", "run-b"]),
        memberships,
        distances,
    )

    assert frame["dominant_cluster"].tolist() == [0, 0]
    assert frame["max_membership"].tolist() == [0.7, 0.25]
    assert frame["nearest_center_distance"].tolist() == [0.1, 0.5]
    assert np.isclose(frame.loc[1, "membership_entropy_normalized"], 1.0)


def test_pairwise_condition_metrics_detects_stable_cluster() -> None:
    module = load_module()
    frame = pd.DataFrame(
        {
            "f1": [0.0, 0.1, 0.0],
            "membership_c0": [0.8, 0.7, 0.75],
            "membership_c1": [0.1, 0.2, 0.15],
            "membership_c2": [0.05, 0.05, 0.05],
            "membership_c3": [0.05, 0.05, 0.05],
        }
    )

    result = module.pairwise_condition_metrics(frame, ["f1"])

    assert result["dominant_cluster_agreement"] == 1.0
    assert result["max_pairwise_feature_l2"] == 0.1
    assert result["mean_pairwise_membership_l1"] > 0
