from __future__ import annotations

import numpy as np
import pandas as pd

from master_regimes.frozen_projection import (
    display_state,
    fuzzy_memberships,
    project_to_frozen_model,
)


def test_fuzzy_memberships_sum_to_one() -> None:
    values = np.array([[0.0, 0.0], [1.0, 1.0]])
    centers = np.array([[0.0, 0.0], [2.0, 2.0]])

    memberships, distances = fuzzy_memberships(
        values,
        centers,
        fuzzifier=1.7,
    )

    assert memberships.shape == distances.shape == (2, 2)
    assert np.allclose(memberships.sum(axis=1), 1.0)
    assert memberships[0, 0] > memberships[0, 1]


def test_display_state_uses_locked_thresholds() -> None:
    assert display_state(0.60, 0.20, 0.80) == "clear_prototype"
    assert display_state(0.45, 0.10, 1.10) == "mixed_boundary"
    assert display_state(0.30, 0.05, 1.20) == "weak_prototype_coverage"


def test_project_to_frozen_model_uses_saved_contract_and_centers(tmp_path) -> None:
    preprocessing = tmp_path / "preprocessing.csv"
    centers = tmp_path / "centers.csv"
    baseline = tmp_path / "baseline.csv"
    pd.DataFrame(
        [
            {
                "matrix": "locked",
                "feature": "feature_a",
                "status": "kept",
                "transform": "identity",
                "center": 0.0,
                "scale": 1.0,
            }
        ]
    ).to_csv(preprocessing, index=False)
    pd.DataFrame(
        [
            {"k": 2, "seed": 0, "cluster": 0, "feature_a": 0.0},
            {"k": 2, "seed": 0, "cluster": 1, "feature_a": 10.0},
        ]
    ).to_csv(centers, index=False)
    pd.DataFrame(
        [
            {"query_run_id": "b0", "feature_a": 0.0},
            {"query_run_id": "b1", "feature_a": 10.0},
        ]
    ).to_csv(baseline, index=False)
    raw = pd.DataFrame(
        [{"query_run_id": "q1", "feature_a": 1.0}]
    )

    scaled, projection, quality = project_to_frozen_model(
        raw,
        preprocessing_report=preprocessing,
        centers_file=centers,
        baseline_scaled_file=baseline,
        matrix_name="locked",
        k=2,
        seed=0,
        fuzzifier=1.7,
    )

    assert scaled.loc[0, "feature_a"] == 1.0
    assert projection.loc[0, "hard_cluster"] == 0
    assert projection.loc[0, "membership_c0"] > 0.99
    assert quality.loc[0, "missing_count"] == 0
