from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "analysis/scripts/agent/100_pressure_profile_scorers.py"
    spec = importlib.util.spec_from_file_location("pressure_profile_scorers", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_contract():
    return yaml.safe_load(
        (ROOT / "configs/models/pressure_profile_scorers_v1.yml").read_text(
            encoding="utf-8"
        )
    )


def test_contract_has_five_independent_domains_without_design_inputs() -> None:
    contract = load_contract()
    assert set(contract["domains"]) == {
        "gac_finalization",
        "remote_path",
        "worker_data_skew",
        "repartition_join",
        "regional_finalization",
    }
    names = {
        feature["name"]
        for domain in contract["domains"].values()
        for feature in domain["features"]
    }
    assert not names.intersection(contract["forbidden_model_inputs"])
    assert "elapsed_seconds" not in names
    assert "target_log2_gain" not in names
    assert contract["domains"]["remote_path"]["minimum_feature_coverage"] == 0.4
    assert "edge_boundary_wait_share" in contract["domains"]["remote_path"][
        "required_features"
    ]
    assert contract["domains"]["gac_finalization"]["output_mode"] == (
        "component_profile"
    )
    assert set(contract["domains"]["gac_finalization"]["component_profiles"]) == {
        "gac_fanin",
        "gac_reduction",
        "gac_sort_spill",
        "gac_aggregate_finalization",
    }
    categories = contract["feature_provenance"]["categories"]
    provenance_names = [
        name for category in categories.values() for name in category["features"]
    ]
    assert len(provenance_names) == len(set(provenance_names))
    assert set(provenance_names) == names
    assert "edge_estimated_fetch_cycles_sum" not in names
    assert contract["feature_provenance"]["descriptive_only_evidence"] == [
        {
            "name": "edge_estimated_fetch_cycles_sum",
            "provenance": "intervention_sensitive_estimate",
            "exclusion_reason": (
                "Procjena koristi aktivni fetch_size i zato nije modelski ulaz."
            ),
        }
    ]


def test_edge_aggregation_preserves_per_execution_scope() -> None:
    module = load_module()
    edges = pd.DataFrame(
        [
            {
                "query_run_id": "q1",
                "remote_bytes_proxy": 100,
                "estimated_fetch_cycles": 2,
                "rtt_context_median_ms": 20,
                "query_window_source_tx_bps": 1000,
                "foreign_scan_time_ms_sum": 80,
                "regional_plan_time_ms_sum": 50,
                "foreign_scan_minus_regional_time_ms_proxy": 30,
                "packet_loss_context_percent_max": 0,
                "query_window_qdisc_overlimits": 3,
                "tcp_retrans_delta_node_global": 1,
            },
            {
                "query_run_id": "q1",
                "remote_bytes_proxy": 300,
                "estimated_fetch_cycles": 4,
                "rtt_context_median_ms": 40,
                "query_window_source_tx_bps": 3000,
                "foreign_scan_time_ms_sum": 120,
                "regional_plan_time_ms_sum": 90,
                "foreign_scan_minus_regional_time_ms_proxy": 30,
                "packet_loss_context_percent_max": 1,
                "query_window_qdisc_overlimits": 5,
                "tcp_retrans_delta_node_global": 2,
            },
        ]
    )
    result = module.aggregate_edge_evidence(edges).iloc[0]
    assert result["edge_remote_bytes_sum"] == 400
    assert result["edge_estimated_fetch_cycles_sum"] == 6
    assert result["edge_rtt_context_median_ms_max"] == 40
    assert result["edge_source_tx_bps_hmean"] == pytest.approx(1500)
    assert result["edge_boundary_wait_ms_sum"] == 60
    assert result["edge_boundary_wait_share"] == pytest.approx(0.3)


def test_pairwise_ranker_learns_order_and_penalizes_control_change() -> None:
    module = load_module()
    domain = {
        "features": [
            {"name": "signal", "transform": "identity", "baseline_direction": 1},
            {"name": "noise", "transform": "identity", "baseline_direction": 1},
        ]
    }
    positive = pd.DataFrame(
        {
            "pair_id": [f"p{i}" for i in range(12)],
            "signal__stressed": np.linspace(2, 5, 12),
            "signal__mitigated": np.linspace(0, 1, 12),
            "noise__stressed": np.tile([0, 1], 6),
            "noise__mitigated": np.tile([1, 0], 6),
        }
    )
    controls = pd.DataFrame(
        {
            "pair_id": [f"c{i}" for i in range(6)],
            "signal__stressed": np.ones(6),
            "signal__mitigated": np.ones(6),
            "noise__stressed": np.arange(6),
            "noise__mitigated": np.arange(6)[::-1],
        }
    )
    estimator = {
        "margin": 1.0,
        "l2_penalty": 0.1,
        "control_invariance_penalty": 1.0,
        "maximum_iterations": 1000,
    }
    state = module.fit_ranker(positive, controls, domain, estimator)
    scored = module.pair_scores(positive, state)
    control_scores = module.pair_scores(controls, state)
    assert scored["score_delta"].gt(0).all()
    assert abs(state["weights"][0]) > abs(state["weights"][1])
    assert control_scores["score_delta"].abs().median() < scored["score_delta"].median()


def test_remote_domain_accepts_core_edge_evidence_without_optional_telemetry() -> None:
    module = load_module()
    contract = load_contract()
    domain = contract["domains"]["remote_path"]
    row = {
        "pair_id": "pair-1",
        "strict_gain_eligible": True,
        "pressure_axis": "remote_path",
        "intervention_role": "negative_control",
    }
    core = set(domain["required_features"])
    for feature in domain["features"]:
        name = feature["name"]
        row[f"{name}__stressed"] = 1.0 if name in core else np.nan
        row[f"{name}__mitigated"] = 1.0 if name in core else np.nan
    planned, positive, controls = module.filter_pairs_for_domain(
        pd.DataFrame([row]),
        "remote_path",
        domain,
        contract["pair_contract"],
    )
    assert planned.empty
    assert positive.empty
    assert len(controls) == 1


def test_response_matrix_reports_off_diagonal_relative_to_own_axis() -> None:
    module = load_module()
    pairs = pd.DataFrame(
        [
            {
                "pair_id": f"p{index}",
                "score_kind": "transparent_coordinate",
                "pressure_axis": "repartition_join",
                "intervention_role": "positive_case",
                "domain": "repartition_join",
                "diagnostic_domain": "repartition_join",
                "output_mode": "scalar_coordinate",
                "score_delta": value,
            }
            for index, value in enumerate([2.0, 2.2, 1.8])
        ]
        + [
            {
                "pair_id": f"p{index}",
                "score_kind": "transparent_coordinate",
                "pressure_axis": "repartition_join",
                "intervention_role": "positive_case",
                "domain": "worker_data_skew",
                "diagnostic_domain": "worker_data_skew",
                "output_mode": "scalar_coordinate",
                "score_delta": value,
            }
            for index, value in enumerate([1.0, 1.1, 0.9])
        ]
    )
    audit = pd.DataFrame(
        [
            {
                "pair_id": f"p{index}",
                "pressure_axis": "repartition_join",
                "intervention_role": "positive_case",
            }
            for index in range(3)
        ]
    )
    contract = load_contract()
    contract["estimator"]["random_seed"] = 1
    contract["bootstrap"] = {"repetitions": 100, "confidence_level": 0.95}
    result = module.build_response_matrix(pairs, audit, contract)
    cross = result[result["scorer_domain"].eq("worker_data_skew")].iloc[0]
    assert cross["diagonal_median_score_delta"] == pytest.approx(2.0)
    assert cross["absolute_delta_relative_to_diagonal"] == pytest.approx(0.5)


def test_local_calibration_uses_mitigated_reference_without_bands() -> None:
    module = load_module()
    rows = []
    for index, score in enumerate([0.9, 1.0, 1.1, 2.0]):
        rows.append(
            {
                "query_run_id": f"q{index}",
                "domain": "remote_path",
                "variant": "mitigated" if index < 3 else "stressed",
                "coordinate_score": score,
                "sql_normalized_hash": "sql-a",
                "dataset_profile_id": "dataset-a",
                "topology_id": "n2",
                "execution_scope": "global",
                "logical_question_id": "question-a",
                "created_at_utc": f"2026-01-01T00:00:0{index}Z",
            }
        )
    contract = {
        "coordinate_field": "coordinate_score",
        "feature_contract_version": "test-v1",
        "reference_variants": ["mitigated"],
        "minimum_reference_executions": 3,
        "scale_floor": 0.05,
        "exact_group_fields": [
            "sql_normalized_hash",
            "dataset_profile_id",
            "topology_id",
            "execution_scope",
        ],
        "fallback_group_fields": [
            "logical_question_id",
            "dataset_profile_id",
            "topology_id",
            "execution_scope",
        ],
    }
    result = module.local_calibration(pd.DataFrame(rows), contract)
    first_reference = result[result["query_run_id"].eq("q0")].iloc[0]
    stressed = result[result["variant"].eq("stressed")].iloc[0]
    assert first_reference["local_context_status"] == "insufficient_history"
    assert pd.isna(first_reference["local_robust_z"])
    assert stressed["local_context_status"] == "available"
    assert stressed["reference_scope"] == "exact_query_context"
    assert stressed["local_median"] == pytest.approx(1.0)
    assert stressed["local_robust_z"] > 0
    assert "pressure_band" not in result.columns


def test_local_calibration_does_not_fallback_to_logical_question() -> None:
    module = load_module()
    rows = []
    for index, score in enumerate([0.9, 1.0, 1.1]):
        rows.append(
            {
                "query_run_id": f"reference-{index}",
                "domain": "remote_path",
                "variant": "mitigated",
                "coordinate_score": score,
                "sql_normalized_hash": "sql-reference",
                "dataset_profile_id": "dataset-a",
                "topology_id": "n2",
                "execution_scope": "global",
                "logical_question_id": "question-a",
                "created_at_utc": f"2026-01-01T00:00:0{index}Z",
            }
        )
    rows.append(
        {
            "query_run_id": "candidate",
            "domain": "remote_path",
            "variant": "stressed",
            "coordinate_score": 2.0,
            "sql_normalized_hash": "sql-candidate",
            "dataset_profile_id": "dataset-a",
            "topology_id": "n2",
            "execution_scope": "global",
            "logical_question_id": "question-a",
            "created_at_utc": "2026-01-01T00:00:03Z",
        }
    )
    contract = {
        "coordinate_field": "coordinate_score",
        "feature_contract_version": "test-v1",
        "reference_variants": ["mitigated"],
        "minimum_reference_executions": 3,
        "scale_floor": 0.05,
        "fallback_enabled": False,
        "exact_group_fields": [
            "sql_normalized_hash",
            "dataset_profile_id",
            "topology_id",
            "execution_scope",
        ],
        "fallback_group_fields": [
            "logical_question_id",
            "dataset_profile_id",
            "topology_id",
            "execution_scope",
        ],
    }
    result = module.local_calibration(pd.DataFrame(rows), contract)
    candidate = result[result["query_run_id"].eq("candidate")].iloc[0]
    assert candidate["local_context_status"] == "insufficient_history"
    assert candidate["reference_scope"] == "exact_query_context"
    assert candidate["reference_count"] == 0


def test_methodological_audit_separates_validation_from_local_calibration() -> None:
    module = load_module()
    contract = load_contract()
    executions = pd.DataFrame(
        [
            {
                "condition_id": "condition-a",
                "pair_id": "pair-a",
            }
        ]
    )
    pairs = pd.DataFrame([{"pair_id": "pair-a"}])
    scores = pd.DataFrame(
        [
            {
                "score_status": "insufficient_evidence",
                "coordinate_score": np.nan,
            }
        ]
    )
    predictions = pd.DataFrame(
        [
            {
                "domain": "remote_path",
                "holdout": "leave_dataset_out",
                "held_out_group": "dataset-a",
                "pair_id": "pair-a",
                "score_delta": 1.0,
            }
        ]
    )
    result = module.methodological_audit(
        executions,
        pairs,
        scores,
        predictions,
        contract,
    )
    assert result["calibration_leakage"]["status"] == "PASS"
    assert result["grouped_split_integrity"]["status"] == "PASS"
    assert result["model_input_scope"]["status"] == "PASS"
    assert result["missingness_semantics"]["status"] == "PASS"
    assert result["calibration_leakage"]["live_time_causal_calibration"]
