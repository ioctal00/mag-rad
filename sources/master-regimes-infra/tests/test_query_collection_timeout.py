from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "common-scripts" / "run_query_collection.py"
    spec = importlib.util.spec_from_file_location(
        "run_query_collection",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_command_timed_out_accepts_shell_timeout_exit_codes() -> None:
    module = _load_module()

    assert module.command_timed_out(
        subprocess.CompletedProcess(
            args=["timeout"],
            returncode=124,
            stdout="",
            stderr="",
        )
    )
    assert module.command_timed_out(
        subprocess.CompletedProcess(
            args=["timeout"],
            returncode=137,
            stdout="",
            stderr="",
        )
    )


def test_command_timed_out_accepts_postgres_statement_timeout() -> None:
    module = _load_module()
    result = subprocess.CompletedProcess(
        args=["psql"],
        returncode=1,
        stdout="",
        stderr="ERROR: canceling statement due to statement timeout",
    )

    assert module.command_timed_out(result)


def test_command_timed_out_rejects_unrelated_failure() -> None:
    module = _load_module()
    result = subprocess.CompletedProcess(
        args=["psql"],
        returncode=1,
        stdout="",
        stderr="ERROR: relation does not exist",
    )

    assert not module.command_timed_out(result)


def test_clock_calibration_maps_remote_epoch_to_controller_epoch() -> None:
    module = _load_module()

    calibration = module.parse_clock_calibration(
        "\n".join(
            [
                "__MR_CLOCK_BEFORE__=1000.100",
                "Run directory: /tmp/query-run",
                "__MR_CLOCK_AFTER__=1000.300",
            ]
        ),
        controller_started_at_unix=1000.0,
        controller_finished_at_unix=1000.4,
    )

    assert calibration["status"] == "available"
    assert abs(calibration["remote_minus_controller_seconds"]) < 1e-9
    assert abs(calibration["uncertainty_seconds"] - 0.1) < 1e-9


def test_remote_edge_context_merge_preserves_identity_and_both_stages() -> None:
    module = _load_module()
    before = {
        "eu->gac-1": {
            "edge_id": "eu->gac-1",
            "source_cluster_id": "eu",
            "source_node": "eu-coord-1",
            "destination_gac_id": "gac-1",
            "availability_status": "available",
            "rtt_median_ms": 10,
        }
    }
    after = {
        "eu->gac-1": {
            "edge_id": "eu->gac-1",
            "source_cluster_id": "eu",
            "source_node": "eu-coord-1",
            "destination_gac_id": "gac-1",
            "availability_status": "available",
            "rtt_median_ms": 12,
        },
        "us->gac-1": {
            "edge_id": "us->gac-1",
            "source_cluster_id": "us",
            "source_node": "us-coord-1",
            "destination_gac_id": "gac-1",
            "availability_status": "partial",
        },
    }

    rows = module.merge_remote_edge_context(before=before, after=after)
    by_edge = {row["edge_id"]: row for row in rows}

    assert set(by_edge) == {"eu->gac-1", "us->gac-1"}
    assert by_edge["eu->gac-1"]["before"]["rtt_median_ms"] == 10
    assert by_edge["eu->gac-1"]["after"]["rtt_median_ms"] == 12
    assert by_edge["eu->gac-1"]["availability_status"] == "available"
    assert by_edge["us->gac-1"]["availability_status"] == "partial"


def test_filter_hosts_by_regions_limits_single_edge_capture() -> None:
    module = _load_module()
    hosts = {
        "eu-coord-1": {"ansible_host": "10.0.0.1"},
        "us-coord-1": {"ansible_host": "10.0.0.2"},
    }

    assert module.filter_hosts_by_regions(hosts, regions=["eu"]) == {
        "eu-coord-1": {"ansible_host": "10.0.0.1"}
    }
    assert module.filter_hosts_by_regions(hosts, regions=[]) == hosts


def test_ssh_run_retries_only_transport_failures(monkeypatch) -> None:
    module = _load_module()
    calls = 0

    def fake_run_command(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise subprocess.CalledProcessError(255, args[0])
        return subprocess.CompletedProcess(args[0], 0, "ok", "")

    monkeypatch.setattr(module, "run_command", fake_run_command)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    result = module.ssh_run(
        "192.0.2.1",
        "root",
        None,
        "true",
        transport_attempts=3,
        retry_delay_seconds=0,
    )

    assert result.returncode == 0
    assert calls == 3


def test_ssh_run_does_not_retry_remote_command_failure(monkeypatch) -> None:
    module = _load_module()
    calls = 0

    def fake_run_command(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(module, "run_command", fake_run_command)

    try:
        module.ssh_run(
            "192.0.2.1",
            "root",
            None,
            "false",
            transport_attempts=3,
            retry_delay_seconds=0,
        )
    except subprocess.CalledProcessError as error:
        assert error.returncode == 1
    else:
        raise AssertionError("Expected remote command failure")

    assert calls == 1


def test_query_capture_start_script_recovers_started_session_on_retry() -> None:
    module = _load_module()

    script = module.query_capture_start_script(
        remote_bench_dir="/opt/psql-benchmarks",
        remote_label="20260806T000000Z-deadbeef",
        capture_db_snapshots=False,
        capture_os_samples=True,
        sample_interval_seconds=0.25,
    )

    assert "if test -s \"$active_file\"" in script
    assert "run_dir" in script
    assert "query-capture-start --label 20260806T000000Z-deadbeef" in script
    assert "--os-sampler" in script
    assert "BENCH_SAMPLE_INTERVAL_SECONDS=0.25" in script


def test_query_capture_start_script_rejects_label_requiring_sanitization() -> None:
    module = _load_module()

    try:
        module.query_capture_start_script(
            remote_bench_dir="/opt/psql-benchmarks",
            remote_label="unsafe label",
            capture_db_snapshots=False,
            capture_os_samples=False,
            sample_interval_seconds=0.25,
        )
    except ValueError as error:
        assert "Unsafe remote capture label" in str(error)
    else:
        raise AssertionError("Expected unsafe capture label to be rejected")
