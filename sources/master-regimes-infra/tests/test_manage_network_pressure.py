from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "common-scripts"
    / "manage_network_pressure.py"
)


def load_script():
    spec = importlib.util.spec_from_file_location("manage_network_pressure", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_remote_retries_ssh_transport_failure(monkeypatch) -> None:
    module = load_script()
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            return subprocess.CompletedProcess(args[0], 255, "", "connection reset")
        return subprocess.CompletedProcess(
            args[0],
            0,
            json.dumps({"status": "ok", "device": "eth0"}),
            "",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    result = module.run_remote(
        host="192.0.2.1",
        user="root",
        key_file=None,
        script="print('{}')",
    )

    assert result["status"] == "ok"
    assert result["ssh_attempt_count"] == 3
    assert calls == 3


def test_run_remote_does_not_retry_remote_command_failure(monkeypatch) -> None:
    module = load_script()
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(args[0], 1, "", "python failed")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.run_remote(
        host="192.0.2.1",
        user="root",
        key_file=None,
        script="raise RuntimeError",
    )

    assert result["status"] == "failed"
    assert result["ssh_attempt_count"] == 1
    assert calls == 1
