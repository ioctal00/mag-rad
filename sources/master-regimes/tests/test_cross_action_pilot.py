from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from master_regimes.corpus_adapter import render_corpus

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workloads/corpus/corpus_manifest.cross-action-pilot-v1.yml"


def load_module():
    path = ROOT / "analysis/scripts/agent/99_cross_action_pilot.py"
    spec = importlib.util.spec_from_file_location("cross_action_pilot", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_diff_ignores_profile_identity() -> None:
    module = load_module()
    before = {
        "pg_options": {"work_mem": "64kB"},
        "network_profile": {"id": "before", "configured_delay_ms": 30},
    }
    after = {
        "pg_options": {"work_mem": "64kB"},
        "network_profile": {"id": "after", "configured_delay_ms": 0},
    }

    assert module.changed_runtime_fields(before, after) == {
        "network_profile.configured_delay_ms"
    }


def test_rank_reversal_count_requires_opposite_orderings() -> None:
    module = load_module()
    gains = pd.DataFrame(
        [
            {"scenario_id": "a", "mitigation_action": "x", "target_log2_gain": 2.0},
            {"scenario_id": "a", "mitigation_action": "y", "target_log2_gain": 1.0},
            {"scenario_id": "b", "mitigation_action": "x", "target_log2_gain": 0.0},
            {"scenario_id": "b", "mitigation_action": "y", "target_log2_gain": 3.0},
        ]
    )

    _, reversal_count = module.count_rank_reversals(gains)

    assert reversal_count == 1


def test_action_conditioned_matrix_changes_feature_effect_by_action() -> None:
    module = load_module()
    values = np.array([[1.0, 2.0], [1.0, 2.0]])
    actions = pd.Series(["a", "b"])

    matrix = module.action_conditioned_matrix(values, actions, ["a", "b"])

    assert matrix.shape == (2, 8)
    assert not np.array_equal(matrix[0], matrix[1])


def test_condition_summary_ignores_missing_result_signatures() -> None:
    module = load_module()
    rows = pd.DataFrame(
        [
            {
                "condition_id": "condition-a",
                "scenario_id": "scenario-a",
                "component_match_id": "component-a",
                "logical_question_id": "question-a",
                "dataset_profile_id": "dataset-a",
                "template_id": "template-a",
                "variant": "stressed",
                "mitigation_action": np.nan,
                "execution_status": "completed",
                "elapsed_seconds": 1.0,
                "result_multiset_sha256": "hash-a",
            },
            {
                "condition_id": "condition-a",
                "scenario_id": "scenario-a",
                "component_match_id": "component-a",
                "logical_question_id": "question-a",
                "dataset_profile_id": "dataset-a",
                "template_id": "template-a",
                "variant": "stressed",
                "mitigation_action": np.nan,
                "execution_status": "completed",
                "elapsed_seconds": 1.1,
                "result_multiset_sha256": np.nan,
            },
        ]
    )

    summary = module.condition_summary(rows)

    assert summary.loc[0, "signature_count"] == 1
    assert summary.loc[0, "result_multiset_sha256"] == "hash-a"
    assert summary.loc[0, "mitigation_action"] == ""


def test_repeat_ranking_stability_uses_common_baseline_per_repetition() -> None:
    module = load_module()
    rows = []
    for repetition, baseline, action_a, action_b, action_c in (
        (0, 8.0, 2.0, 4.0, 7.0),
        (1, 9.0, 3.0, 4.5, 8.0),
        (2, 10.0, 2.5, 5.0, 9.0),
    ):
        rows.extend(
            [
                {
                    "scenario_id": "scenario-a",
                    "repetition_index": repetition,
                    "variant": "stressed",
                    "mitigation_action": "",
                    "elapsed_seconds": baseline,
                },
                {
                    "scenario_id": "scenario-a",
                    "repetition_index": repetition,
                    "variant": "mitigated",
                    "mitigation_action": "action-a",
                    "elapsed_seconds": action_a,
                },
                {
                    "scenario_id": "scenario-a",
                    "repetition_index": repetition,
                    "variant": "mitigated",
                    "mitigation_action": "action-b",
                    "elapsed_seconds": action_b,
                },
                {
                    "scenario_id": "scenario-a",
                    "repetition_index": repetition,
                    "variant": "mitigated",
                    "mitigation_action": "action-c",
                    "elapsed_seconds": action_c,
                },
            ]
        )

    detail, summary = module.repeat_ranking_stability(pd.DataFrame(rows))

    assert len(detail) == 3
    assert summary.loc[0, "all_rankings_equal"]
    assert summary.loc[0, "all_top_actions_equal"]
    assert detail["ranking"].eq("action-a>action-b>action-c").all()


def test_paired_bootstrap_compares_same_scenarios() -> None:
    module = load_module()
    metrics = pd.DataFrame(
        [
            {
                "model": "baseline",
                "scenario_id": "a",
                "pairwise_accuracy": 1.0,
                "regret": 0.0,
            },
            {
                "model": "baseline",
                "scenario_id": "b",
                "pairwise_accuracy": 1.0,
                "regret": 0.0,
            },
            {
                "model": "candidate",
                "scenario_id": "a",
                "pairwise_accuracy": 1.0,
                "regret": 0.0,
            },
            {
                "model": "candidate",
                "scenario_id": "b",
                "pairwise_accuracy": 0.0,
                "regret": 2.0,
            },
        ]
    )

    result = module.paired_bootstrap_comparison(
        metrics,
        baseline_model="baseline",
        candidate_model="candidate",
        samples=100,
        seed=42,
    )

    assert result["scenario_count"] == 2
    assert result["pairwise_accuracy_delta_mean"] == -0.5
    assert result["regret_delta_mean"] == 1.0


def test_pilot_limits_collection_to_active_regions(tmp_path: Path) -> None:
    plan_path = render_corpus(
        manifest_path=MANIFEST,
        output_dir=tmp_path / "cross-action-pilot",
    )
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

    assert plan["group_count"] == 4
    assert sum(group["instance_count"] for group in plan["groups"]) == 144

    for group in plan["groups"]:
        sweep_path = ROOT.parent / group["sweep_config"]
        sweep = yaml.safe_load(sweep_path.read_text(encoding="utf-8"))
        manifest_path = ROOT.parent / sweep["workload"]["instance_manifest"]
        instances = pd.read_csv(manifest_path, keep_default_na=False)
        configured_runtimes = {
            str(runtime["id"]) for runtime in sweep["runtime_configs"]
        }
        expected = (
            ["eu", "us"] if "multiregion_union" in group["strategies"] else ["eu"]
        )
        assert sweep["workload"]["filter_instances_by_runtime_config"] is True
        assert set(instances["runtime_config_id"].astype(str)) == configured_runtimes
        assert instances.groupby("runtime_config_id").size().gt(0).all()
        assert sweep["collection"]["os_sampler_node_groups"] == expected
        assert sweep["collection"]["fdw_auto_explain_regions"] == expected
