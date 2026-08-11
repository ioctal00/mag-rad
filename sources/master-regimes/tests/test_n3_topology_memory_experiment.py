from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "analysis/scripts/agent/104_n3_topology_memory_experiment.py"
    specification = importlib.util.spec_from_file_location("n3_topology_memory_104", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _profile_tenants(profile: dict) -> dict[int, str]:
    tenants: dict[int, str] = {}
    for physical_region, specification in profile["regions"].items():
        ranges = specification.get("tenant_id_ranges")
        if ranges is None:
            ranges = [
                [
                    *specification["tenant_id_range"],
                    specification.get("data_region_id", physical_region),
                ]
            ]
        for start, end, logical_region in ranges:
            for tenant_id in range(int(start), int(end) + 1):
                assert tenant_id not in tenants
                tenants[tenant_id] = str(logical_region)
    return tenants


def test_contract_has_exact_primary_n3_design() -> None:
    module = _load_module()
    contract = module.read_yaml(module.DEFAULT_CONTRACT)
    scenarios = module.validate_contract(contract)
    blocks = {row["id"]: row for row in contract["blocks"]}

    assert len(scenarios) == 15
    assert sum(
        int(row["expected_executions"])
        for row in blocks.values()
        if row["topology"] == "n3"
    ) == 120
    assert int(blocks["n2_control"]["expected_executions"]) == 60
    assert contract["model_freeze"]["refit_on_n3"] is False


def test_dataset_pairs_preserve_logical_content_contract() -> None:
    module = _load_module()
    contract = module.read_yaml(module.DEFAULT_CONTRACT)
    for pair in contract["dataset_pairs"].values():
        n2 = module.read_yaml(ROOT / pair["n2"]["profile"])
        n3 = module.read_yaml(ROOT / pair["n3"]["profile"])

        assert _profile_tenants(n2) == _profile_tenants(n3)
        assert module.profile_tenant_regions(n2) == module.profile_tenant_regions(n3)
        assert n2["seed"] == n3["seed"]
        assert n2["base_time_unix"] == n3["base_time_unix"]
        assert n2["scale"] == n3["scale"]
        assert n2["distribution"] == n3["distribution"]
        assert n2["identity"]["event_id_mode"] == "tenant_global"
        assert n3["identity"]["event_id_mode"] == "tenant_global"


def test_blind_and_context_exact_memory_diverge_on_topology_shift() -> None:
    module = _load_module()
    event = pd.Series(
        {
            "logical_query_hash": "same-query",
            "topology_id": "eu_us_apac_gac",
            "dataset_pair": "small",
            "profile": "transport",
        }
    )
    states = pd.DataFrame(
        [
            {
                "episode_id": "n2::q01",
                "query_id": "q01",
                "logical_query_hash": "same-query",
                "topology_id": "eu_us_gac",
                "dataset_pair": "small",
                "profile": "transport",
            }
        ]
    )
    outcomes = pd.DataFrame(
        [
            {
                "episode_id": "n2::q01",
                "mitigation_action": action,
                "target_log2_gain": float(index),
            }
            for index, action in enumerate(module.ACTIONS)
        ]
    )

    blind, blind_status, _ = module.exact_prediction(
        event, states, outcomes, context_aware=False
    )
    context, context_status, _ = module.exact_prediction(
        event, states, outcomes, context_aware=True
    )

    assert blind_status == "available"
    assert all(np.isfinite(blind[action]) for action in module.ACTIONS)
    assert context_status == "exact_context_unseen"
    assert all(np.isnan(context[action]) for action in module.ACTIONS)


def test_cross_query_call_excludes_query_identity() -> None:
    module = _load_module()
    calls: list[tuple[str, str]] = []

    class FakeDba:
        @staticmethod
        def _estimate_from_memory(
            _test_value,
            _memory_values,
            _memory_states,
            _memory_outcomes,
            **kwargs,
        ):
            calls.append(
                (kwargs["excluded_query_id"], kwargs["excluded_normalized_sql_hash"])
            )
            return (
                {action: float(index) for index, action in enumerate(module.ACTIONS)},
                [],
                0.1,
                3,
            )

        @staticmethod
        def _status(**_kwargs):
            return "available"

        @staticmethod
        def _decision_actions(predictions, status, actions):
            candidate = max(actions, key=predictions.__getitem__)
            return candidate, candidate if status == "available" else ""

    contract = module.read_yaml(module.DEFAULT_CONTRACT)
    event = pd.DataFrame(
        [
            {
                "episode_id": "phase_a::q01",
                "episode_order": 1,
                "query_id": "q01",
                "logical_query_hash": "logical-q01",
                "baseline_query_run_id": "run-1",
                "topology_id": "eu_us_apac_gac",
                "dataset_pair": "small",
                "profile": "transport",
            }
        ]
    )
    states = pd.DataFrame(
        [
            {
                "episode_id": "n2::q02",
                "query_id": "q02",
                "logical_query_hash": "logical-q02",
                "topology_id": "eu_us_gac",
                "dataset_pair": "small",
                "profile": "transport",
            }
        ]
    )
    outcomes = pd.DataFrame(
        [
            {
                "episode_id": "n2::q02",
                "mitigation_action": action,
                "target_log2_gain": float(index),
            }
            for index, action in enumerate(module.ACTIONS)
        ]
    )

    module.recommendations(
        contract,
        event,
        states,
        outcomes,
        np.zeros((1, 2)),
        np.zeros((1, 2)),
        1.0,
        FakeDba,
        freeze_id="phase_a_recommendations",
        allow_context_exact=False,
        n3_only=False,
    )

    assert calls == [("q01", "logical-q01")]


def test_topology_sql_canonicalization_removes_only_apac_source() -> None:
    module = _load_module()
    n2 = """with events_all as (
select 'eu'::text from fdw_eu.events
union all
select 'us'::text from fdw_us.events
)
select * from events_all;
"""
    n3 = """with events_all as (
select 'eu'::text from fdw_eu.events
union all
select 'us'::text from fdw_us.events
union all
select 'apac'::text from fdw_apac.events
)
select * from events_all;
"""

    assert module.canonicalize_topology_sql(n2) == module.canonicalize_topology_sql(n3)


def test_raw_execution_identifiers_use_indexed_query_timestamps() -> None:
    module = _load_module()
    frame = pd.DataFrame(
        [
            {
                "query_run_id": "run-1",
                "execution_slot_id": "slot-1",
                "condition_id": "condition-1",
                "component_match_id": "component-1",
                "variant": "stressed",
                "mitigation_action": np.nan,
                "execution_status": "completed",
                "timed_out": False,
                "query_started_at_unix": 10.0,
                "query_finished_at_unix": 12.0,
                "experiment_block_id": "phase_a_baseline",
            }
        ]
    )

    result = module.raw_execution_identifiers({"phase_a_baseline": frame})

    assert result.loc[0, "query_started_at_unix"] == 10.0
    assert result.loc[0, "query_finished_at_unix"] == 12.0


def test_metric_rows_count_only_valid_actions_as_recommendations() -> None:
    module = _load_module()
    scored = pd.DataFrame(
        [
            {
                "phase": "A",
                "method": "cross_query_knn",
                "predicted_action": np.nan,
                "top1_correct": False,
                "regret_log2": np.nan,
                "nearest_distance": 3.0,
            },
            {
                "phase": "A",
                "method": "cross_query_knn",
                "predicted_action": "mitigate_remote_path_bundle",
                "top1_correct": True,
                "regret_log2": 0.0,
                "nearest_distance": 1.0,
            },
        ]
    )

    row = module._metric_rows(scored).iloc[0]

    assert row["recommendation_count"] == 1
    assert row["abstention_count"] == 1
    assert row["coverage"] == 0.5
    assert row["top1_accuracy_among_recommendations"] == 1.0


def test_phase_metric_comparison_has_single_flat_header() -> None:
    module = _load_module()
    metrics = pd.DataFrame(
        [
            {"phase": "A", "method": "knn", "coverage": 0.0},
            {"phase": "B", "method": "knn", "coverage": 1.0},
        ]
    )

    result = module._flatten_phase_metric_comparison(metrics)

    assert result.columns.tolist() == ["method", "coverage__A", "coverage__B"]


def test_report_checksums_exclude_checksum_file(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "a.csv").write_text("a\n1\n", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}\n", encoding="utf-8")

    module.write_report_checksums(tmp_path)
    first = (tmp_path / "checksums.sha256").read_text(encoding="utf-8")
    module.write_report_checksums(tmp_path)
    second = (tmp_path / "checksums.sha256").read_text(encoding="utf-8")

    assert first == second
    assert "a.csv" in first
    assert "b.json" in first
    assert "checksums.sha256" not in first
