import pandas as pd

from master_regimes.repeatability_analysis import (
    feature_stability,
    fingerprint_stability,
    prepare_attempt_frame,
    resolve_attempts,
    write_repeatability_report,
)


def test_resolver_preserves_timeout_but_uses_completed_retry() -> None:
    attempts = pd.DataFrame(
        [
            {
                "condition_id": "c1",
                "repetition_index": 0,
                "attempt_number": 1,
                "execution_status": "timeout",
                "value": 1,
            },
            {
                "condition_id": "c1",
                "repetition_index": 0,
                "attempt_number": 2,
                "execution_status": "completed",
                "value": 2,
            },
        ]
    )
    resolved = resolve_attempts(attempts)
    assert len(resolved) == 1
    assert resolved.iloc[0]["attempt_number"] == 2
    assert len(attempts) == 2


def test_feature_stability_uses_median_and_mad() -> None:
    frame = pd.DataFrame(
        [
            {"condition_id": "c1", "feature_a": 9.0},
            {"condition_id": "c1", "feature_a": 10.0},
            {"condition_id": "c1", "feature_a": 100.0},
        ]
    )
    result = feature_stability(frame)
    row = result[result["feature"].eq("feature_a")].iloc[0]
    assert row["median"] == 10.0
    assert row["mad"] == 1.0


def test_feature_stability_accepts_locked_feature_list() -> None:
    frame = pd.DataFrame(
        [
            {"condition_id": "c1", "feature_a": 1.0, "diagnostic": 100.0},
            {"condition_id": "c1", "feature_a": 2.0, "diagnostic": 200.0},
        ]
    )

    result = feature_stability(frame, feature_columns=["feature_a"])

    assert result["feature"].tolist() == ["feature_a"]


def test_prepare_attempt_frame_preserves_repetition_and_retry_identity() -> None:
    attempts = pd.DataFrame(
        [
            {
                "query_run_id": "q-timeout",
                "condition_id": "c1",
                "repetition_index": 0,
                "run_order": 1,
                "attempt_number": 1,
                "execution_status": "timeout",
            },
            {
                "query_run_id": "q-complete",
                "condition_id": "c1",
                "repetition_index": 0,
                "run_order": 1,
                "attempt_number": 2,
                "execution_status": "completed",
            },
        ]
    )
    query_runs = pd.DataFrame(
        [
            {
                "query_run_id": "q-complete",
                "plan_fingerprint": "fp1",
                "condition_id": "c1",
                "repetition_index": 0,
                "run_order": 1,
            }
        ]
    )
    raw = pd.DataFrame([{"query_run_id": "q-complete", "feature_a": 1.0}])
    projection = pd.DataFrame(
        [
            {
                "query_run_id": "q-complete",
                "hard_cluster": 1,
                "membership_c0": 0.1,
                "membership_c1": 0.7,
                "membership_c2": 0.1,
                "membership_c3": 0.1,
                "display_state": "clear_prototype",
            }
        ]
    )
    evidence = pd.DataFrame(
        [
            {
                "query_run_id": "q-complete",
                "evidence_completeness": 1.0,
                "missing_region_count": 0,
                "unexpected_region_count": 0,
                "region_identity_duplicate_rows": 0,
                "remote_sql_slot_duplicate_rows": 0,
                "worker_identity_duplicate_rows": 0,
                "plan_identity_duplicate_rows": 0,
            }
        ]
    )
    selection = pd.DataFrame(
        [{"condition_id": "c1", "source_query_run_id": "source-q"}]
    )

    frame = prepare_attempt_frame(
        attempts,
        query_runs,
        raw,
        projection,
        evidence,
        selection,
    )
    resolved = resolve_attempts(frame)

    assert len(frame) == 2
    assert resolved.iloc[0]["query_run_id"] == "q-complete"
    assert resolved.iloc[0]["source_query_run_id"] == "source-q"
    assert resolved.iloc[0]["main_plan_fingerprint"] == "fp1"


def test_fingerprint_stability_does_not_count_missing_fingerprint() -> None:
    resolved = pd.DataFrame(
        [
            {"condition_id": "c1", "main_plan_fingerprint": ""},
            {"condition_id": "c1", "main_plan_fingerprint": None},
        ]
    )

    result = fingerprint_stability(resolved)

    assert result.iloc[0]["fingerprint_count"] == 0
    assert result.iloc[0]["dominant_fingerprint"] == ""


def _report_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "condition_id": "c1",
                "repetition_index": repetition,
                "attempt_number": 1,
                "execution_status": "completed",
                "evidence_completeness": 1.0,
                "ambiguous_candidate_count": 0,
                "missing_applicable_evidence_count": 0,
                "main_plan_fingerprint": "fp1",
                "display_state": "mixed_boundary",
                "membership_c0": 0.4,
                "membership_c1": 0.3,
                "membership_c2": 0.2,
                "membership_c3": 0.1,
                "feature_a": 2.0,
                "elapsed_seconds": 1.0 + repetition * 0.1,
                "main_root_actual_total_time_ms": 900.0 + repetition,
                "execution_strategy": "fdw_raw",
                "dataset_profile_id": "dataset-a",
                "runtime_config_id": "default",
                "template_id": "template-a",
            }
            for repetition in range(3)
        ]
    )


def test_real_report_omits_synthetic_fixture_warning(tmp_path) -> None:
    manifest = write_repeatability_report(
        _report_fixture(),
        out_dir=tmp_path,
        manifest_extra={
            "synthetic_fixture": False,
            "collector_unresolved_issue_count": 0,
        },
        feature_columns=["feature_a"],
    )

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert manifest["synthetic_fixture"] is False
    assert "Namjerno ubačeni" not in readme
    assert "Nisu pronađeni nerazriješeni collector problemi." in readme
    assert "Runtime se prikazuje kao odvojeni audit" in readme


def test_synthetic_report_preserves_fixture_warning(tmp_path) -> None:
    write_repeatability_report(
        _report_fixture(),
        out_dir=tmp_path,
        manifest_extra={"synthetic_fixture": True},
        feature_columns=["feature_a"],
    )

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Namjerno ubačeni missing/duplicate/fingerprint-drift" in readme


def test_report_writes_canonical_summary_outputs(tmp_path) -> None:
    write_repeatability_report(
        _report_fixture(),
        out_dir=tmp_path,
        feature_columns=["feature_a"],
    )

    summary = pd.read_csv(tmp_path / "repeatability_summary.csv")
    conditions = pd.read_csv(tmp_path / "condition_repeatability_summary.csv")
    by_strategy = pd.read_csv(tmp_path / "repeatability_by_strategy.csv")
    runtime = pd.read_csv(tmp_path / "runtime_stability.csv")

    assert (summary["metric"] == "plan_stable_condition_count").any()
    assert conditions.iloc[0]["repetition_count"] == 3
    assert by_strategy.iloc[0]["execution_strategy"] == "fdw_raw"
    assert set(runtime["metric"]) == {
        "elapsed_seconds",
        "main_root_actual_total_time_ms",
    }
