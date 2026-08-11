import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from master_regimes.config import load_yaml

ROOT = Path(__file__).resolve().parents[1]
FREEZE_DIR = ROOT / "analysis/reports/semantic-v2-model-freeze"
HOLDOUT_DIR = ROOT / "analysis/reports/stats-ceb-semantic-v2b-holdout"


def _require_report_artifacts(*paths: Path) -> None:
    if missing := [path for path in paths if not path.exists()]:
        pytest.skip(
            "optional archived report artifacts are not restored: "
            + ", ".join(path.name for path in missing)
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_semantic_v2_p99_contract_matches_frozen_training_distances() -> None:
    manifest_path = FREEZE_DIR / "semantic_v2_model_manifest.yml"
    memberships_path = FREEZE_DIR / "baseline_memberships_k4.csv"
    _require_report_artifacts(manifest_path, memberships_path)
    manifest = load_yaml(manifest_path)
    coverage = manifest["coverage_reference"]
    assert coverage == {
        "interpretation": "empirical_training_coverage_not_formal_ood_detector",
        "distance": "euclidean_distance_to_nearest_fcm_center",
        "threshold_scope": "one_global_threshold_per_representation",
        "quantile": 0.99,
        "quantile_method": "linear",
        "reference_rows": 1964,
        "reference_scope": "clean_run_v1_training_corpus",
        "frozen_before_external_projection": True,
    }

    memberships = pd.read_csv(memberships_path)
    expected = float(
        np.quantile(
            memberships["nearest_center_distance"].to_numpy(dtype=float),
            0.99,
            method="linear",
        )
    )
    actual = float(manifest["models"]["k4"]["ood_p99_threshold"])
    assert np.isclose(actual, expected, rtol=0.0, atol=1.0e-15)


def test_semantic_v2_family_weighting_name_matches_implemented_rule() -> None:
    contract = load_yaml(
        ROOT / "configs/features/feature_semantic_contract_v2.yml"
    )
    manifest_path = FREEZE_DIR / "semantic_v2_model_manifest.yml"
    _require_report_artifacts(manifest_path)
    manifest = load_yaml(manifest_path)
    assert contract["family_weighting"] == "inverse_sqrt_feature_count"
    assert manifest["family_weighting"] == "inverse_sqrt_feature_count"


def test_finalization_refreeze_preserves_holdout_projection_bytes() -> None:
    equivalence_path = FREEZE_DIR / "finalization_refreeze_equivalence.json"
    summary_path = HOLDOUT_DIR / "holdout_summary.json"
    _require_report_artifacts(equivalence_path, summary_path)
    audit = json.loads(
        equivalence_path.read_text()
    )
    holdout_summary = json.loads(summary_path.read_text())

    assert audit["model_refit_performed"] is False
    assert (
        audit["current_feature_contract_sha256"]
        == holdout_summary["feature_contract_sha256"]
    )
    assert (
        audit["current_model_manifest_sha256"]
        == holdout_summary["model_manifest_sha256"]
    )
    for filename, expected in audit["byte_identical_outputs"].items():
        assert _sha256(HOLDOUT_DIR / filename) == expected
