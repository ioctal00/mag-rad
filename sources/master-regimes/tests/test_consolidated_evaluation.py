from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis/scripts/agent/106_consolidated_evaluation.py"


def load_module():
    specification = importlib.util.spec_from_file_location("consolidated_evaluation_106", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_contract_keeps_frozen_configuration() -> None:
    module = load_module()
    contract = module.read_yaml(module.DEFAULT_CONTRACT)

    module._validate_contract(contract)

    assert contract["policy"]["frozen_neighbors"] == 5
    assert contract["policy"]["frozen_distance_metric"] == "euclidean"
    assert contract["policy"]["frozen_coverage_quantile"] == 0.99
    assert contract["policy"]["sensitivity_neighbors"] == [1, 3, 5]


def test_identity_audit_distinguishes_normalized_and_logical_memory() -> None:
    module = load_module()
    contract = module.read_yaml(module.DEFAULT_CONTRACT)

    audit, memory_contract, checks = module.identity_audit(contract)

    assert len(audit) == 15
    assert checks["raw_sql_changes_with_apac_branch"]
    assert checks["normalized_sql_changes_with_apac_branch"]
    assert checks["logical_identity_stable_across_topology"]
    assert checks["logical_hash_bijective_with_query_id"]
    assert set(memory_contract["canonical_name"]) == {
        "exact_query_memory",
        "logical_query_memory",
        "context_logical_query_memory",
    }


def test_q08_is_retained_and_explains_weighted_ranking_failure() -> None:
    module = load_module()
    contract = module.read_yaml(module.DEFAULT_CONTRACT)

    neighbors, rankings, summary = module.q08_failure_analysis(contract)

    assert len(neighbors) == 5
    assert summary["excluded_from_primary_result"] is False
    assert summary["predicted_action"] == "mitigate_remote_path_bundle"
    assert summary["actual_best_action"] == "regional_topk_candidates"
    assert neighbors["best_action"].value_counts()["regional_topk_candidates"] == 3
    assert rankings.loc[rankings["predicted_rank"].idxmin(), "action"] == (
        "mitigate_remote_path_bundle"
    )


def test_release_numbers_match_required_topology_result() -> None:
    release = ROOT / "releases/consolidated-evaluation-v1"
    if not release.exists():
        return
    numbers = json.loads((release / "manuscript_numbers.json").read_text())
    summary = pd.read_csv(release / "representation_summary.csv")
    e4 = summary[
        summary["evaluation"].eq("E4") & summary["representation"].eq("R3_full_multilayer")
    ].iloc[0]

    assert numbers["r3_e4_coverage_count"] == 15
    assert numbers["r3_e4_correct_count"] == 12
    assert numbers["r3_e4_top1"] == e4["top1_accuracy"]
    assert numbers["q08_regret"] > 2.7
