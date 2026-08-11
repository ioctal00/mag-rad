from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "analysis/scripts/agent/115_action_selection_sample_size_audit.py"
)


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sample_size_audit", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_keeps_executions_and_decisions_separate() -> None:
    module = load_module()
    units = {row["evidence_block"]: row for row in module.audit_units()}

    broad = units["broad intervention corpus"]
    assert broad["physical_executions"] == 2607
    assert broad["before_after_pairs"] == 418
    assert broad["complete_competing_action_matrix"].startswith("no")

    confirmatory = units["confirmatory new-query panel"]
    assert confirmatory["physical_executions"] == 300
    assert confirmatory["temporal_decisions"] == 15
    assert confirmatory["distinct_sql_units"] == 15
    assert confirmatory["repetitions_per_condition"] == 5


def test_confirmatory_top1_is_eight_of_fourteen() -> None:
    module = load_module()
    metrics, paired = module.audit_confirmatory()
    by_mode = {row["mode"]: row for row in metrics}

    prequential = by_mode["prequential_full_feedback"]
    assert prequential["recommendation_count"] == 14
    assert prequential["correct_recommendation_count"] == 8
    assert prequential["top1"] == 8 / 14

    static = by_mode["static_action_median"]
    assert static["recommendation_count"] == 15
    assert static["correct_recommendation_count"] == 8
    assert paired["prequential_total_correct"] == paired["static_total_correct"] == 8
    assert paired["prequential_only_correct"] == 1
    assert paired["static_only_correct"] == 0
