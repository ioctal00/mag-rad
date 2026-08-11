from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "common-scripts" / "collect_hardware_snapshot.py"
DATABASE_SWEEP_SCRIPT = ROOT / "common-scripts" / "run_database_sweep.py"


def load_script():
    spec = importlib.util.spec_from_file_location(
        "collect_hardware_snapshot",
        SCRIPT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_database_sweep():
    spec = importlib.util.spec_from_file_location(
        "run_database_sweep",
        DATABASE_SWEEP_SCRIPT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ssh_run_retries_transport_failure(monkeypatch) -> None:
    module = load_script()
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise subprocess.CalledProcessError(255, args[0])
        return subprocess.CompletedProcess(args[0], 0, "{}", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    result = module.ssh_run(
        "192.0.2.1",
        "root",
        None,
        "true",
        attempts=3,
        retry_delay_seconds=0,
    )

    assert result.returncode == 0
    assert calls == 3


def test_ssh_run_does_not_retry_remote_command_failure(monkeypatch) -> None:
    module = load_script()
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    try:
        module.ssh_run("192.0.2.1", "root", None, "false")
    except subprocess.CalledProcessError as error:
        assert error.returncode == 1
    else:
        raise AssertionError("Expected remote command failure")

    assert calls == 1


def test_database_sweep_accepts_shared_parent_hardware_snapshot(
    tmp_path: Path,
) -> None:
    module = load_database_sweep()
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    (snapshot_dir / "hardware_snapshot_manifest.json").write_text(
        json.dumps(
            {
                "collection_contract": {
                    "scope": "pressure_batch_global",
                }
            }
        ),
        encoding="utf-8",
    )

    resolved, scope = module.resolve_hardware_snapshot(snapshot_dir)

    assert resolved == snapshot_dir.resolve()
    assert scope == "pressure_batch_global"
