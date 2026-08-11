from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from master_regimes.confirmatory_skew import (
    build_confirmatory_skew_plan,
    evaluate_local_readiness,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "validation" / "confirmatory_skew_v1.yml"


def _test_config(tmp_path: Path) -> Path:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    features = [f"feature_{index:02d}" for index in range(21)]
    frozen_dir = tmp_path / "frozen"
    frozen_dir.mkdir()
    manifest = {
        "model_id": config["frozen_model"]["model_id"],
        "feature_matrix": {"features": features},
        "primary_model": {
            "algorithm": "fuzzy_c_means",
            "k": 4,
            "fuzzifier": 1.7,
        },
    }
    manifest_path = frozen_dir / "final_model_manifest.yml"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    artifact_paths = {
        "scaled_matrix": frozen_dir / "scaled.csv",
        "raw_matrix": frozen_dir / "raw.csv",
        "candidate_config": frozen_dir / "candidate.yml",
        "centers": frozen_dir / "centers.csv",
    }
    for name, path in artifact_paths.items():
        path.write_text(f"fixture: {name}\n", encoding="utf-8")
    config["frozen_model"].update(
        {
            "manifest": str(manifest_path),
            **{name: str(path) for name, path in artifact_paths.items()},
        }
    )
    config["source_manifest"] = str(
        ROOT
        / "workloads"
        / "corpus"
        / "corpus_manifest.confirmatory-skew-v1.yml"
    )
    config["source_render_dir"] = str(tmp_path / "source")
    config["output_dir"] = str(tmp_path / "output")
    config["selection"] = str(tmp_path / "selection.csv")
    path = tmp_path / "config.yml"
    path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_confirmatory_plan_has_locked_state_pairing_and_counts(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path)
    outputs = build_confirmatory_skew_plan(config_path=config)
    plan = yaml.safe_load(outputs["plan"].read_text(encoding="utf-8"))
    selection = pd.read_csv(outputs["selection"], low_memory=False)
    design = pd.read_csv(outputs["design_matrix"], low_memory=False)

    assert plan["state_order"] == ["A", "B", "C", "D"]
    assert plan["state_count"] == 4
    assert plan["query_condition_count"] == 4
    assert plan["execution_condition_count"] == 16
    assert plan["execution_count"] == 48
    assert plan["placement_aware_runner_required"] is True
    assert plan["database_result_rows_stored"] is False
    assert len(selection) == 16
    assert len(design) == 48
    assert design["slot_id"].nunique() == 48
    assert set(design.groupby("state_id").size()) == {12}

    b = selection[selection["state_id"].eq("B")].sort_values(
        "query_condition_id"
    )
    c = selection[selection["state_id"].eq("C")].sort_values(
        "query_condition_id"
    )
    assert b["logical_data_contract_id"].tolist() == c[
        "logical_data_contract_id"
    ].tolist()
    assert b["template_id"].tolist() == c["template_id"].tolist()
    assert b["param_json"].tolist() == c["param_json"].tolist()
    assert b["rendered_sql_sha256"].tolist() == c[
        "rendered_sql_sha256"
    ].tolist()

    c_group = next(
        group for group in plan["groups"] if group["state_id"] == "C"
    )
    assert c_group["dataset_transition"] == "reuse_previous_loaded_dataset"
    assert c_group["requires_placement_orchestrator"] is True


def test_confirmatory_local_readiness_passes_locked_fixture(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path)
    outputs = build_confirmatory_skew_plan(config_path=config)
    readiness = evaluate_local_readiness(
        config_path=config,
        plan_path=outputs["plan"],
        selection_path=outputs["selection"],
    )

    assert readiness["status"] == "pass"
    assert readiness["decision"] == "GO"
    assert all(readiness["gates"].values())
    assert readiness["bc_differences"] == []
    assert {
        row["physical_strategy_id"]
        for row in readiness["query_semantics"]
    } == {"regional_reduced", "raw_gac_finalize"}
