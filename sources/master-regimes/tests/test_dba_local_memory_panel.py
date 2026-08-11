from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis/scripts/agent/102_dba_local_memory_panel.py"
CONTRACT = ROOT / "configs/validation/dba_local_memory_panel_v1.yml"


def load_module():
    specification = importlib.util.spec_from_file_location("dba_memory_102", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_manifest_has_fifteen_queries_and_180_executions() -> None:
    module = load_module()
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

    manifest, design = module.build_manifest(contract)

    assert len(design) == 15
    assert design["query_shape"].nunique() == 15
    assert design["physical_execution_count"].sum() == 180
    assert design["repetitions"].sum() == 45
    assert set(design["region_count"]) == {2, 3}
    assert len(manifest["cells"]) == 60


def test_every_query_has_shared_baseline_and_three_actions() -> None:
    module = load_module()
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    manifest, _ = module.build_manifest(contract)

    for scenario in contract["scenarios"]:
        query_id = scenario["query_id"]
        cells = [
            cell
            for cell in manifest["cells"]
            if cell["component_match_id"] == f"dba_memory_{query_id}"
        ]
        assert len(cells) == 4
        assert sum(cell["variant"] == "stressed" for cell in cells) == 1
        assert {
            cell.get("mitigation_action", "") for cell in cells if cell["variant"] == "mitigated"
        } == set(module.ACTIONS)
        assert {cell["repeatability_repetitions"] for cell in cells} == {scenario["repetitions"]}


def test_recommendation_is_withheld_until_evidence_is_available() -> None:
    module = load_module()
    predictions = {
        "increase_gac_work_mem": 0.1,
        "regional_topk_candidates": 1.2,
        "mitigate_remote_path_bundle": 0.4,
    }

    candidate, recommendation = module._decision_actions(predictions, "outside_reference_coverage")
    assert candidate == "regional_topk_candidates"
    assert recommendation == ""

    candidate, recommendation = module._decision_actions(predictions, "available")
    assert candidate == "regional_topk_candidates"
    assert recommendation == "regional_topk_candidates"

    candidate, recommendation = module._decision_actions(
        predictions,
        "available",
        ("increase_gac_work_mem", "mitigate_remote_path_bundle"),
    )
    assert candidate == "mitigate_remote_path_bundle"
    assert recommendation == "mitigate_remote_path_bundle"


def test_supported_distance_metrics_have_expected_geometry() -> None:
    module = load_module()
    left = np.asarray([[1.0, 0.0]])
    right = np.asarray([[1.0, 0.0], [0.0, 1.0]])

    assert np.allclose(module._distance_matrix(left, right, "euclidean"), [[0.0, 2**0.5]])
    assert np.allclose(module._distance_matrix(left, right, "manhattan"), [[0.0, 2.0]])
    assert np.allclose(module._distance_matrix(left, right, "cosine"), [[0.0, 1.0]])


def test_memory_analysis_module_loads_with_dataclass_metadata() -> None:
    module = load_module()

    memory_module = module._load_memory_module()

    assert memory_module.StatePreprocessor.__module__ == "memory_analysis_101"


def test_markdown_report_does_not_require_optional_tabulate_dependency() -> None:
    module = load_module()
    frame = pd.DataFrame([{"action": "a|b", "gain": 1.25}])

    rendered = module._markdown_table(frame, ["action", "gain"])

    assert "a\\|b" in rendered
    assert "1.250" in rendered


def test_json_encoder_normalizes_numpy_scalars() -> None:
    module = load_module()

    rendered = json.dumps(
        {"ok": np.bool_(True), "count": np.int64(3)},
        default=module._json_default,
    )

    assert json.loads(rendered) == {"ok": True, "count": 3}


def test_cross_query_estimator_excludes_same_normalized_sql_neighbors() -> None:
    module = load_module()
    states = pd.DataFrame(
        [
            {
                "episode_id": "e1",
                "query_id": "q1",
                "normalized_sql_hash": "sql-1",
                "topology_id": "n2",
            },
            {
                "episode_id": "e2",
                "query_id": "q2",
                "normalized_sql_hash": "sql-2",
                "topology_id": "n2",
            },
            {
                "episode_id": "e3",
                "query_id": "q3-alias",
                "normalized_sql_hash": "sql-1",
                "topology_id": "n2",
            },
        ]
    )
    outcomes = pd.DataFrame(
        [
            {
                "episode_id": episode,
                "mitigation_action": action,
                "target_log2_gain": gain,
            }
            for episode, gains in (
                ("e1", (0.0, 0.0, 3.0)),
                ("e2", (0.0, 2.0, 0.0)),
                ("e3", (0.0, 0.0, 4.0)),
            )
            for action, gain in zip(module.ACTIONS, gains, strict=True)
        ]
    )

    predictions, neighbors, nearest, eligible_count = module._estimate_from_memory(
        np.asarray([0.1]),
        np.asarray([[0.0], [10.0], [0.05]]),
        states,
        outcomes,
        neighbors=1,
        epsilon=1e-9,
        excluded_query_id="q1",
        excluded_normalized_sql_hash="sql-1",
    )

    assert eligible_count == 1
    assert nearest == 9.9
    assert [row["query_id"] for row in neighbors] == ["q2"]
    assert max(predictions, key=predictions.get) == "regional_topk_candidates"


def test_exact_query_memory_abstains_then_uses_only_identical_sql() -> None:
    module = load_module()
    events = pd.DataFrame(
        [
            {
                "episode_id": "q1::run-1",
                "episode_order": 1,
                "query_id": "q1",
                "query_shape": "shape-1",
                "query_occurrence": 1,
                "planned_query_occurrences": 2,
                "topology_id": "n2",
                "region_count": 2,
                "dataset_profile_id": "d1",
                "profile": "p1",
                "baseline_elapsed_seconds": 10.0,
                "normalized_sql_hash": "sql-1",
            },
            {
                "episode_id": "q2::run-1",
                "episode_order": 2,
                "query_id": "q2",
                "query_shape": "shape-2",
                "query_occurrence": 1,
                "planned_query_occurrences": 1,
                "topology_id": "n2",
                "region_count": 2,
                "dataset_profile_id": "d1",
                "profile": "p1",
                "baseline_elapsed_seconds": 10.0,
                "normalized_sql_hash": "sql-2",
            },
            {
                "episode_id": "q1::run-2",
                "episode_order": 3,
                "query_id": "q1",
                "query_shape": "shape-1",
                "query_occurrence": 2,
                "planned_query_occurrences": 2,
                "topology_id": "n2",
                "region_count": 2,
                "dataset_profile_id": "d1",
                "profile": "p1",
                "baseline_elapsed_seconds": 10.0,
                "normalized_sql_hash": "sql-1",
            },
        ]
    )
    gains = {
        "q1::run-1": (0.0, 2.0, 1.0),
        "q2::run-1": (0.0, 0.5, 3.0),
        "q1::run-2": (0.0, 2.1, 1.0),
    }
    outcomes = pd.DataFrame(
        [
            {
                "episode_id": episode_id,
                "mitigation_action": action,
                "target_log2_gain": gain,
            }
            for episode_id, values in gains.items()
            for action, gain in zip(module.ACTIONS, values, strict=True)
        ]
    )

    timeline = module.replay_exact_query_memory(events, outcomes)

    assert timeline.loc[0, "decision_status"] == "exact_query_unseen"
    assert timeline.loc[0, "predicted_action"] == ""
    assert timeline.loc[1, "predicted_action"] == ""
    assert timeline.loc[2, "same_query_history_count_before"] == 1
    assert timeline.loc[2, "predicted_action"] == "regional_topk_candidates"
    assert bool(timeline.loc[2, "top1_correct"])


def test_exact_query_memory_requires_compatible_context() -> None:
    module = load_module()
    events = pd.DataFrame(
        [
            {
                "episode_id": f"q1::run-{order}",
                "episode_order": order,
                "query_id": "q1",
                "query_shape": "shape-1",
                "query_occurrence": order,
                "planned_query_occurrences": 3,
                "topology_id": "n2",
                "region_count": 2,
                "dataset_profile_id": "d1",
                "profile": profile,
                "baseline_elapsed_seconds": 10.0,
                "normalized_sql_hash": "sql-1",
            }
            for order, profile in ((1, "p1"), (2, "p2"), (3, "p2"))
        ]
    )
    outcomes = pd.DataFrame(
        [
            {
                "episode_id": episode_id,
                "mitigation_action": action,
                "target_log2_gain": gain,
            }
            for episode_id in events["episode_id"]
            for action, gain in zip(module.ACTIONS, (0.0, 2.0, 1.0), strict=True)
        ]
    )

    timeline = module.replay_exact_query_memory(events, outcomes)

    assert timeline.loc[0, "decision_status"] == "exact_query_unseen"
    assert timeline.loc[1, "decision_status"] == "exact_query_context_unseen"
    assert timeline.loc[1, "same_sql_history_count_before"] == 1
    assert timeline.loc[1, "same_query_history_count_before"] == 0
    assert timeline.loc[2, "decision_status"] == "available"
    assert timeline.loc[2, "predicted_action"] == "regional_topk_candidates"


def test_hierarchical_policy_prefers_exact_memory_and_falls_back_to_knn() -> None:
    module = load_module()
    timeline = pd.DataFrame(
        [
            {
                "memory_mode": "exact_query_memory",
                "episode_id": "e1",
                "episode_order": 1,
                "predicted_action": "",
            },
            {
                "memory_mode": "exact_query_memory",
                "episode_id": "e2",
                "episode_order": 2,
                "predicted_action": "regional_topk_candidates",
            },
            {
                "memory_mode": "warm_start_cross_query",
                "episode_id": "e1",
                "episode_order": 1,
                "predicted_action": "mitigate_remote_path_bundle",
            },
            {
                "memory_mode": "warm_start_cross_query",
                "episode_id": "e2",
                "episode_order": 2,
                "predicted_action": "mitigate_remote_path_bundle",
            },
        ]
    )

    result = module.build_hierarchical_timeline(
        timeline,
        cross_query_mode="warm_start_cross_query",
        output_mode="hierarchical_warm_start",
    )

    assert result["predicted_action"].tolist() == [
        "mitigate_remote_path_bundle",
        "regional_topk_candidates",
    ]
    assert result["decision_route"].tolist() == [
        "cross_query_knn",
        "exact_query_memory",
    ]


def test_matched_first_occurrence_comparison_uses_identical_episode_set() -> None:
    module = load_module()
    rows = []
    actuals = [
        "mitigate_remote_path_bundle",
        "regional_topk_candidates",
    ]
    for order, actual in enumerate(actuals, start=1):
        gains = {action: 0.0 for action in module.ACTIONS}
        gains[actual] = 2.0
        rows.append(
            {
                "memory_mode": "warm_start_cross_query",
                "episode_id": f"e{order}",
                "episode_order": order,
                "query_occurrence": 1,
                "predicted_action": actual,
                "actual_best_action": actual,
                "top1_correct": True,
                "regret_log2": 0.0,
                **{f"actual_gain__{action}": gain for action, gain in gains.items()},
            }
        )
    reference = pd.DataFrame(
        [
            {
                "mitigation_action": action,
                "target_log2_gain": gain,
            }
            for action, gain in zip(module.ACTIONS, (0.0, 1.0, 3.0), strict=True)
        ]
    )

    comparison, details = module._matched_first_occurrence_comparison(
        pd.DataFrame(rows), reference
    )

    assert set(comparison["episode_count"]) == {2}
    assert comparison.set_index("method").loc[
        "knn_warm_start_excluding_same_query", "top1_correct_count"
    ] == 2
    assert details["knn_only_correct_count"] == 1
    assert details["static_only_correct_count"] == 0
