from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis/scripts/agent/90_run_mitigation_correctness_recovery.py"
SPEC = importlib.util.spec_from_file_location("run_mitigation_correctness_recovery", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_snapshot_locator_resolves_completed_checkpoint_artifact(tmp_path: Path) -> None:
    collection = tmp_path / "collection"
    snapshot = collection / "nodes/gac/run-1"
    (snapshot / "results").mkdir(parents=True)
    (snapshot / "results/result_snapshot.json").write_text("{}\n", encoding="utf-8")
    (collection / "execution_manifest.json").write_text(
        json.dumps({"local_artifacts": {"gac": "nodes/gac/run-1"}}),
        encoding="utf-8",
    )
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(
        json.dumps(
            {
                "execution_slot_id": "pair-1::stressed",
                "status": "completed",
                "collection_dir": str(collection),
                "completed_at_utc": "20260801T120000Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    selection = pd.DataFrame(
        [
            {
                "recovery_id": "pair-1::stressed",
                "pair_id": "pair-1",
                "member": "stressed",
                "backend": "standard_corpus",
                "dataset_profile_id": "dataset-1",
            },
            {
                "recovery_id": "pair-1::mitigated",
                "pair_id": "pair-1",
                "member": "mitigated",
                "backend": "standard_corpus",
                "dataset_profile_id": "dataset-1",
            },
        ]
    )

    locator = tmp_path / "locator.csv"
    summary = MODULE.write_snapshot_locator(selection, checkpoint, locator)

    assert summary["located_member_count"] == 1
    assert summary["missing_member_count"] == 1
    rows = pd.read_csv(locator)
    assert rows.iloc[0]["snapshot_dir"] == str(snapshot.resolve())
