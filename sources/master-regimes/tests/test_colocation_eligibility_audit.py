from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "analysis/scripts/agent/95_colocation_eligibility_audit.py"
    spec = importlib.util.spec_from_file_location("colocation_eligibility_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_contract():
    return yaml.safe_load(
        (ROOT / "configs/models/colocation_eligibility_v1.yml").read_text(
            encoding="utf-8"
        )
    )


def test_repartition_join_is_review_candidate() -> None:
    module = load_module()
    row = pd.Series(
        {
            "citus_repartition_observed_v2": True,
            "remote_citus_map_merge_job_count_sum": 4,
            "join_shape_id": "segment_aggregate",
            "distribution_key": "tenant_id",
            "join_uses_distribution_key": False,
        }
    )

    status, candidate = module.classify(row, load_contract())

    assert status == "candidate_requires_schema_and_workload_review"
    assert candidate is True


def test_colocated_or_missing_join_is_not_review_candidate() -> None:
    module = load_module()
    contract = load_contract()
    no_repartition = pd.Series(
        {
            "citus_repartition_observed_v2": False,
            "remote_citus_map_merge_job_count_sum": 0,
            "join_shape_id": "segment_aggregate",
            "distribution_key": "tenant_id",
            "join_uses_distribution_key": True,
        }
    )
    missing_semantics = pd.Series(
        {
            "citus_repartition_observed_v2": True,
            "remote_citus_map_merge_job_count_sum": 2,
            "join_shape_id": None,
            "distribution_key": None,
            "join_uses_distribution_key": False,
        }
    )

    assert module.classify(no_repartition, contract)[1] is False
    assert module.classify(missing_semantics, contract)[1] is False
