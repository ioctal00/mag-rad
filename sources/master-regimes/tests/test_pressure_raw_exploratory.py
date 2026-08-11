from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "analysis/scripts/agent/87_pressure_raw_exploratory_analysis.py"
    spec = importlib.util.spec_from_file_location("pressure_raw_exploratory", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execution_rows() -> pd.DataFrame:
    rows = []
    for variant, elapsed, signature, byte_count in (
        ("stressed", "4", "hash-a", "100"),
        ("mitigated", "2", "hash-b", "99"),
    ):
        for repetition in range(3):
            rows.append(
                {
                    "pair_id": "pair-1",
                    "repetition_index": str(repetition),
                    "variant": variant,
                    "query_run_id": f"query-{variant}-{repetition}",
                    "condition_id": f"condition-{variant}",
                    "elapsed_seconds": elapsed,
                    "dataset_profile_id": "dataset",
                    "runtime_config_id": variant,
                    "template_id": "floating-aggregate",
                    "physical_strategy_id": variant,
                    "pressure_level": variant,
                    "pressure_axis": "remote_path",
                    "intervention_role": "positive_case",
                    "target_metric": "execution_time_seconds",
                    "result_signature_status": "completed" if repetition == 0 else "disabled",
                    "result_row_count": "1" if repetition == 0 else "",
                    "result_output_byte_count": byte_count if repetition == 0 else "",
                    "result_multiset_sha256": signature if repetition == 0 else "",
                }
            )
    return pd.DataFrame(rows)


def test_pair_targets_keep_three_repetitions_and_log2_gain() -> None:
    module = load_module()
    executions = execution_rows()
    signatures = module.build_result_signature_audit(executions)
    targets = module.build_pair_repeat_targets(executions, signatures)

    assert len(targets) == 3
    assert targets["pair_complete"].all()
    assert set(targets["target_log2_mitigation_gain"]) == {1.0}
    assert set(targets["result_equivalence_status"]) == {"same_row_count_hash_diff_review"}


def test_pair_summary_uses_log2_ratio_of_condition_medians() -> None:
    module = load_module()
    executions = execution_rows()
    executions.loc[executions["variant"].eq("stressed"), "elapsed_seconds"] = [
        "4",
        "100",
        "9",
    ]
    executions.loc[executions["variant"].eq("mitigated"), "elapsed_seconds"] = [
        "2",
        "50",
        "1",
    ]
    signatures = module.build_result_signature_audit(executions)
    repeats = module.build_pair_repeat_targets(executions, signatures)

    result = module.build_pair_summary(repeats).iloc[0]

    assert result["stressed_elapsed_median"] == 9
    assert result["mitigated_elapsed_median"] == 2
    assert result["elapsed_ratio_median"] == 4.5
    assert result["paired_repeat_ratio_median"] == 2
    assert result["target_log2_gain_median"] == pytest.approx(math.log2(4.5))


def test_result_signature_audit_does_not_treat_same_row_count_as_exact() -> None:
    module = load_module()
    result = module.build_result_signature_audit(execution_rows()).iloc[0]

    assert result["same_row_count"]
    assert not result["exact_multiset_hash"]
    assert result["output_byte_difference"] == 1
    assert result["result_equivalence_status"] == "same_row_count_hash_diff_review"


def test_os_node_coverage_flags_incomplete_skew_capture() -> None:
    module = load_module()
    executions = pd.DataFrame(
        [
            {
                "batch_id": "batch-120-skew",
                "os_sampled_node_count": "3",
                "os_query_aligned_node_count": "3",
            }
        ]
    )

    result = module.build_os_node_coverage(executions).iloc[0]

    assert result["expected_os_node_count"] == 7
    assert result["observed_os_node_count_min"] == 3
    assert result["coverage_status"] == "incomplete"


def test_os_coverage_report_note_reflects_current_gate() -> None:
    module = load_module()

    assert "Svi batch-evi" in module.os_coverage_report_note([])
    assert "ponovo prikupljeni" in module.os_coverage_report_note(["batch-120-skew"])
