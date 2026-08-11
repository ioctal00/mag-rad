from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from master_regimes.corpus_adapter import _apply_execution_policy_to_rows
from master_regimes.repeatability import build_selection, build_smoke_selection


def _candidate_rows(count: int = 120) -> pd.DataFrame:
    rows = []
    strategies = [
        "single_region_citus",
        "fdw_raw",
        "multiregion_union",
        "etl_materialized",
    ]
    for index in range(count):
        sql_path = Path("/tmp") / f"repeatability-{index}.sql"
        sql_path.write_text("select 1;\n", encoding="utf-8")
        runtime_config_id = [
            "default",
            "fetch_small",
            "work_mem_low",
            "wan_100ms",
        ][index % 4]
        source_plan_id = (
            "validation-holdout-v1" if index % 5 == 0 else "clean-run-v1"
        )
        rows.append(
            {
                "query_run_id": f"query-{index}",
                "source_plan_id": source_plan_id,
                "source_logical_run_id": (
                    "clean-run-v1-validation-holdout"
                    if source_plan_id == "validation-holdout-v1"
                    else "clean-run-v1"
                ),
                "execution_status": "completed",
                "source_sql_file": str(sql_path),
                "logical_question_id": f"family-{index % 11}",
                "execution_strategy": strategies[index % 4],
                "dataset_id": [
                    "pilot-balanced-v1",
                    "pilot-skew-heavy-v1",
                ][index % 2],
                "dataset_profile_id": [
                    "pilot-balanced-v1",
                    "pilot-skew-heavy-v1",
                ][index % 2],
                "runtime_config_id": runtime_config_id,
                "network_profile_id": (
                    "wan_100ms" if runtime_config_id == "wan_100ms" else ""
                ),
                "corpus_cell_id": f"cell-{index}",
                "instance_id": f"instance-{index}",
                "template_id": f"template-{index % 11}",
                "param_json": "{}",
                "expected_shape_tags": "",
                "topology_id": "eu_us_gac",
                "intervention_role": "baseline",
                "intervention_axis": "",
                "expected_regime_targets": "",
                "execution_class": "pilot",
            }
        )
    return pd.DataFrame(rows)


def _memberships(count: int = 120) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "query_run_id": f"query-{index}",
                "k": 4,
                "hard_cluster": index % 4,
                "max_membership": 0.7 if index % 3 else 0.45,
                "top2_margin": 0.4 if index % 3 else 0.05,
                "membership_entropy": 0.8,
            }
            for index in range(count)
        ]
    )


def test_selection_has_locked_counts_and_is_deterministic() -> None:
    first = build_selection(_candidate_rows(), _memberships())
    second = build_selection(_candidate_rows(), _memberships())
    assert first["source_query_run_id"].tolist() == second[
        "source_query_run_id"
    ].tolist()
    assert len(first) == 96
    assert first["condition_id"].nunique() == 96
    assert int(first["sentinel_flag"].sum()) == 20
    assert int(first["planned_repetitions"].sum()) == 328
    assert first["logical_question_id"].nunique() == 11
    assert first["execution_strategy"].nunique() == 4
    assert set(first["source_plan_id"]) == {
        "clean-run-v1",
        "validation-holdout-v1",
    }
    assert first["network_profile_id"].ne("").any()


def test_execution_policy_expands_repetitions_without_changing_instance() -> None:
    rows = [
        {
            "condition_id": "condition-a",
            "instance_id": "same-instance",
            "corpus_cell_id": "cell",
            "corpus_id": "corpus",
            "dataset_profile_id": "dataset",
            "runtime_config_id": "default",
            "topology_id": "topology",
            "sentinel_flag": "false",
        }
    ]
    expanded = _apply_execution_policy_to_rows(
        rows,
        group_id="group",
        execution_policy={
            "repetitions_default": 3,
            "order_policy": "deterministic_shuffle",
            "shuffle_seed": 7,
        },
    )
    assert len(expanded) == 3
    assert {row["condition_id"] for row in expanded} == {"condition-a"}
    assert {row["instance_id"] for row in expanded} == {"same-instance"}
    assert {row["repetition_index"] for row in expanded} == {"0", "1", "2"}
    assert {row["run_order"] for row in expanded} == {"1", "2", "3"}


def test_explicit_schedule_orders_repetitions_without_changing_conditions() -> None:
    rows = [
        {
            "condition_id": f"condition-{cell}",
            "instance_id": f"instance-{cell}",
            "corpus_cell_id": cell,
            "corpus_id": "corpus",
            "dataset_profile_id": "dataset",
            "runtime_config_id": "default",
            "topology_id": "topology",
            "sentinel_flag": "false",
        }
        for cell in ("a", "b")
    ]
    schedule = [
        {"corpus_cell_id": "a", "repetition_index": 0},
        {"corpus_cell_id": "b", "repetition_index": 1},
        {"corpus_cell_id": "b", "repetition_index": 0},
        {"corpus_cell_id": "a", "repetition_index": 1},
    ]

    expanded = _apply_execution_policy_to_rows(
        rows,
        group_id="group",
        execution_policy={
            "repetitions_default": 2,
            "order_policy": "explicit_schedule",
            "explicit_schedule": schedule,
        },
    )

    assert [row["corpus_cell_id"] for row in expanded] == ["a", "b", "b", "a"]
    assert [row["repetition_index"] for row in expanded] == ["0", "1", "0", "1"]
    assert [row["run_order"] for row in expanded] == ["1", "2", "3", "4"]
    assert [row["condition_id"] for row in expanded] == [
        "condition-a",
        "condition-b",
        "condition-b",
        "condition-a",
    ]


def test_explicit_schedule_rejects_uncovered_rows() -> None:
    rows = [
        {
            "condition_id": "condition-a",
            "instance_id": "instance-a",
            "corpus_cell_id": "a",
            "corpus_id": "corpus",
            "dataset_profile_id": "dataset",
            "runtime_config_id": "default",
            "topology_id": "topology",
            "sentinel_flag": "false",
        }
    ]

    with pytest.raises(ValueError, match="does not cover every"):
        _apply_execution_policy_to_rows(
            rows,
            group_id="group",
            execution_policy={
                "repetitions_default": 2,
                "order_policy": "explicit_schedule",
                "explicit_schedule": [
                    {"corpus_cell_id": "a", "repetition_index": 0}
                ],
            },
        )


def test_smoke_selection_covers_strategies_wan_and_work_mem() -> None:
    selection = build_selection(_candidate_rows(), _memberships())
    smoke = build_smoke_selection(selection)
    assert len(smoke) == 6
    assert int(smoke["planned_repetitions"].sum()) == 6
    assert smoke["execution_strategy"].nunique() == 4
    assert smoke["network_profile_id"].ne("").any()
    assert smoke["runtime_config_id"].eq("work_mem_low").any()
