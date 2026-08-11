from __future__ import annotations

import json
from pathlib import Path

from master_regimes.feedback_loop import (
    DOMAIN_IDS,
    build_domain_view,
    build_relative_profile,
    classify_end_to_end_effect,
    classify_outcome,
    classify_physical_transition,
    identity_matches,
    load_yaml,
    render_dry_run_plan,
    results_equivalent,
    validate_authoritative_rq_h_text,
    validate_decision_log,
    validate_dry_run_plan,
    validate_intervention_catalog,
    validate_pressure_domain_manifest,
    validate_query_trajectory_manifest,
)
from master_regimes.temporal_contract import (
    cutoff_offset_days,
    cutoff_timestamp,
    validate_cutoff_against_contract,
    validate_dataset_time_contract,
    wall_clock_functions,
)

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments/feedback-loop-v1"


def manifests() -> tuple[dict, dict, dict]:
    domains = load_yaml(EXPERIMENT / "pressure_domain_manifest.yaml")
    catalog = load_yaml(EXPERIMENT / "intervention_catalog.yaml")
    trajectories = load_yaml(EXPERIMENT / "query_trajectory_manifest.yaml")
    return domains, catalog, trajectories


def test_manifests_freeze_six_domains_without_global_thresholds() -> None:
    domains, catalog, trajectories = manifests()
    assert validate_pressure_domain_manifest(domains) == []
    assert validate_intervention_catalog(catalog) == []
    assert validate_query_trajectory_manifest(trajectories, catalog) == []
    assert tuple(domain["id"] for domain in domains["domains"]) == DOMAIN_IDS
    assert domains["universal_high_low_thresholds"] is False


def test_query_cutoffs_are_offsets_from_the_frozen_dataset_anchor() -> None:
    _, _, trajectories = manifests()
    contract = trajectories["dataset_time_contract"]
    assert validate_dataset_time_contract(contract) == []
    observed_offsets = {
        cutoff_offset_days(contract["base_time_unix"], cutoff)
        for trajectory in trajectories["trajectories"]
        if (cutoff := trajectory.get("parameter_bindings", {}).get("cutoff_ts"))
    }
    assert observed_offsets == {30}


def test_cutoff_before_generated_window_is_a_valid_full_dataset_selection() -> None:
    _, _, trajectories = manifests()
    contract = trajectories["dataset_time_contract"]

    cutoff = cutoff_timestamp(contract["base_time_unix"], 60)

    assert cutoff.isoformat() == "2026-05-02T00:00:00+00:00"
    assert validate_cutoff_against_contract(cutoff.isoformat(), contract) == []
    assert 60 > contract["generated_lookback_days"]


def test_measured_feedback_loop_sql_does_not_use_the_live_wall_clock() -> None:
    run_roots = (
        ROOT / "generated/feedback-loop-runs/20260807T123708Z-pressure-feedback-loop-v1",
        ROOT
        / "generated/feedback-loop-runs/20260807T152322Z-pressure-feedback-loop-aggregate-exact-v1",
    )
    sql_files = [path for root in run_roots for path in root.glob("rendered_sql/*.sql")]
    assert sql_files
    assert {
        path.relative_to(ROOT).as_posix(): wall_clock_functions(path.read_text(encoding="utf-8"))
        for path in sql_files
        if wall_clock_functions(path.read_text(encoding="utf-8"))
    } == {}


def test_every_intervention_has_apply_rollback_and_verification() -> None:
    _, catalog, _ = manifests()
    for action in catalog["interventions"]:
        assert action["apply"]["command"]
        assert action["apply"]["verify_command"]
        assert action["rollback"]["command"]
        assert action["rollback"]["verify_command"]
        assert action["requires_dataset_reload"] is False
        assert action["changes_colocation"] is False
        assert action["changes_shard_placement"] is False


def test_dry_run_is_offline_and_has_expected_and_maximum_counts() -> None:
    _, _, trajectories = manifests()
    plan = render_dry_run_plan(trajectories)
    assert validate_dry_run_plan(plan, trajectories) == []
    assert len(plan) == 45
    assert sum(row["included_in_expected_count"] for row in plan) == 36
    assert all(row["live_execution"] is False for row in plan)
    assert all(row["requires_pre_outcome_decision"] for row in plan if row["step_index"] > 0)


def test_identity_contracts_do_not_infer_sql_semantics() -> None:
    base = {
        "sql_normalized_hash": "sql-a",
        "logical_question_id": "question-a",
        "dataset_snapshot_id": "snapshot-1",
        "topology_id": "n2",
        "pair_id": "pair-1",
        "result_contract_id": "result-v1",
    }
    same_sql_after = {**base, "action_id": "custom-change"}
    rewrite_after = {
        **same_sql_after,
        "sql_normalized_hash": "sql-b",
    }
    assert identity_matches(base, same_sql_after, "same_normalized_sql")
    assert identity_matches(base, same_sql_after, "same_sql_declared_intervention")
    assert not identity_matches(base, rewrite_after, "same_normalized_sql")
    assert identity_matches(base, rewrite_after, "manual_logical_question_link")
    assert not identity_matches(
        base,
        {**rewrite_after, "logical_question_id": "different-question"},
        "manual_logical_question_link",
    )


def test_result_contract_distinguishes_order_and_multiset() -> None:
    before = {"ordered_sha256": "ordered-a", "multiset_sha256": "set-a"}
    reordered = {"ordered_sha256": "ordered-b", "multiset_sha256": "set-a"}
    assert not results_equivalent(before, reordered, {"mode": "ordered_sequence_hash"})
    assert results_equivalent(before, reordered, {"mode": "multiset_hash"})
    assert results_equivalent(
        {"value": 100.0},
        {"value": 100.00001},
        {
            "mode": "typed_scalar_tolerance",
            "absolute_tolerance": 0.001,
            "relative_tolerance": 0.0,
        },
    )


def test_decision_log_rejects_leakage_and_future_outcomes() -> None:
    decision = {
        "record_type": "decision",
        "decision_id": "d1",
        "recorded_at_utc": "2026-08-07T10:00:00Z",
        "history_cutoff_utc": "2026-08-07T09:59:00Z",
        "status": "locked_pre_execution",
    }
    outcome = {
        "record_type": "outcome",
        "decision_id": "d1",
        "recorded_at_utc": "2026-08-07T10:30:00Z",
        "outcome_label": "mixed",
    }
    assert validate_decision_log([decision, outcome]) == []
    leaked = {**decision, "delta_outcome": {"elapsed_log2_gain": 1.0}}
    assert any("leaks outcome" in error for error in validate_decision_log([leaked]))
    assert any("precedes" in error for error in validate_decision_log([outcome, decision]))
    future_cutoff = {**decision, "history_cutoff_utc": "2026-08-07T10:01:00Z"}
    assert any("future" in error for error in validate_decision_log([future_cutoff]))


def test_domain_coordinate_preserves_conflicting_components() -> None:
    domains, _, _ = manifests()
    remote = domains["domains"][0]
    reference = [
        {
            "foreign_scan_time_share": 0.5,
            "edge_remote_bytes_sum": 100,
            "edge_boundary_wait_share": 0.2,
            "edge_rtt_context_median_ms_max": 5,
            "edge_source_tx_bps_hmean": 100,
        }
        for _ in range(3)
    ]
    current = [
        {
            "foreign_scan_time_share": 0.7,
            "edge_remote_bytes_sum": 200,
            "edge_boundary_wait_share": 0.3,
            "edge_rtt_context_median_ms_max": 6,
            "edge_source_tx_bps_hmean": 200,
        }
        for _ in range(3)
    ]
    view = build_domain_view(remote, current, reference)
    assert view["status"] == "available"
    assert view["relative_pressure_evidence"] is not None
    assert view["conflicting_component_signs"] is True
    assert len(view["components"]) == len(remote["features"])


def test_relative_profile_uses_all_three_frozen_reference_names() -> None:
    domains, _, _ = manifests()
    feature_ids = {feature["id"] for domain in domains["domains"] for feature in domain["features"]}
    current = [{feature_id: 2.0 for feature_id in feature_ids}]
    reference = [{feature_id: 1.0 for feature_id in feature_ids}]
    profile = build_relative_profile(
        domains,
        current,
        {
            "trajectory_origin": reference,
            "previous_accepted_state": reference,
            "prior_logical_question_history": reference,
        },
    )

    assert set(profile["views"]) == set(domains["relative_references"])
    assert all(view["status"] == "available" for view in profile["views"].values())


def test_outcome_label_keeps_runtime_domain_conflict_mixed() -> None:
    assert (
        classify_outcome(
            result_valid=True,
            outcome_direction="improved",
            adverse_domain_change=True,
            beneficial_domain_change=True,
            conflicting_domain_components=False,
        )
        == "mixed"
    )
    assert (
        classify_outcome(
            result_valid=True,
            outcome_direction="within_noise_or_unavailable",
            adverse_domain_change=False,
            beneficial_domain_change=False,
            conflicting_domain_components=False,
        )
        == "indeterminate"
    )


def test_outcome_axes_do_not_collapse_runtime_and_physical_evidence() -> None:
    assert (
        classify_end_to_end_effect(
            result_valid=True,
            interval_low=0.1,
            interval_high=0.4,
        )
        == "positive"
    )
    assert (
        classify_end_to_end_effect(
            result_valid=True,
            interval_low=-0.4,
            interval_high=-0.1,
        )
        == "negative"
    )
    assert (
        classify_end_to_end_effect(
            result_valid=True,
            interval_low=-0.1,
            interval_high=0.1,
        )
        == "no_material_change"
    )
    assert (
        classify_physical_transition(
            [
                {
                    "status": "available",
                    "relative_pressure_evidence": -1.0,
                    "conflicting_component_signs": False,
                },
                {
                    "status": "available",
                    "relative_pressure_evidence": 0.5,
                    "conflicting_component_signs": False,
                },
            ]
        )
        == "mixed"
    )


def test_exact_aggregate_addendum_is_frozen_and_uses_exact_arithmetic() -> None:
    addendum = load_yaml(EXPERIMENT / "aggregate_exact_addendum.yaml")
    trajectories = load_yaml(EXPERIMENT / "aggregate_exact_query_manifest.yaml")
    _, catalog, _ = manifests()

    assert addendum["execution_order"]["total_execution_count"] == 25
    flattened = [
        state
        for block in addendum["execution_order"]["blocks"]
        for state in block
    ]
    assert {state: flattened.count(state) for state in set(flattened)} == {
        "A_raw_baseline": 5,
        "B_fetch_size": 5,
        "C_regional_aggregate": 5,
        "D_wan_delay": 5,
    }
    trajectory = trajectories["trajectories"][0]
    catalog_ids = {action["id"] for action in catalog["interventions"]}
    assert set(trajectory["allowed_actions"]).issubset(catalog_ids)
    assert trajectory["allowed_identity_modes"] == [
        "same_normalized_sql",
        "same_sql_declared_intervention",
        "manual_logical_question_link",
    ]
    assert trajectories["automatic_sql_semantic_similarity"] is False

    raw_sql = (
        ROOT
        / "workloads/templates/gac-fdw/gac_fdw_multiregion_event_exact_raw_summary.sql.j2"
    ).read_text(encoding="utf-8")
    regional_sql = (
        ROOT
        / "workloads/templates/gac-fdw/gac_fdw_multiregion_event_exact_regional_summary.sql.j2"
    ).read_text(encoding="utf-8")
    combined = (raw_sql + regional_sql).lower()
    assert "count(*)::numeric" in combined
    assert "avg(" not in combined
    assert "double precision" not in combined


def test_rq_h_mapping_contains_fixed_application_formulations() -> None:
    mapping = (EXPERIMENT / "RQ_H_MAPPING.md").read_text(encoding="utf-8")
    assert validate_authoritative_rq_h_text(mapping) == []


def test_decision_log_schema_is_machine_readable() -> None:
    schema = json.loads(
        (EXPERIMENT / "schemas/decision_log.schema.json").read_text(encoding="utf-8")
    )
    assert schema["$schema"].endswith("2020-12/schema")
    assert {"decision", "outcome"}.issubset(schema["$defs"])
