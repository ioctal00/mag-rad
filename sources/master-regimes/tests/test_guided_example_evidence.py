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
        / "58_build_guided_example_evidence.py"
    )
    spec = importlib.util.spec_from_file_location("guided_example_evidence", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_choose_pair_is_deterministic_and_prefers_first_repetition() -> None:
    module = load_module()
    frame = pd.DataFrame(
        [
            {
                "state_id": state,
                "query_condition_id": module.PRIMARY_CONDITION,
                "execution_status": "completed",
                "repetition_index": repetition,
                "query_run_id": f"{state}-{repetition}",
            }
            for repetition in ("1", "0")
            for state in ("C", "B")
        ]
    )

    b, c = module.choose_pair(frame)

    assert b["query_run_id"] == "B-0"
    assert c["query_run_id"] == "C-0"


def test_population_cv_and_imbalance_factor() -> None:
    module = load_module()

    assert module.coefficient_of_variation([50.0, 150.0]) == 0.5
    assert module.imbalance_factor([50.0, 150.0]) == 1.5


def test_plan_tree_preserves_remote_boundary() -> None:
    module = load_module()
    plan = {
        "Node Type": "Aggregate",
        "Actual Rows": 10,
        "Plans": [
            {
                "Node Type": "Foreign Scan",
                "Schema": "fdw_eu",
                "Relation Name": "events",
                "Actual Rows": 100,
                "Remote SQL": "SELECT tenant_id FROM public.events",
            }
        ],
    }

    lines = module.format_plan_tree(plan)

    assert lines[0] == "Aggregate [rows=10]"
    assert "Foreign Scan on fdw_eu.events" in lines[1]
    assert "remote_sql=SELECT tenant_id FROM public.events" in lines[1]
