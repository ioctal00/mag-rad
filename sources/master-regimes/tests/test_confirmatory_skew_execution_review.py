from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


def load_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "analysis"
        / "scripts"
        / "agent"
        / "56_confirmatory_skew_execution_review.py"
    )
    spec = importlib.util.spec_from_file_location(
        "confirmatory_skew_execution_review",
        script,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_condition_parsers_preserve_preregistered_keys() -> None:
    module = load_module()
    value = "confirm-skew-v1::C::top_tenants__regional_reduced"

    assert module.state_from_condition(value) == "C"
    assert module.query_condition(value) == "top_tenants__regional_reduced"


def test_combine_indexes_materializes_feature_builder_contract(
    tmp_path: Path,
) -> None:
    module = load_module()
    tables = (
        "query_runs",
        "region_fragments",
        "worker_task_fragments",
        "plan_structure_features",
        "plan_nodes",
        "fdw_remote_plans",
    )
    manifest = {"query_sweeps": {}}
    for state_id in ("A", "B", "C", "D"):
        index_dir = tmp_path / state_id
        index_dir.mkdir()
        manifest["query_sweeps"][state_id] = {"index_dir": str(index_dir)}
        for table in tables:
            pd.DataFrame(
                [{"query_run_id": f"query-{state_id}", "value": table}]
            ).to_csv(index_dir / f"{table}.csv", index=False)

    logical_index = tmp_path / "_logical" / "_index"
    combined = module.combine_indexes(
        manifest=manifest,
        logical_index=logical_index,
    )

    assert set(combined) == set(tables)
    for table in tables:
        result = pd.read_csv(logical_index / f"{table}.csv")
        assert len(result) == 4
        assert set(result["state_id"]) == {"A", "B", "C", "D"}
