from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis/scripts/agent/103_representation_value_ablation.py"
CONTRACT = ROOT / "configs/validation/representation_value_ablation_v1.yml"


def load_module():
    specification = importlib.util.spec_from_file_location(
        "representation_value_ablation_103", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_contract_freezes_three_representations_and_common_policy() -> None:
    module = load_module()
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

    module._validate_contract(contract)

    assert set(contract["representations"]) == {
        "sql_structural",
        "coordinator_physical",
        "full_multilayer",
    }
    assert contract["decision_policy"]["neighbors"] == 5
    assert contract["decision_policy"]["coverage_quantile"] == 0.99
    assert contract["decision_policy"]["exclude_same_query_id"]
    assert contract["representations"]["full_multilayer"][
        "expected_active_features"
    ] == 64


def test_sql_structural_features_separate_query_shape_from_literals() -> None:
    module = load_module()
    sql = """
        select a.tenant_id, sum(a.value)
        from events a
        join tenants b on b.tenant_id = a.tenant_id
        where a.value = 10 and b.weight >= 20
        group by a.tenant_id
        order by sum(a.value) desc
        limit 5
    """
    changed_literals = sql.replace("10", "999").replace("20", "777").replace("5", "50")

    features = module.sql_structural_features(sql)
    changed = module.sql_structural_features(changed_literals)

    assert features == changed
    assert features["sql_join_count"] == 1
    assert features["sql_equality_predicate_count"] == 1
    assert features["sql_non_equality_predicate_count"] == 1
    assert features["sql_selection_predicate_count"] == 2
    assert features["sql_aggregate_function_count"] == 2
    assert features["sql_group_expression_count"] == 1
    assert features["sql_order_expression_count"] == 1
    assert features["sql_topk_present"] == 1


def test_structural_preprocessor_retains_constant_development_features() -> None:
    module = load_module()
    specifications = {
        "sql_join_count": {"family": "sql", "transform": "log1p"},
        "plan_join_operator_count": {"family": "plan", "transform": "log1p"},
    }
    reference = pd.DataFrame(
        {
            "sql_join_count": [0.0, 0.0, 0.0],
            "plan_join_operator_count": [0.0, 0.0, 0.0],
        }
    )
    unseen = pd.DataFrame(
        {"sql_join_count": [1.0], "plan_join_operator_count": [2.0]}
    )
    processor = module.StructuralPreprocessor(specifications)

    fitted = processor.fit(reference)
    transformed = processor.transform(unseen)

    assert fitted.shape == (3, 2)
    assert np.allclose(fitted, 0.0)
    assert np.linalg.norm(transformed) > 0
    assert processor.selection_audit["selected"].all()
    assert set(processor.selection_audit["decision"]) == {
        "retained_constant_for_unseen_structure"
    }


def test_summary_separates_abstention_from_top1_denominator() -> None:
    module = load_module()
    frame = pd.DataFrame(
        [
            {
                "representation": "test",
                "query_occurrence": 1,
                "predicted_action": "action-a",
                "top1_correct": True,
                "regret_log2": 0.0,
            },
            {
                "representation": "test",
                "query_occurrence": 1,
                "predicted_action": "",
                "top1_correct": False,
                "regret_log2": np.nan,
            },
        ]
    )

    summary = module._summarize(frame, "same_query_excluded")

    assert summary["episode_count"] == 2
    assert summary["recommendation_count"] == 1
    assert summary["abstention_count"] == 1
    assert summary["coverage"] == 0.5
    assert summary["top1_accuracy"] == 1.0


def test_neighbor_trace_marks_same_and_future_neighbors() -> None:
    module = load_module()
    timeline = pd.DataFrame(
        [
            {
                "representation": "test",
                "episode_id": "q1::run-2",
                "episode_order": 3,
                "query_id": "q1",
                "query_occurrence": 2,
                "neighbor_evidence_json": (
                    '[{"episode_id":"q1::run-1","query_id":"q1",'
                    '"distance":0.1,"weight":10.0,"action_gains":{}}]'
                ),
            }
        ]
    )
    events = pd.DataFrame(
        [
            {"episode_id": "q1::run-1", "episode_order": 1},
            {"episode_id": "q1::run-2", "episode_order": 3},
        ]
    )

    trace = module._expanded_neighbor_trace(timeline, events)

    assert bool(trace.iloc[0]["same_query_id"])
    assert not bool(trace.iloc[0]["future_or_current_neighbor"])


def test_cluster_bootstrap_keeps_query_repetitions_together() -> None:
    module = load_module()
    frame = pd.DataFrame(
        [
            {
                "query_id": query_id,
                "predicted_action": "action" if recommended else "",
                "top1_correct": correct,
                "regret_log2": regret,
            }
            for query_id, values in {
                "q1": [(True, True, 0.0), (True, True, 0.0)],
                "q2": [(False, False, np.nan), (False, False, np.nan)],
            }.items()
            for recommended, correct, regret in values
        ]
    )

    samples = module._cluster_metric_samples(frame, samples=100, seed=7)

    assert set(np.unique(samples["coverage"])) <= {0.0, 0.5, 1.0}
    assert np.nanmax(samples["top1_accuracy"]) == 1.0
