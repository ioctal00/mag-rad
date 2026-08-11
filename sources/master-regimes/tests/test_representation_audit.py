from __future__ import annotations

import numpy as np
import pandas as pd

from master_regimes.representation_audit import (
    fit_fcm,
    memberships_from_centers,
    semantic_transform,
)


def _contract() -> dict[str, object]:
    return {
        "features": {
            "share": {
                "family": "flow",
                "transform": "bounded_share",
                "neutral": 0.0,
            },
            "ratio": {
                "family": "flow",
                "transform": "nonnegative_log_atan",
                "neutral": 0.0,
            },
            "isf": {
                "family": "skew",
                "transform": "isf_excess_share",
                "support_columns": ["count"],
                "neutral": 0.0,
            },
            "task_isf": {
                "family": "skew",
                "transform": "positive_excess_log_atan",
                "neutral": 0.0,
            },
            "max_share": {
                "family": "skew",
                "transform": "max_share_excess",
                "support_columns": ["count"],
                "neutral": 0.0,
                "drop_as_redundant": True,
                "redundant_with": "isf",
            },
        }
    }


def test_semantic_transform_bounds_and_removes_redundant_input() -> None:
    raw = pd.DataFrame(
        {
            "query_run_id": ["a", "b"],
            "share": [1.2, np.nan],
            "ratio": [1000.0, 0.0],
            "isf": [2.0, 1.0],
            "task_isf": [4.0, 1.0],
            "max_share": [0.5, 0.25],
        }
    )
    support = pd.DataFrame(
        {
            "query_run_id": ["a", "b"],
            "count": [4.0, 4.0],
        }
    )

    transformed, weighted, audit = semantic_transform(raw, support, _contract())

    assert transformed["share"].tolist() == [1.0, 0.0]
    assert transformed["ratio"].between(0.0, 1.0).all()
    assert np.isclose(transformed.loc[0, "isf"], 1.0 / 3.0)
    assert 0.0 < transformed.loc[0, "task_isf"] < 1.0
    assert transformed.loc[1, "task_isf"] == 0.0
    assert np.isclose(transformed.loc[0, "max_share"], 1.0 / 3.0)
    assert "max_share" not in weighted
    assert audit.set_index("feature").loc["max_share", "dropped_as_redundant"]


def test_fcm_projection_memberships_sum_to_one() -> None:
    values = np.array([[0.0, 0.0], [0.1, 0.0], [0.9, 1.0], [1.0, 1.0]])
    fit = fit_fcm(values, k=2, seed=0)
    memberships, distances = memberships_from_centers(
        values,
        fit.centers,
        fuzzifier=1.7,
    )

    assert fit.converged
    assert np.allclose(memberships.sum(axis=1), 1.0)
    assert distances.shape == (4, 2)
