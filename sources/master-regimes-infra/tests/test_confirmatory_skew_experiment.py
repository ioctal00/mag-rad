from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "common-scripts"
        / "run_confirmatory_skew_experiment.py"
    )
    spec = importlib.util.spec_from_file_location(
        "confirmatory_skew_experiment",
        script,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_group_requires_exact_state_match() -> None:
    module = load_module()
    plan = {"groups": [{"state_id": "A", "group_id": "a"}]}

    assert module.plan_group(plan, "A")["group_id"] == "a"


def test_frozen_contract_verification_uses_declared_hashes(
    tmp_path,
    monkeypatch,
) -> None:
    module = load_module()
    workspace = tmp_path / "workspace"
    plan_dir = workspace / "master-regimes" / "generated" / "corpus" / "run"
    artifact = workspace / "master-regimes" / "model.csv"
    plan_dir.mkdir(parents=True)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("model\n", encoding="utf-8")
    digest = module.sha256_file(artifact)
    (plan_dir / "frozen_contract.json").write_text(
        (
            '{"model_id":"m","feature_count":1,"artifacts":'
            '{"centers":{"path":"master-regimes/model.csv","sha256":"'
            + digest
            + '"}}}'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "WORKSPACE_ROOT", workspace)

    result = module.verify_frozen_contract(plan_dir / "plan.yml")

    assert result["artifact_hashes_verified"] is True
