from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "common-scripts"
    / "build_corpus_rerun_plan.py"
)


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_corpus_rerun_plan",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_copy_instance_rows_selects_only_failed_repetition(tmp_path) -> None:
    builder = _load_builder()
    source = tmp_path / "source.csv"
    output = tmp_path / "output.csv"
    sql_file = tmp_path / "query.sql"
    sql_file.write_text("SELECT 1;\n", encoding="utf-8")
    fieldnames = [
        "instance_id",
        "condition_id",
        "repetition_index",
        "rendered_sql_path",
    ]
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "instance_id": "same-instance",
                    "condition_id": "condition-1",
                    "repetition_index": "0",
                    "rendered_sql_path": str(sql_file),
                },
                {
                    "instance_id": "same-instance",
                    "condition_id": "condition-1",
                    "repetition_index": "1",
                    "rendered_sql_path": str(sql_file),
                },
            ]
        )

    selected, missing = builder.copy_instance_rows(
        source_manifest=source,
        selected_execution_keys={
            ("repeatability", "condition-1", "1")
        },
        output_manifest=output,
        queries_dir=tmp_path / "queries",
    )

    assert missing == []
    assert len(selected) == 1
    assert selected[0]["repetition_index"] == "1"


def test_legacy_execution_key_uses_instance_id() -> None:
    builder = _load_builder()

    assert builder.execution_key({"instance_id": "legacy-1"}) == (
        "legacy",
        "legacy-1",
    )


def test_bundled_group_expands_to_concrete_runtime_segments() -> None:
    builder = _load_builder()
    group = {
        "dataset_profile_id": "dataset-a",
        "runtime_config_id": "multiple",
        "runtime_config_ids": ["runtime-a", "runtime-b"],
        "target_group": "analytics_clients",
    }

    assert builder.group_segment_keys(group) == [
        ("dataset-a", "runtime-a", "analytics_clients"),
        ("dataset-a", "runtime-b", "analytics_clients"),
    ]


def test_rerun_group_id_is_bounded_and_deterministic() -> None:
    builder = _load_builder()
    raw = "source-group-" * 20

    first = builder.bounded_rerun_group_id(raw)
    second = builder.bounded_rerun_group_id(raw)

    assert first == second
    assert len(first) <= builder.MAX_RERUN_GROUP_ID_CHARS
