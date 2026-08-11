from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from master_regimes.corpus_adapter import render_corpus
from master_regimes.fuzzy_intervention_memory import (
    effective_sample_size,
    estimate_actions,
    fuzzy_episode_weights,
    fuzzy_transition_edges,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis/scripts/agent/101_fuzzy_intervention_memory.py"
PANEL_MANIFEST = (
    ROOT / "workloads/corpus/corpus_manifest.fuzzy-memory-topk-panel-v1.yml"
)


def load_script():
    specification = importlib.util.spec_from_file_location(
        "fuzzy_intervention_memory_analysis", SCRIPT
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_effective_sample_size_matches_uniform_support() -> None:
    assert effective_sample_size(np.ones(4)) == 4.0
    assert effective_sample_size(np.zeros(4)) == 0.0


def test_fuzzy_episode_weights_prefer_matching_context() -> None:
    query = np.asarray([0.9, 0.1])
    history = np.asarray([[0.85, 0.15], [0.1, 0.9]])

    weights = fuzzy_episode_weights(query, history, fuzzifier=1.7)

    assert weights[0] > weights[1]


def test_action_estimate_abstains_without_local_support() -> None:
    estimates = estimate_actions(
        query_membership=np.asarray([0.8, 0.2]),
        historical_memberships=np.asarray([[0.9, 0.1], [0.7, 0.3]]),
        historical_actions=["known", "known"],
        historical_gains=np.asarray([1.0, 2.0]),
        candidate_actions=["known", "unknown"],
        fuzzifier=1.7,
        minimum_observed_support=2,
        minimum_effective_support=1.5,
    )

    by_action = {estimate.action: estimate for estimate in estimates}
    assert by_action["known"].status == "available"
    assert np.isfinite(by_action["known"].prediction)
    assert by_action["unknown"].status == "insufficient_local_evidence"
    assert np.isnan(by_action["unknown"].prediction)


def test_transition_graph_preserves_action_and_context_direction() -> None:
    edges = fuzzy_transition_edges(
        before_memberships=np.asarray([[0.9, 0.1], [0.8, 0.2]]),
        after_memberships=np.asarray([[0.1, 0.9], [0.2, 0.8]]),
        actions=["rewrite", "rewrite"],
        gains=np.asarray([2.0, 1.5]),
        fuzzifier=1.7,
    )

    dominant = edges.sort_values("transition_weight", ascending=False).iloc[0]
    assert dominant["action"] == "rewrite"
    assert dominant["source_context"] == 0
    assert dominant["destination_context"] == 1
    assert 1.5 <= dominant["gain_weighted_mean"] <= 2.0


def _synthetic_episodes() -> pd.DataFrame:
    rows = []
    actions = ["action-a", "action-b"]
    for scenario_index in range(6):
        for action_index, action in enumerate(actions):
            rows.append(
                {
                    "source_id": "synthetic",
                    "scenario_id": f"scenario-{scenario_index}",
                    "base_scenario_id": f"scenario-{scenario_index}",
                    "component_match_id": "component",
                    "logical_question_id": "question",
                    "dataset_profile_id": "dataset",
                    "baseline_condition_id": f"before-{scenario_index}",
                    "action_condition_id": f"after-{scenario_index}-{action_index}",
                    "mitigation_action": action,
                    "baseline_elapsed_median": 10.0,
                    "action_elapsed_median": 5.0,
                    "target_log2_gain": float(
                        scenario_index if action == "action-a" else 5 - scenario_index
                    ),
                    "completed": True,
                    "result_equal": True,
                    "episode_available_at_unix": float(100 + scenario_index),
                    "before__f1": float(scenario_index),
                    "before__f2": float(scenario_index % 2),
                    "after__f1": float(999 + action_index),
                    "after__f2": float(-999 - action_index),
                }
            )
    return pd.DataFrame(rows)


def test_loso_predictions_do_not_use_after_action_state() -> None:
    module = load_script()
    episodes = _synthetic_episodes()
    specifications = {
        "f1": {"family": "one", "transform": "identity"},
        "f2": {"family": "two", "transform": "identity"},
    }
    state_contract = {
        "pca_components": 2,
        "minimum_active_features": 2,
    }
    memory = {
        "fuzzifier": 1.7,
        "primary_k": 2,
        "minimum_scenarios_per_context": 2,
        "seeds": [11, 29],
        "minimum_observed_support": 2,
        "minimum_effective_support": 1.0,
        "knn_neighbors": 3,
        "distance_epsilon": 0.000001,
    }

    first, _, _ = module.evaluate_panel(
        episodes,
        panel_name="synthetic",
        actions=["action-a", "action-b"],
        specifications=specifications,
        state_contract=state_contract,
        memory=memory,
        random_seed=42,
    )
    changed = episodes.copy()
    changed["after__f1"] *= -1000
    changed["after__f2"] *= 1000
    second, _, _ = module.evaluate_panel(
        changed,
        panel_name="synthetic",
        actions=["action-a", "action-b"],
        specifications=specifications,
        state_contract=state_contract,
        memory=memory,
        random_seed=42,
    )

    columns = [
        "prediction_action_median",
        "prediction_knn",
        "prediction_kmeans_hard_memory",
        "prediction_fcm_soft_memory",
    ]
    np.testing.assert_allclose(first[columns], second[columns])


def test_state_preprocessor_records_feature_selection_reasons() -> None:
    module = load_script()
    frame = pd.DataFrame(
        {
            "before__varying": [1.0, 2.0, 3.0],
            "before__constant": [4.0, 4.0, 4.0],
            "before__missing": [np.nan, np.nan, np.nan],
        }
    )
    specifications = {
        name: {"family": "test", "transform": "identity"}
        for name in ("varying", "constant", "missing")
    }
    processor = module.StatePreprocessor(
        specifications=specifications,
        pca_components=1,
        minimum_active_features=1,
    )

    processor.fit(frame)

    assert processor.active_features == ["varying"]
    assert processor.selection_audit is not None
    decisions = processor.selection_audit.set_index("feature")["decision"].to_dict()
    assert decisions == {
        "varying": "selected",
        "constant": "constant",
        "missing": "all_missing",
    }


def test_gain_uses_median_condition_times() -> None:
    module = load_script()
    conditions = pd.DataFrame(
        [
            {
                "source_id": "source",
                "condition_id": "before",
                "scenario_id": "scenario",
                "base_scenario_id": "scenario",
                "component_match_id": "component",
                "logical_question_id": "question",
                "dataset_profile_id": "dataset",
                "variant": "stressed",
                "mitigation_action": "",
                    "completed_count": 3,
                    "elapsed_median": 8.0,
                    "condition_started_at_unix": 10.0,
                    "condition_finished_at_unix": 11.0,
                    "result_multiset_sha256": "same",
            },
            {
                "source_id": "source",
                "condition_id": "after",
                "scenario_id": "scenario",
                "base_scenario_id": "scenario",
                "component_match_id": "component",
                "logical_question_id": "question",
                "dataset_profile_id": "dataset",
                "variant": "mitigated",
                "mitigation_action": "action",
                    "completed_count": 3,
                    "elapsed_median": 2.0,
                    "condition_started_at_unix": 12.0,
                    "condition_finished_at_unix": 13.0,
                    "result_multiset_sha256": "same",
            },
        ]
    )

    gains = module.build_gain_rows(conditions, repetitions_per_condition=3)

    assert len(gains) == 1
    assert gains.iloc[0]["target_log2_gain"] == 2.0
    assert gains.iloc[0]["completed"]
    assert gains.iloc[0]["result_equal"]
    assert gains.iloc[0]["episode_available_at_unix"] == 13.0


def test_prequential_predictions_use_only_earlier_scenarios() -> None:
    module = load_script()
    episodes = _synthetic_episodes()
    specifications = {
        "f1": {"family": "one", "transform": "identity"},
        "f2": {"family": "two", "transform": "identity"},
    }
    state_contract = {
        "pca_components": 2,
        "minimum_active_features": 2,
    }
    memory = {
        "fuzzifier": 1.7,
        "primary_k": 2,
        "minimum_scenarios_per_context": 2,
        "seeds": [11, 29],
        "minimum_observed_support": 2,
        "minimum_effective_support": 1.0,
        "knn_neighbors": 3,
        "distance_epsilon": 0.000001,
    }

    first = module.evaluate_prequential_panel(
        episodes,
        panel_name="synthetic",
        actions=["action-a", "action-b"],
        specifications=specifications,
        state_contract=state_contract,
        memory=memory,
        random_seed=42,
    )
    changed = episodes.copy()
    changed.loc[changed["scenario_id"].eq("scenario-5"), "target_log2_gain"] += 1000
    second = module.evaluate_prequential_panel(
        changed,
        panel_name="synthetic",
        actions=["action-a", "action-b"],
        specifications=specifications,
        state_contract=state_contract,
        memory=memory,
        random_seed=42,
    )

    columns = [f"prediction_{model}" for model in module.PREQUENTIAL_MODELS]
    np.testing.assert_allclose(
        first[columns],
        second[columns],
        equal_nan=True,
    )
    history = first.groupby("prequential_step")["history_scenario_count"].first()
    assert history.to_dict() == {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}
    assert first[first["prequential_step"].eq(1)][
        "prequential_status_action_median"
    ].eq("cold_start").all()
    assert first[first["prequential_step"].eq(2)][
        "prequential_status_action_median"
    ].eq("available").all()
    for row in first.to_dict(orient="records"):
        evidence = json.loads(row["knn_neighbor_evidence_json"])
        assert all(
            neighbor["scenario_id"] != row["scenario_id"]
            for neighbor in evidence
        )
        assert all(
            neighbor["scenario_id"] != "scenario-5"
            for neighbor in evidence
            if row["prequential_step"] < 6
        )

    summary, _, _ = module.summarize_prequential_predictions(first)
    assert set(summary["evaluation_scope"]) == {"own_available", "fcm_matched"}
    matched = summary[summary["evaluation_scope"].eq("fcm_matched")]
    assert matched["predicted_scenario_count"].nunique() == 1
    assert matched["evaluation_scenario_count"].nunique() == 1
    assert matched["coverage"].eq(1.0).all()
    own = summary[summary["evaluation_scope"].eq("own_available")].set_index("model")
    assert own.loc["action_median", "cold_start_scenario_count"] == 1
    assert own.loc["action_median", "initial_abstention_scenario_count"] == 1


def test_knn_does_not_impute_unseen_action() -> None:
    module = load_script()
    predictions = module._knn_action_estimates(
        train_values=np.asarray([[0.0], [1.0]]),
        test_value=np.asarray([0.25]),
        train_scenarios=["scenario-1", "scenario-2"],
        train_episodes=pd.DataFrame(
            [
                {
                    "scenario_id": "scenario-1",
                    "mitigation_action": "known",
                    "target_log2_gain": 1.0,
                },
                {
                    "scenario_id": "scenario-2",
                    "mitigation_action": "known",
                    "target_log2_gain": 2.0,
                },
            ]
        ),
        actions=["known", "unseen"],
        neighbors=2,
        epsilon=0.000001,
    )

    assert np.isfinite(predictions["known"])
    assert np.isnan(predictions["unseen"])


def test_topk_panel_renders_complete_cross_action_matrix(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=PANEL_MANIFEST,
        output_dir=tmp_path / "fuzzy-memory-topk-panel",
    )
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    manifests = []
    for group in plan["groups"]:
        path = Path(group["instance_manifest"])
        manifests.append(
            pd.read_csv(path if path.is_absolute() else ROOT.parent / path)
        )
    rows = pd.concat(manifests, ignore_index=True)

    assert len(rows) == 288
    assert rows["condition_id"].nunique() == 96
    assert rows["component_match_id"].nunique() == 3
    assert rows["dataset_profile_id"].nunique() == 2
    assert rows.groupby("condition_id").size().eq(3).all()

    rows["scenario_id"] = (
        rows["component_match_id"].astype(str)
        + "::"
        + rows["dataset_profile_id"].astype(str)
        + "::"
        + rows["param_json"].map(lambda value: module_json(value))
    )
    for _, group in rows.groupby("scenario_id"):
        conditions = group.drop_duplicates("condition_id")
        assert len(conditions) == 4
        assert conditions["variant"].eq("stressed").sum() == 1
        assert set(
            conditions.loc[
                conditions["mitigation_action"].notna(), "mitigation_action"
            ]
        ) == {
            "increase_gac_work_mem",
            "regional_topk_candidates",
            "mitigate_remote_path_bundle",
        }


def module_json(value: str) -> str:
    return json.dumps(json.loads(value), sort_keys=True, separators=(",", ":"))
