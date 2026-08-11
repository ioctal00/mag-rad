from pathlib import Path

import pandas as pd

from master_regimes.collector_audit import (
    EvidenceContract,
    correlation_key_dictionary,
    select_manual_cases,
    summarize_audit,
    summarize_logical_run,
)


def test_contract_expresses_applicability() -> None:
    contract = EvidenceContract.load(
        Path("configs/validation/expected_evidence_contract.yml")
    )
    assert contract.strategy("multiregion_union")["expected_regions"] == [
        "eu",
        "us",
    ]
    assert contract.strategy("fdw_raw")["expected_regions"] == ["eu"]
    assert (
        contract.strategy("etl_materialized")["remote_region_evidence"]
        == "not_applicable"
    )


def test_unknown_strategy_is_rejected() -> None:
    contract = EvidenceContract.load(
        Path("configs/validation/expected_evidence_contract.yml")
    )
    try:
        contract.strategy("unknown")
    except ValueError as exc:
        assert "Uncovered execution strategy" in str(exc)
    else:
        raise AssertionError("Unknown strategy was silently accepted")


def test_manual_selection_is_deterministic_and_diverse() -> None:
    rows = []
    for index in range(40):
        rows.append(
            {
                "logical_run_id": f"run-{index % 2}",
                "query_run_id": f"query-{index}",
                "instance_id": f"instance-{index}",
                "template_id": f"template-{index % 5}",
                "logical_question_id": f"family-{index % 7}",
                "execution_strategy": ["fdw_raw", "multiregion_union"][index % 2],
                "dataset_id": "dataset",
                "runtime_config_id": "default",
                "attempt_number": 1,
                "expected_regions": "eu",
                "observed_regions": "eu",
                "observed_remote_fragment_count": 1,
                "observed_worker_fragment_count": 32,
                "evidence_completeness": 1.0,
                "issue_count": 0,
                "issue_codes": "",
            }
        )
    frame = pd.DataFrame(rows)
    first = select_manual_cases(frame, sample_size=12, seed="fixed")
    second = select_manual_cases(frame, sample_size=12, seed="fixed")
    assert first["query_run_id"].tolist() == second["query_run_id"].tolist()
    assert first["logical_question_id"].nunique() == 7
    assert first["execution_strategy"].nunique() == 2


def test_correlation_dictionary_covers_all_evidence_layers() -> None:
    contract = EvidenceContract.load(
        Path("configs/validation/expected_evidence_contract.yml")
    )
    dictionary = correlation_key_dictionary(contract)
    assert set(dictionary["layer"]) == {
        "global_execution",
        "gac_main_plan",
        "regional_auto_explain",
        "citus_worker_task",
        "execution_feature_row",
        "retry_resolution",
    }
    regional = dictionary.set_index("layer").loc["regional_auto_explain"]
    assert "remote_plan_id" in regional["primary_identity"]
    assert "start_line" in regional["auxiliary_scope"]
    assert "application_name" in regional["auxiliary_scope"]


def _audit_fixture(query_run_ids: list[str]) -> pd.DataFrame:
    rows = []
    for query_run_id in query_run_ids:
        rows.append(
            {
                "query_run_id": query_run_id,
                "expected_regions": "",
                "missing_region_count": 0,
                "expected_worker_fragment_count": 0,
                "main_plan_count": 1,
                "main_plan_parse_ok": True,
                "remote_evidence_applicable": False,
                "region_parse_failure_count": 0,
                "worker_parse_failure_count": 0,
                "worker_unavailable_plan_count": 0,
                "region_identity_duplicate_rows": 0,
                "remote_sql_slot_duplicate_rows": 0,
                "worker_identity_duplicate_rows": 0,
                "plan_identity_duplicate_rows": 0,
                "orphan_worker_plan_count": 0,
                "region_context_mismatch_count": 0,
                "worker_context_mismatch_count": 0,
                "feature_context_mismatch_count": 0,
                "main_plan_exists": True,
                "artifact_paths_ok": True,
                "issue_count": 0,
            }
        )
    return pd.DataFrame(rows)


def _write_summary_fixture(
    root: Path,
    *,
    duplicate_feature: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    run_root = root / "fixture-run"
    index_dir = run_root / "_index"
    index_dir.mkdir(parents=True)
    pd.DataFrame({"query_run_id": ["q1", "q2"]}).to_csv(
        index_dir / "query_runs.csv", index=False
    )
    feature_ids = ["q1", "q2", "q2"] if duplicate_feature else ["q1", "q2"]
    pd.DataFrame({"query_run_id": feature_ids}).to_csv(
        index_dir / "execution_features.csv", index=False
    )
    pd.DataFrame(columns=["query_run_id"]).to_csv(
        index_dir / "region_fragments.csv", index=False
    )
    pd.DataFrame(columns=["query_run_id"]).to_csv(
        index_dir / "worker_task_fragments.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "query_run_id": "q1",
                "execution_status": "completed",
                "timed_out": False,
            },
            {
                "query_run_id": "q2-old",
                "execution_status": "missing",
                "timed_out": False,
            },
            {
                "query_run_id": "q2",
                "execution_status": "completed",
                "timed_out": False,
            },
        ]
    ).to_csv(run_root / "query_attempts.csv", index=False)
    pd.DataFrame(
        [
            {
                "attempt_count": 1,
                "resolved_status": "completed",
                "resolved_query_run_id": "q1",
            },
            {
                "attempt_count": 2,
                "resolved_status": "completed",
                "resolved_query_run_id": "q2",
            },
        ]
    ).to_csv(run_root / "resolved_query_status.csv", index=False)
    return _audit_fixture(["q1", "q2"]), pd.DataFrame()


def test_run_summary_counts_retry_and_exact_one_to_one(tmp_path: Path) -> None:
    audit, unresolved = _write_summary_fixture(tmp_path)
    summary = summarize_logical_run(
        tmp_path,
        "fixture-run",
        audit,
        unresolved,
    )
    assert summary["query_attempt_count"] == 3
    assert summary["retried_instance_count"] == 1
    assert summary["resolved_after_retry_count"] == 1
    assert summary["one_to_one_query_feature_count"] == 2
    assert summary["one_to_one_query_feature_ok"] is True
    assert summary["overall_correctness_gate"] is True


def test_run_summary_rejects_duplicate_feature_identity(tmp_path: Path) -> None:
    audit, unresolved = _write_summary_fixture(
        tmp_path,
        duplicate_feature=True,
    )
    summary = summarize_logical_run(
        tmp_path,
        "fixture-run",
        audit,
        unresolved,
    )
    assert summary["duplicate_feature_row_count"] == 2
    assert summary["one_to_one_query_feature_ok"] is False
    assert summary["overall_correctness_gate"] is False


def test_manual_review_summary_reports_counts_without_population_estimate() -> None:
    audit = pd.DataFrame(
        [
            {
                "logical_run_id": "run-1",
                "execution_strategy": "fdw_raw",
                "issue_count": 0,
                "evidence_completeness": 1.0,
                "applicability_ok": True,
                "uniqueness_ok": True,
                "consistency_ok": True,
                "artifact_paths_ok": True,
                "resolution_status": "resolved",
            }
        ]
    )
    manual_results = pd.DataFrame(
        [
            {"review_status": "reviewed", "link_correct": True},
            {"review_status": "reviewed", "link_correct": True},
        ]
    )

    summary = summarize_audit(audit, pd.DataFrame(), manual_results)

    assert summary["manual_reviewed_count"] == 2
    assert summary["manual_correct_link_count"] == 2
    assert "manual_link_accuracy" not in summary
    assert not any("wilson" in key.lower() for key in summary)
