from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis/scripts/agent/114_temporal_validity_audit.py"


def load_module():
    spec = importlib.util.spec_from_file_location("temporal_validity_audit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sql_temporal_classifier_distinguishes_effective_anchor() -> None:
    audit = load_module()
    assert (
        audit.classify_sql(
            "SELECT COALESCE(to_timestamp(nullif(1782864000, 0)), now())"
        )
        == "fixed_as_of"
    )
    assert audit.classify_sql("SELECT current_date") == "dynamic_current_date"
    assert audit.classify_sql("SELECT now()") == "dynamic_now"
    assert (
        audit.classify_sql("SELECT * FROM t WHERE ts >= timestamptz '2026-06-01'")
        == "fixed_literal"
    )
    assert audit.classify_sql("SELECT count(*) FROM t") == "no_wall_clock"


def test_archived_temporal_audit_preserves_claim_boundaries(tmp_path: Path) -> None:
    audit = load_module()
    final_repo = ROOT.parent / "master-thesis-final"
    payload = audit.build(final_repo, tmp_path)

    pressure = payload["wide_intervention_program"]
    assert pressure["execution_count"] == 2607
    assert pressure["condition_count"] == 869
    assert pressure["pair_count"] == 418
    assert pressure["dynamic_empty_negative_control_pairs"] == 21
    assert pressure["substantive_frozen_or_time_independent_pairs"] == 397

    f21 = payload["legacy_fcm_corpus"]
    assert f21["execution_count"] == 1964
    assert f21["model_refit_performed"] is False
    assert f21["current_date_queries_stayed_on_generation_utc_date"] is True
    assert f21["hard_cluster_vs_within_sweep_time_quartile_nmi"] < 0.01
    assert f21["f19_hard_cluster_vs_within_sweep_time_quartile_nmi"] < 0.01

    assert payload["live_sql_executed"] is False
    assert payload["dataset_regenerated"] is False
    assert payload["model_refit_performed"] is False
    assert (tmp_path / "checksums.sha256").is_file()
