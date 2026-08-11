from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from master_regimes.corpus_adapter import render_corpus
from master_regimes.corpus_manifest import validate_corpus_manifest
from master_regimes.dataset_profile import validate_dataset_profile

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
MANIFEST = (
    ROOT / "workloads/corpus/pressure-raw-v1/batch-300-n3-colocation-holdout.yml"
)
PROFILES = (
    "n3-medium-balanced-wide-global-dim.yml",
    "n3-medium-apac-dominant-wide-global-dim.yml",
    "n3-large-balanced-wide-global-dim.yml",
    "n3-large-apac-dominant-wide-global-dim.yml",
)


def workspace_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else WORKSPACE / path


def load_freeze_module():
    path = ROOT / "analysis/scripts/agent/96_freeze_n3_colocation_holdout.py"
    spec = importlib.util.spec_from_file_location("freeze_n3", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_analysis_module():
    path = ROOT / "analysis/scripts/agent/97_n3_colocation_no_refit.py"
    spec = importlib.util.spec_from_file_location("analyze_n3", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_n3_dataset_profiles_validate_for_all_regions() -> None:
    for file_name in PROFILES:
        path = ROOT / "datasets/profiles" / file_name
        for region in ("eu", "us", "apac"):
            result = validate_dataset_profile(path, region=region)
            assert result["status"] == "ok", (file_name, region, result["errors"])


def test_n3_manifest_expands_to_frozen_96_execution_design(tmp_path: Path) -> None:
    validation = validate_corpus_manifest(MANIFEST)
    assert validation["status"] == "ok", validation["errors"]
    assert validation["source_cell_count"] == 8
    assert validation["cell_count"] == 32

    plan_path = render_corpus(manifest_path=MANIFEST, output_dir=tmp_path)
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    design = load_freeze_module().validate_rendered_plan(plan)

    assert design["execution_count"] == 96
    assert design["condition_count"] == 32
    assert design["pair_count"] == 16
    assert design["dataset_count"] == 4
    assert design["template_count"] == 8
    assert design["regions"] == ["eu", "us", "apac"]


def test_n3_sweeps_keep_one_global_execution_and_three_edges(tmp_path: Path) -> None:
    plan_path = render_corpus(manifest_path=MANIFEST, output_dir=tmp_path)
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    assert len(plan["groups"]) == 4

    for group in plan["groups"]:
        sweep = yaml.safe_load(
            workspace_path(str(group["sweep_config"])).read_text(encoding="utf-8")
        )
        assert sweep["collection"]["target_group"] == "analytics_clients"
        assert sweep["execution_policy"]["query_concurrency"] == 1
        assert sweep["datasets"][0]["regions"] == ["eu", "us", "apac"]
        assert sweep["collection"]["fdw_bootstrap"]["regions"] == [
            "eu",
            "us",
            "apac",
        ]
        assert sweep["collection"]["fdw_auto_explain_regions"] == [
            "eu",
            "us",
            "apac",
        ]

        rows: list[dict[str, str]]
        with workspace_path(str(group["instance_manifest"])).open(
            newline="", encoding="utf-8"
        ) as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 24
        for row in rows:
            sql = workspace_path(row["rendered_sql_path"]).read_text(encoding="utf-8")
            assert "fdw_eu." in sql
            assert "fdw_us." in sql
            assert "fdw_apac." in sql


def test_n3_pair_matrix_uses_three_repetitions_per_variant() -> None:
    module = load_analysis_module()
    observed_rows = []
    execution_rows = []
    for pair_index in range(16):
        for variant in ("stressed", "mitigated"):
            for repetition in range(3):
                query_run_id = f"q-{pair_index}-{variant}-{repetition}"
                observed_rows.append(
                    {
                        "pair_id": f"pair-{pair_index}",
                        "variant": variant,
                        "query_run_id": query_run_id,
                        "elapsed_seconds": (
                            8.0 + pair_index if variant == "stressed" else 2.0
                        ),
                        "dataset_profile_id": "n3-medium-balanced-v1",
                        "logical_question_id_frozen": f"question-{pair_index % 4}",
                        "scenario_level_frozen": "n3_no_refit",
                    }
                )
                execution_rows.append(
                    {
                        "query_run_id": query_run_id,
                        "feature_a": float(pair_index + 1),
                        "feature_b": float(repetition),
                    }
                )
    matrix = module.build_pair_matrix(
        pd.DataFrame(observed_rows),
        pd.DataFrame(execution_rows),
        ["feature_a", "feature_b"],
    )
    assert len(matrix) == 16
    assert np.isclose(matrix.loc[0, "feature_b"], 1.0)
    assert matrix["target_log2_gain"].gt(0).all()


def test_n3_ranking_support_rule_is_predeclared() -> None:
    batch = yaml.safe_load(
        (ROOT / "configs/collection/batches/batch-300-n3-holdout.yml").read_text(
            encoding="utf-8"
        )
    )
    rule = batch["frozen_inputs"]["ranking_support_rule"]
    assert rule == {
        "minimum_spearman": 0.5,
        "minimum_kendall": 0.35,
        "minimum_ndcg_at_5": 0.8,
        "minimum_top5_recall": 0.6,
        "calibration_metrics_are_secondary": True,
        "coverage_is_warning_only": True,
    }


def test_n3_statistical_transparency_is_deterministic_and_stratified() -> None:
    module = load_analysis_module()
    module.BOOTSTRAP_RESAMPLES = 200
    actual = np.linspace(0.5, 4.0, 16)
    predicted = actual * 0.8 + np.sin(np.arange(16)) * 0.1
    matrix = pd.DataFrame(
        {
            "pair_id": [f"pair-{index}" for index in range(16)],
            "placement_profile": ["balanced"] * 8 + ["apac_dominant"] * 8,
            "size_class": ["medium", "large"] * 8,
            "logical_question_id": [f"q-{index % 4}" for index in range(16)],
            "dataset_profile_id": [f"dataset-{index % 4}" for index in range(16)],
            "target_log2_gain": actual,
            "predicted_log2_gain": predicted,
            "actual_speedup": np.exp2(actual),
            "predicted_speedup": np.exp2(predicted),
            "distance_to_p99_ratio": np.linspace(1.1, 2.0, 16),
            "outside_training_p99": [True] * 16,
        }
    )
    metrics = module.ranking_metrics(actual, predicted)
    first = module.bootstrap_ranking_intervals(matrix, metrics)
    second = module.bootstrap_ranking_intervals(matrix, metrics)
    pd.testing.assert_frame_equal(first, second)
    assert set(first["metric"]) == {"spearman", "ndcg_at_5"}
    assert first["valid_resamples"].gt(0).all()
    assert first["lower"].le(first["estimate"]).all()
    assert first["estimate"].le(first["upper"]).all()

    placement = module.placement_metrics(matrix)
    assert set(placement["placement_profile"]) == {
        "balanced",
        "apac_dominant",
    }
    assert placement["pair_count"].eq(8).all()

    ranking = module.pair_ranking(matrix)
    assert list(ranking["actual_rank"]) == list(range(1, 17))
    assert ranking["outside_training_p99"].all()


def test_n3_edge_topology_uses_concrete_gac_destination() -> None:
    module = load_analysis_module()
    edge_rows = pd.DataFrame(
        [
            {
                "edge_id": f"{region}->eu-analytics-1",
                "source_cluster_id": region,
                "destination_gac_id": "eu-analytics-1",
            }
            for region in ("eu", "us", "apac")
        ]
    )
    status = module.validate_edge_topology(
        edge_rows,
        pd.Series(["eu-analytics-1"]),
    )
    assert status["edges_complete"] is True
    assert status["edge_count"] == 3
    assert status["edge_source_region_ids"] == "apac|eu|us"
    assert status["edge_destination_gac_ids"] == "eu-analytics-1"


def test_n3_edge_topology_rejects_missing_or_wrong_destination() -> None:
    module = load_analysis_module()
    edge_rows = pd.DataFrame(
        [
            {
                "edge_id": "eu->eu-analytics-1",
                "source_cluster_id": "eu",
                "destination_gac_id": "eu-analytics-1",
            },
            {
                "edge_id": "us->other-gac",
                "source_cluster_id": "us",
                "destination_gac_id": "other-gac",
            },
        ]
    )
    status = module.validate_edge_topology(
        edge_rows,
        pd.Series(["eu-analytics-1"]),
    )
    assert status["edges_complete"] is False


def test_freeze_resolves_model_matrix_relative_to_repository() -> None:
    module = load_freeze_module()
    assert module.repository_path("analysis/reports/example.csv") == (
        ROOT / "analysis/reports/example.csv"
    )
    assert module.repository_path("master-regimes/generated/example.csv") == (
        WORKSPACE / "master-regimes/generated/example.csv"
    )
