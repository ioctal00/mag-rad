from __future__ import annotations

import csv
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "common-scripts/run_database_sweep.py"


def load_module():
    specification = importlib.util.spec_from_file_location("database_sweep_order", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def write_manifest(path: Path, runtimes: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["run_order", "runtime_config_id", "execution_slot_id"],
        )
        writer.writeheader()
        for index, runtime in enumerate(runtimes, start=1):
            writer.writerow(
                {
                    "run_order": index,
                    "runtime_config_id": runtime,
                    "execution_slot_id": f"slot-{index}",
                }
            )


def test_runtime_segments_preserve_global_order_and_contiguous_runs(tmp_path: Path) -> None:
    module = load_module()
    manifest = tmp_path / "instances.csv"
    write_manifest(manifest, ["a", "b", "b", "a", "c"])

    segments = module.runtime_order_segments(
        instance_manifest=manifest,
        runtime_configs=[{"id": value} for value in ("a", "b", "c")],
        out_dir=tmp_path / "segments",
    )

    assert [segment[0]["id"] for segment in segments] == ["a", "b", "a", "c"]
    assert [segment[2] for segment in segments] == [1, 2, 1, 1]
    observed_slots: list[str] = []
    for _, path, _ in segments:
        with path.open(encoding="utf-8", newline="") as handle:
            observed_slots.extend(row["execution_slot_id"] for row in csv.DictReader(handle))
    assert observed_slots == ["slot-1", "slot-2", "slot-3", "slot-4", "slot-5"]


def test_runtime_segments_apply_global_instance_limit_before_splitting(tmp_path: Path) -> None:
    module = load_module()
    manifest = tmp_path / "instances.csv"
    write_manifest(manifest, ["a", "b", "c", "a", "b"])

    segments = module.runtime_order_segments(
        instance_manifest=manifest,
        runtime_configs=[{"id": value} for value in ("a", "b", "c")],
        out_dir=tmp_path / "segments",
        max_instances=3,
    )

    assert [segment[0]["id"] for segment in segments] == ["a", "b", "c"]
    assert sum(segment[2] for segment in segments) == 3


def test_network_measurement_cache_key_ignores_only_profile_label() -> None:
    module = load_module()
    baseline = {
        "id": "baseline",
        "configured_delay_ms": 15,
        "configured_bandwidth_mbit": 50,
    }
    same_environment = {**baseline, "id": "gac-memory"}
    changed_environment = {**baseline, "id": "remote", "configured_delay_ms": 0}

    assert module.network_profile_cache_key(baseline) == module.network_profile_cache_key(
        same_environment
    )
    assert module.network_profile_cache_key(baseline) != module.network_profile_cache_key(
        changed_environment
    )


def test_partial_database_index_does_not_mask_collection_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    module = load_module()
    messages: list[tuple[str, str]] = []

    def fail_index(_sweep_dir: Path) -> None:
        raise subprocess.CalledProcessError(1, ["index_database_sweep.py"])

    monkeypatch.setattr(module, "index_database_sweep", fail_index)
    monkeypatch.setattr(
        module,
        "log_event",
        lambda component, message: messages.append((component, message)),
    )

    assert module.try_index_partial_database_sweep(tmp_path) is False
    assert messages
    assert messages[0][0] == "INDEX"
    assert "partial database sweep index failed" in messages[0][1]
