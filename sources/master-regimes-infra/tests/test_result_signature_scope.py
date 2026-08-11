from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "common-scripts"
        / "run_query_collection_sweep.py"
    )
    spec = importlib.util.spec_from_file_location(
        "run_query_collection_sweep",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_execution_scope_collects_all_repetitions() -> None:
    module = _load_module()

    assert module.collect_result_signature_for_row(
        enabled=True,
        scope="every_execution",
        row={"repetition_index": "2"},
    )


def test_first_repetition_scope_collects_only_repetition_zero() -> None:
    module = _load_module()

    assert module.collect_result_signature_for_row(
        enabled=True,
        scope="first_repetition_per_condition",
        row={"repetition_index": "0"},
    )
    assert not module.collect_result_signature_for_row(
        enabled=True,
        scope="first_repetition_per_condition",
        row={"repetition_index": "1"},
    )
    assert not module.collect_result_signature_for_row(
        enabled=False,
        scope="first_repetition_per_condition",
        row={"repetition_index": "0"},
    )


def test_weighted_progress_helpers() -> None:
    module = _load_module()

    assert module.format_seconds(None) == "calibrating"
    assert module.format_seconds(65) == "1m 05s"
    assert module.format_seconds(3661) == "1h 01m"
    assert module.progress_bar(5, 10, width=10) == "[#####-----]"
    assert module.progress_percent(5, 10) == 50
    assert (
        module.estimated_rate(
            local_seconds_per_unit=[2.0, 3.0, 100.0],
            prior_seconds_per_unit=9.0,
        )
        == 3.0
    )
    assert (
        module.estimated_rate(
            local_seconds_per_unit=[2.0],
            prior_seconds_per_unit=9.0,
        )
        == 9.0
    )
    assert module.remaining_counts(
        initial={"heavy": 3, "light": 2},
        processed_rows=[
            {"progress_cost_class": "heavy"},
            {"progress_cost_class": "light"},
        ],
        field="progress_cost_class",
    ) == {"heavy": 2, "light": 1}


def test_completed_checkpoint_requires_durable_completed_artifact(
    tmp_path: Path,
) -> None:
    module = _load_module()
    collection_dir = tmp_path / "query-collection"
    collection_dir.mkdir()
    event = {
        "status": "completed",
        "execution_slot_id": "slot-1",
        "collection_dir": str(collection_dir),
    }

    assert not module.completed_checkpoint_event(event)

    (collection_dir / "execution_manifest.json").write_text(
        json.dumps({"execution_status": "completed"}),
        encoding="utf-8",
    )
    assert module.completed_checkpoint_event(event)

    (collection_dir / "execution_manifest.json").write_text(
        json.dumps({"execution_status": "failed"}),
        encoding="utf-8",
    )
    assert not module.completed_checkpoint_event(event)
