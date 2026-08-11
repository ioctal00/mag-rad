from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from master_regimes.corpus_adapter import render_corpus
from master_regimes.dataset_profile import validate_dataset_profile

ROOT = Path(__file__).resolve().parents[1]
SELECTION = (
    ROOT
    / "external/stats-ceb/query-selection.full-recovery-1800s-v1.yml"
)
SOURCE_SELECTION = (
    ROOT / "external/stats-ceb/query-selection.full-no-refit-v1.yml"
)
MANIFEST = (
    ROOT
    / "workloads/corpus/corpus_manifest.stats-ceb-full-recovery-1800s-v1.yml"
)
SCRIPT = (
    ROOT
    / "analysis/scripts/agent/70_stats_ceb_extended_recovery.py"
)
CORRECTNESS_IDS = {
    30,
    34,
    45,
    58,
    89,
    104,
    105,
    108,
    114,
    120,
    122,
    126,
    132,
    135,
}
COLLECTOR_IDS = {68, 106}


def load_script():
    spec = importlib.util.spec_from_file_location(
        "stats_ceb_extended_recovery",
        SCRIPT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recovery_selection_is_exact_and_preserves_source_contract() -> None:
    recovery = yaml.safe_load(SELECTION.read_text(encoding="utf-8"))
    source = yaml.safe_load(SOURCE_SELECTION.read_text(encoding="utf-8"))
    source_by_id = {
        int(item["query_id"]): item for item in source["queries"]
    }
    selected_by_id = {
        int(item["query_id"]): item for item in recovery["queries"]
    }

    assert set(selected_by_id) == CORRECTNESS_IDS | COLLECTOR_IDS
    assert recovery["recovery_contract"]["timeout_seconds"] == 1800
    assert recovery["recovery_contract"]["attempts_per_query"] == 1
    assert recovery["recovery_contract"]["query_concurrency"] == 1
    assert (
        set(
            recovery["recovery_contract"][
                "correctness_incomplete_query_ids"
            ]
        )
        == CORRECTNESS_IDS
    )
    assert (
        set(
            recovery["recovery_contract"][
                "collector_incomplete_query_ids"
            ]
        )
        == COLLECTOR_IDS
    )
    for query_id, selected in selected_by_id.items():
        source_item = source_by_id[query_id]
        for field in (
            "expected_count",
            "source_sha256",
            "tables",
            "table_count_stratum",
            "selection_hash",
        ):
            assert selected[field] == source_item[field]


def test_recovery_profile_and_rendered_plan_use_fixed_budget(
    tmp_path: Path,
) -> None:
    profile_path = (
        ROOT / "datasets/profiles/stats-ceb-full-recovery-1800s.yml"
    )
    result = validate_dataset_profile(profile_path)
    assert result["status"] == "ok", result["errors"]

    plan_path = render_corpus(
        manifest_path=MANIFEST,
        output_dir=tmp_path / "rendered",
        include_execution_classes={"pilot"},
    )
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    sweep_path = ROOT.parent / plan["groups"][0]["sweep_config"]
    sweep = yaml.safe_load(sweep_path.read_text(encoding="utf-8"))

    assert plan["groups"][0]["instance_count"] == 16
    assert plan["execution_budget"]["hard_timeout_seconds"] == 1800
    assert len(plan["groups"]) == 1
    assert sweep["collection"]["hard_timeout_seconds"] == 1800
    assert sweep["collection"]["timeout_grace_seconds"] == 60
    assert (
        sweep["collection"]["correctness_validation"]["timeout_seconds"]
        == 1800
    )
    assert (
        sweep["collection"]["correctness_validation"]["selection"]
        == "master-regimes/external/stats-ceb/"
        "query-selection.full-recovery-1800s-v1.yml"
    )
    assert (
        sweep["collection"]["correctness_validation"][
            "filter_workload_to_passed"
        ]
        is True
    )
    assert plan["execution_policy"]["repetitions_default"] == 1


def test_recovery_outcomes_preserve_original_failure_stage(
    tmp_path: Path,
) -> None:
    module = load_script()
    selection = {
        "recovery_contract": {
            "correctness_incomplete_query_ids": [30],
            "collector_incomplete_query_ids": [68],
        },
        "queries": [{"query_id": 30}, {"query_id": 68}],
    }
    query_audit = tmp_path / "recovery_query_audit.csv"
    query_audit.write_text(
        "query_id,query_run_id,comparison_status,execution_status\n"
        "30,run-30,passed,completed\n"
        "68,run-68,passed,timeout\n",
        encoding="utf-8",
    )
    projection = tmp_path / "recovery_projection.csv"
    projection.write_text(
        "query_id,k,ood_above_frozen_p99,nearest_center_distance,"
        "frozen_p99_threshold,max_membership,dominant_cluster\n"
        "30,4,False,0.5,1.0,0.7,1\n",
        encoding="utf-8",
    )
    query_attempts = tmp_path / "query_attempts.csv"
    query_attempts.write_text(
        "attempt_number,instance_id,query_run_id,execution_status\n"
        "1,stats_ceb_full_recovery_1800s__stats_ceb_multiregion_count__"
        "query_id-30,run-30,completed\n"
        "1,stats_ceb_full_recovery_1800s__stats_ceb_multiregion_count__"
        "query_id-68,run-68,timeout\n",
        encoding="utf-8",
    )

    rows = module.recovery_outcomes(
        selection=selection,
        query_audit_path=query_audit,
        projection_path=projection,
        query_attempts_path=query_attempts,
    )
    by_id = {row["query_id"]: row for row in rows}

    assert by_id[30]["primary_incomplete_stage"] == "correctness"
    assert by_id[30]["recovery_complete_observation"] is True
    assert by_id[30]["recovery_within_frozen_v2_p99"] is True
    assert by_id[68]["primary_incomplete_stage"] == "instrumented_collection"
    assert by_id[68]["recovery_complete_observation"] is False


def test_recovery_outcomes_report_attempted_timeout_from_logical_index(
    tmp_path: Path,
) -> None:
    module = load_script()
    selection = {
        "recovery_contract": {
            "correctness_incomplete_query_ids": [30],
            "collector_incomplete_query_ids": [],
        },
        "queries": [{"query_id": 30}],
    }
    query_audit = tmp_path / "recovery_query_audit.csv"
    query_audit.write_text(
        "query_id,query_run_id,comparison_status,execution_status\n"
        "30,,passed,\n",
        encoding="utf-8",
    )
    projection = tmp_path / "recovery_projection.csv"
    projection.write_text(
        "query_id,k,ood_above_frozen_p99\n",
        encoding="utf-8",
    )
    query_attempts = tmp_path / "query_attempts.csv"
    query_attempts.write_text(
        "attempt_number,instance_id,query_run_id,execution_status\n"
        "2,stats_ceb_full_recovery_1800s__stats_ceb_multiregion_count__"
        "query_id-30,run-30,timeout\n",
        encoding="utf-8",
    )

    [row] = module.recovery_outcomes(
        selection=selection,
        query_audit_path=query_audit,
        projection_path=projection,
        query_attempts_path=query_attempts,
    )

    assert row["recovery_execution_status"] == "timeout"
    assert row["query_run_id"] == "run-30"
