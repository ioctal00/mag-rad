from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "analysis/scripts/agent/94_colocation_ranking_robustness.py"
    spec = importlib.util.spec_from_file_location("colocation_ranking_robustness", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_contract():
    return yaml.safe_load(
        (ROOT / "configs/models/colocation_ranking_v1.yml").read_text(encoding="utf-8")
    )


def test_feature_views_are_leakage_and_topology_safe() -> None:
    module = load_module()
    contract = load_contract()
    module.validate_contract(contract)
    views = module.feature_views(contract)

    assert set(views["core"]).issubset(views["extended"])
    assert not any("template_id" in name for name in views["extended"])
    assert not any("dataset_profile_id" in name for name in views["extended"])
    assert not any("worker_1" in name or "eu_" in name for name in views["extended"])


def test_ranking_metrics_reward_correct_order() -> None:
    module = load_module()
    actual = np.array([0.5, 1.0, 2.0, 4.0, 6.0])
    correct = actual.copy()
    reversed_order = actual[::-1]

    good = module.ranking_metrics(actual, correct, ndcg_k=5, top_k_values=[3, 5])
    bad = module.ranking_metrics(
        actual, reversed_order, ndcg_k=5, top_k_values=[3, 5]
    )

    assert good["spearman"] == pytest.approx(1.0)
    assert good["kendall"] == pytest.approx(1.0)
    assert good["ndcg_at_5"] > bad["ndcg_at_5"]
    assert good["top3_recall"] > bad["top3_recall"]


def test_top_k_recall_uses_available_fold_size() -> None:
    module = load_module()
    actual = np.array([1.0, 3.0])
    predicted = np.array([1.5, 2.5])

    assert module.top_k_recall(actual, predicted, 5) == 1.0
