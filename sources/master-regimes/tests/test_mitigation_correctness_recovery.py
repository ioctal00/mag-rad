from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis/scripts/agent/89_mitigation_correctness_recovery.py"
SPEC = importlib.util.spec_from_file_location("mitigation_correctness_recovery", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


CONTRACT = {
    "selection": {
        "required_pair_status": "review_only",
        "expected_pair_count": 1,
        "members_per_pair": 2,
        "require_same_dataset": True,
        "require_same_logical_question": True,
        "require_same_template": True,
        "require_same_parameters": True,
        "target_scope": "global_query",
    },
    "comparison": {
        "null_token": "__MASTER_REGIMES_SQL_NULL__",
        "floating_types": ["real", "double precision"],
        "floating_absolute_tolerance": 1.0e-9,
        "floating_relative_tolerance": 1.0e-12,
        "accepted_statuses": ["exact_snapshot", "tolerance_equivalent"],
    },
}


def test_selection_materializes_two_members_and_checks_invariants(tmp_path: Path) -> None:
    sql = tmp_path / "query.sql"
    sql.write_text("select 1;\n", encoding="utf-8")
    pairs = pd.DataFrame(
        [
            {
                "pair_id": "pair-1",
                "gain_pair_status": "review_only",
                "stressed_condition_id": "condition-s",
                "mitigated_condition_id": "condition-m",
                "target_scope_canonical": "global_query",
                "mitigation_action": "increase_fetch_size",
                "intervention_role": "calibration",
                "pressure_axis": "remote_path",
            }
        ]
    )
    matrix_rows = []
    for condition, runtime in (
        ("condition-s", "stressed"),
        ("condition-m", "mitigated"),
    ):
        for repetition in (1, 2, 3):
            matrix_rows.append(
                {
                    "condition_id": condition,
                    "execution_slot_id": f"{condition}::r{repetition}",
                    "repetition_index": repetition,
                    "batch_id": "batch-110-remote",
                    "group_id": f"group-{runtime}",
                    "backend": "standard_corpus",
                    "dataset_profile_id": "dataset-1",
                    "dataset_size_class": "small",
                    "runtime_config_id": runtime,
                    "execution_strategy": "multiregion_union",
                    "physical_strategy_id": "same",
                    "placement_state_id": "",
                    "placement_action": "",
                    "template_id": "template-1",
                    "logical_question_id": "question-1",
                    "param_json": '{"value": 1}',
                    "rendered_sql_path": str(sql),
                }
            )
    selection = MODULE.build_selection(pairs, pd.DataFrame(matrix_rows), CONTRACT)
    assert len(selection) == 2
    assert set(selection["member"]) == {"stressed", "mitigated"}
    assert set(selection["source_condition_repetition_count"]) == {3}
    assert selection["rendered_sql_sha256_actual"].nunique() == 1


def write_snapshot(
    root: Path,
    pair_id: str,
    member: str,
    rows: str,
    digest: str,
) -> None:
    result_dir = root / pair_id / member / "results"
    result_dir.mkdir(parents=True)
    (result_dir / "result_rows.csv").write_text(rows, encoding="utf-8")
    (result_dir / "result_snapshot.json").write_text(
        json.dumps(
            {
                "result_rows_file": "results/result_rows.csv",
                "multiset_sha256": digest,
                "columns": [
                    {"ordinal": 1, "name": "id", "postgres_type": "bigint"},
                    {
                        "ordinal": 2,
                        "name": "value",
                        "postgres_type": "double precision",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_typed_multiset_accepts_order_and_small_float_difference(tmp_path: Path) -> None:
    write_snapshot(tmp_path, "pair-1", "stressed", "1,10.0\n2,20.0\n", "left")
    write_snapshot(
        tmp_path,
        "pair-1",
        "mitigated",
        "2,20.00000000001\n1,10.0\n",
        "right",
    )
    result = MODULE.compare_pair_snapshots("pair-1", tmp_path, CONTRACT)
    assert result["correctness_recovery_status"] == "tolerance_equivalent"
    assert result["matched_row_count"] == 2


def test_typed_multiset_rejects_integer_or_large_float_difference(tmp_path: Path) -> None:
    write_snapshot(tmp_path, "pair-1", "stressed", "1,10.0\n", "left")
    write_snapshot(tmp_path, "pair-1", "mitigated", "2,10.1\n", "right")
    result = MODULE.compare_pair_snapshots("pair-1", tmp_path, CONTRACT)
    assert result["correctness_recovery_status"] == "value_mismatch"
    assert result["matched_row_count"] == 0
