from __future__ import annotations

from master_regimes.extract.plan_structure import (
    finalize_plan_structure_rows,
    plan_structure_feature_row,
)


def test_plan_structure_counts_shape_depth_and_transitions() -> None:
    base = {
        "query_sweep_id": "sweep-1",
        "query_run_id": "run-1",
        "instance_id": "instance-1",
        "template_id": "template-1",
    }
    row = plan_structure_feature_row(
        **base,
        plan_nodes=[
            {
                **base,
                "plan_scope": "main",
                "plan_id": "main",
                "node_id": 1,
                "depth": 0,
                "node_type": "Aggregate",
                "actual_total_time": 10,
                "actual_rows": 5,
            },
            {
                **base,
                "plan_scope": "main",
                "plan_id": "main",
                "node_id": 2,
                "parent_node_id": 1,
                "depth": 1,
                "node_type": "Foreign Scan",
                "actual_total_time": 30,
                "actual_rows": 100,
            },
            {
                **base,
                "plan_scope": "fdw_remote",
                "plan_id": "remote",
                "node_id": 1,
                "depth": 0,
                "node_type": "Hash Join",
                "actual_total_time": 60,
                "actual_rows": 200,
            },
            {
                **base,
                "plan_scope": "fdw_remote",
                "plan_id": "remote",
                "node_id": 2,
                "parent_node_id": 1,
                "depth": 1,
                "node_type": "Aggregate",
                "actual_total_time": 20,
                "actual_rows": 50,
            },
        ],
        plan_edges=[
            {
                **base,
                "plan_scope": "main",
                "plan_id": "main",
                "parent_node_id": 1,
                "child_node_id": 2,
                "parent_node_type": "Aggregate",
                "child_node_type": "Foreign Scan",
            },
            {
                **base,
                "plan_scope": "fdw_remote",
                "plan_id": "remote",
                "parent_node_id": 1,
                "child_node_id": 2,
                "parent_node_type": "Hash Join",
                "child_node_type": "Aggregate",
            }
        ],
    )

    assert row["main_plan_node_count"] == 2
    assert row["main_plan_max_depth"] == 1
    assert row["main_plan_leaf_count"] == 1
    assert row["main_plan_branch_node_count"] == 1
    assert row["main_plan_avg_branching_factor"] == 1.0
    assert row["remote_plan_leaf_count_sum"] == 1
    assert row["remote_plan_avg_branching_factor"] == 1.0
    assert row["aggregate_min_depth"] == 0
    assert row["foreign_scan_max_depth"] == 1
    assert row["aggregate_above_foreign_scan"] == "true"
    assert row["foreign_scan_under_aggregate"] == "true"
    assert row["sort_above_foreign_scan"] == "false"
    assert row["remote_aggregate_present"] == "true"
    assert row["remote_join_present"] == "true"
    assert row["main_finalize_after_remote"] == "true"
    assert row["blocking_operator_count"] == 3
    assert row["blocking_operator_min_depth"] == 0
    assert row["blocking_operator_above_remote_count"] == 1
    assert row["blocking_operator_below_remote_count"] == 2
    assert row["first_blocking_operator_type"] == "Aggregate"
    assert row["first_blocking_operator_depth"] == 0
    assert row["dominant_time_node_type"] == "Hash Join"
    assert row["dominant_time_node_depth"] == 0
    assert row["dominant_time_node_actual_time_share"] == 0.5
    assert row["dominant_rows_node_type"] == "Hash Join"
    assert row["dominant_rows_node_depth"] == 0
    assert row["dominant_rows_node_row_share"] == 200 / 355
    assert row["parent_child_type_count_Aggregate_ForeignScan"] == 1
    assert row["parent_child_type_count_HashJoin_Aggregate"] == 1


def test_plan_structure_finalize_sets_missing_transition_counts_to_zero() -> None:
    row_a = {
        "query_run_id": "a",
        "main_plan_node_count": 1,
        "parent_child_type_count_Aggregate_ForeignScan": 1,
    }
    row_b = {
        "query_run_id": "b",
        "main_plan_node_count": 1,
        "parent_child_type_count_Limit_Sort": 1,
    }

    fieldnames = finalize_plan_structure_rows([row_a, row_b])

    assert "parent_child_type_count_Aggregate_ForeignScan" in fieldnames
    assert "parent_child_type_count_Limit_Sort" in fieldnames
    assert row_a["parent_child_type_count_Limit_Sort"] == 0
    assert row_b["parent_child_type_count_Aggregate_ForeignScan"] == 0
