from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "common-scripts"
    / "index_corpus_run_attempts.py"
)


def _load_indexer():
    spec = importlib.util.spec_from_file_location("index_corpus_run_attempts", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repeatability_repetitions_are_distinct_logical_queries() -> None:
    indexer = _load_indexer()
    base = {
        "dataset_id": "balanced",
        "runtime_config_id": "default",
        "target_group": "analytics_clients",
        "corpus_cell_id": "cell-1",
        "instance_id": "instance-1",
        "condition_id": "condition-1",
    }
    first = indexer.logical_query_key({**base, "repetition_index": "0"})
    second = indexer.logical_query_key({**base, "repetition_index": "1"})
    retry = indexer.logical_query_key({**base, "repetition_index": "0"})

    assert first != second
    assert first == retry


def test_legacy_query_key_remains_stable_without_repeatability_fields() -> None:
    indexer = _load_indexer()
    row = {
        "dataset_id": "balanced",
        "runtime_config_id": "default",
        "target_group": "analytics_clients",
        "corpus_cell_id": "cell-1",
        "instance_id": "instance-1",
    }

    assert indexer.logical_query_key(row) == indexer.logical_query_key(dict(row))


def test_planned_query_row_uses_slot_runtime_in_bundled_group() -> None:
    indexer = _load_indexer()
    group = {
        "dataset_profile_id": "dataset-a",
        "runtime_config_id": "multiple",
        "target_group": "analytics_clients",
    }
    base = {
        "instance_id": "instance-a",
        "corpus_cell_id": "cell-a",
        "condition_id": "condition-a",
        "dataset_profile_id": "dataset-a",
        "runtime_config_id": "runtime-a",
    }
    first = indexer.planned_query_row(
        planned={**base, "repetition_index": "0"},
        group=group,
        common={},
    )
    second = indexer.planned_query_row(
        planned={**base, "repetition_index": "1"},
        group=group,
        common={},
    )

    assert first["runtime_config_id"] == "runtime-a"
    assert first["dataset_id"] == "dataset-a"
    assert indexer.logical_query_key(first) != indexer.logical_query_key(second)


def test_failed_wrapper_recovers_completed_database_index(tmp_path: Path) -> None:
    indexer = _load_indexer()
    attempt_dir = tmp_path / "attempt-01"
    sweep_dir = attempt_dir / "database-sweeps" / "timestamp-group-a"
    index_dir = sweep_dir / "_index"
    index_dir.mkdir(parents=True)
    (index_dir / "query_runs.csv").write_text(
        "query_run_id,execution_status\nrun-a,completed\n",
        encoding="utf-8",
    )

    assert indexer.resolve_database_sweep_paths(
        attempt_dir,
        {"group_id": "group-a", "status": "failed"},
    ) == (
        str(sweep_dir.resolve()),
        str(index_dir.resolve()),
        "recovered_after_postprocessing_failure",
    )
