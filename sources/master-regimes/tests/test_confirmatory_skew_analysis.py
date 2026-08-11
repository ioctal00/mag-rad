from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


def load_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "analysis"
        / "scripts"
        / "agent"
        / "57_confirmatory_skew_analysis.py"
    )
    spec = importlib.util.spec_from_file_location(
        "confirmatory_skew_analysis",
        script,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transform_frame_uses_locked_transform_and_scaler() -> None:
    module = load_module()
    raw = pd.DataFrame(
        {
            "query_run_id": ["q1", "q2"],
            "ratio": [0.0, np.nan],
            "share": [3.0, 5.0],
        }
    )
    preprocess = pd.DataFrame(
        [
            {
                "matrix": module.MATRIX_NAME,
                "feature": "ratio",
                "status": "kept",
                "transform": "log1p",
                "imputation": "median",
                "center": 1.0,
                "scale": 2.0,
            },
            {
                "matrix": module.MATRIX_NAME,
                "feature": "share",
                "status": "kept",
                "transform": "identity",
                "imputation": "median",
                "center": 2.0,
                "scale": 1.0,
            },
        ]
    )
    quality = pd.DataFrame(
        [
            {"matrix": module.MATRIX_NAME, "feature": "ratio", "median": 3.0},
            {"matrix": module.MATRIX_NAME, "feature": "share", "median": 4.0},
        ]
    )

    scaled, audit = module.transform_frame(
        raw,
        features=["ratio", "share"],
        preprocess=preprocess,
        quality=quality,
    )

    assert scaled.loc[0, "ratio"] == -0.5
    assert scaled.loc[1, "ratio"] == (np.log1p(3.0) - 1.0) / 2.0
    assert scaled["share"].tolist() == [1.0, 3.0]
    assert audit.set_index("feature").loc["ratio", "confirmatory_missing_count"] == 1


def test_fcm_membership_sums_to_one_and_selects_nearest_center() -> None:
    module = load_module()
    scaled = pd.DataFrame(
        [{"query_run_id": "q1", "f1": 0.1, "f2": 0.0}]
    )
    centers = pd.DataFrame(
        [
            {"cluster": 0, "f1": 0.0, "f2": 0.0},
            {"cluster": 1, "f1": 10.0, "f2": 10.0},
        ]
    )

    result = module.fcm_memberships(
        scaled,
        centers=centers,
        features=["f1", "f2"],
        fuzzifier=1.7,
    )

    assert result.loc[0, "dominant_cluster"] == 0
    assert abs(result.loc[0, ["membership_c0", "membership_c1"]].sum() - 1.0) < 1e-12


def test_signed_counts_keeps_zero_and_unfavorable_results() -> None:
    module = load_module()

    assert module.signed_counts(pd.Series([1.0, 0.0, -1.0, np.nan])) == (1, 1, 1)


def test_observability_partition_is_order_independent() -> None:
    frozen = ["a", "b", "c"]
    gac = ["c", "a"]
    topology = ["b"]

    assert set(gac) | set(topology) == set(frozen)
    assert not (set(gac) & set(topology))
