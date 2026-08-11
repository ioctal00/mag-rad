from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    script = (
        ROOT
        / "analysis"
        / "scripts"
        / "agent"
        / "74_build_pressure_intervention_program.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pressure_intervention_program_builder",
        script,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pressure_program_has_preregistered_counts_and_unique_slots(
    tmp_path: Path,
) -> None:
    module = load_builder()
    outputs = module.build_program(
        ROOT / "configs/validation/pressure_intervention_program_v1.yml",
        tmp_path / "pressure-program",
    )
    plan = yaml.safe_load(
        outputs["program_plan"].read_text(encoding="utf-8")
    )
    matrix = pd.read_csv(outputs["execution_matrix"], low_memory=False)

    assert len(matrix) == 996
    assert matrix["execution_slot_id"].is_unique
    assert plan["planned_execution_count"] == 996
    assert plan["ready_execution_count"] == 900
    assert plan["blocked_execution_count"] == 96
    assert matrix.groupby("dataset_role").size().to_dict() == {
        "pressure_combined_holdout": 240,
        "pressure_isolated": 624,
        "pressure_sentinel": 36,
        "pressure_topology_holdout": 96,
    }
    assert set(
        matrix.loc[
            matrix["execution_status"].eq("blocked"),
            "backend",
        ]
    ) == {"three_region_topology"}
