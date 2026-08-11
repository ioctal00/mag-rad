from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "common-scripts" / "apply_dataset_profile.py"
    )
    spec = importlib.util.spec_from_file_location("apply_dataset_profile", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dataset_env_uses_per_region_distribution_override() -> None:
    module = _load_module()
    profile = {
        "dataset_id": "region-local-skew-smoke-v1",
        "seed": 42,
        "base_time_unix": 1782864000,
        "scale": {
            "events_per_tenant_avg": 10,
            "users_per_tenant_avg": 5,
            "lookback_days": 7,
        },
        "regions": {
            "eu": {
                "tenant_id_range": [1, 10],
                "distribution": {
                    "skew_profile": "heavy",
                    "hot_tenant_pct": 10,
                    "hot_event_pct": 70,
                },
            },
            "us": {"tenant_id_range": [10001, 10010]},
        },
        "distribution": {
            "distribution_key": "tenant_id",
            "shard_count": 8,
            "skew_profile": "balanced",
            "hot_tenant_pct": 1,
            "hot_event_pct": 50,
        },
    }

    eu_env = module.dataset_env(profile, region="eu", load_method="copy_pipe")
    us_env = module.dataset_env(profile, region="us", load_method="copy_pipe")

    assert eu_env["DATAGEN_DISTRIBUTION"] == "hot_tenants"
    assert eu_env["DATAGEN_HOT_TENANT_PCT"] == "10"
    assert eu_env["DATAGEN_HOT_EVENT_PCT"] == "70"
    assert eu_env["DATAGEN_BASE_TIME_UNIX"] == "1782864000"
    assert us_env["DATAGEN_DISTRIBUTION"] == "uniform"
    assert us_env["DATAGEN_HOT_TENANT_PCT"] == "1"
    assert us_env["DATAGEN_HOT_EVENT_PCT"] == "50"


def test_dataset_time_contract_records_anchor_window_and_measured_bounds() -> None:
    module = _load_module()
    profile = {
        "base_time_unix": 1782864000,
        "scale": {"lookback_days": 30},
    }
    rows = [
        {
            "first_event_at": "2026-06-01 00:02:00+00",
            "last_event_at": "2026-06-30 23:58:00+00",
        },
        {
            "first_event_at": "2026-06-01 00:01:00+00",
            "last_event_at": "2026-06-30 23:59:00+00",
        },
    ]

    contract = module._dataset_time_contract(profile, rows)

    assert contract == {
        "base_time_unix": 1782864000,
        "base_time_utc": "2026-07-01T00:00:00+00:00",
        "lookback_days": 30,
        "wall_clock_anchored": False,
        "measured_event_time_min": "2026-06-01 00:01:00+00",
        "measured_event_time_max": "2026-06-30 23:59:00+00",
    }


def test_dataset_time_contract_marks_legacy_wall_clock_profile() -> None:
    module = _load_module()

    contract = module._dataset_time_contract({"scale": {"lookback_days": 7}}, [])

    assert contract["base_time_unix"] == 0
    assert contract["base_time_utc"] == "not_frozen"
    assert contract["wall_clock_anchored"] is True


def test_dataset_snapshot_contract_does_not_claim_row_level_checksum() -> None:
    module = _load_module()

    contract = module._dataset_snapshot_contract()

    assert contract["checksum_scope"] == "profile_and_aggregate_audit_artifacts"
    assert contract["row_level_checksum_included"] is False


def test_dataset_env_allows_a_wider_global_user_dimension() -> None:
    module = _load_module()
    profile = {
        "dataset_id": "wide-global-users-v1",
        "seed": 73,
        "scale": {
            "events_per_tenant_avg": 100,
            "users_per_tenant_avg": 50,
            "global_users_per_tenant_avg": 200,
            "lookback_days": 30,
        },
        "regions": {"eu": {"tenant_id_range": [1, 20]}},
        "distribution": {
            "distribution_key": "tenant_id",
            "shard_count": 16,
            "skew_profile": "balanced",
        },
    }

    env = module.dataset_env(profile, region="eu", load_method="copy_pipe")

    assert env["DATAGEN_USERS_PER_TENANT"] == "50"
    assert env["DATAGEN_GLOBAL_USERS_PER_TENANT"] == "200"
    assert env["DATAGEN_SHARD_COUNT"] == "16"


def test_dataset_env_serializes_disjoint_logical_tenant_ranges() -> None:
    module = _load_module()
    profile = {
        "dataset_id": "n2-merged-regions-v1",
        "seed": 73,
        "identity": {"event_id_mode": "tenant_global"},
        "scale": {
            "events_per_tenant_avg": 100,
            "users_per_tenant_avg": 50,
            "lookback_days": 30,
        },
        "regions": {
            "us": {
                "tenant_id_ranges": [
                    [10001, 10100, "us"],
                    [20001, 20100, "apac"],
                ]
            }
        },
        "distribution": {
            "distribution_key": "tenant_id",
            "shard_count": 16,
            "skew_profile": "balanced",
        },
    }

    env = module.dataset_env(profile, region="us", load_method="copy_pipe")

    assert env["DATAGEN_TENANT_START"] == "10001"
    assert env["DATAGEN_TENANT_END"] == "10100"
    assert env["DATAGEN_TENANT_RANGES"] == "10001:10100:us,20001:20100:apac"
    assert env["DATAGEN_EVENT_ID_MODE"] == "tenant_global"


def test_hot_tenant_manifest_uses_expected_hot_count(tmp_path: Path) -> None:
    module = _load_module()
    tenant_rows = [
        {
            "tenant_id": str(tenant_id),
            "events_count": str(1000 - tenant_id),
            "total_value": "1.0",
        }
        for tenant_id in range(1, 101)
    ]
    profile = {
        "regions": {
            "eu": {
                "tenant_id_range": [1, 100],
                "distribution": {
                    "skew_profile": "heavy",
                    "hot_tenant_pct": 25,
                    "hot_event_pct": 70,
                },
            }
        },
        "distribution": {"skew_profile": "balanced"},
    }

    hot_count = module.expected_hot_tenant_count(profile, region="eu", tenant_count=100)
    hot_rows = module._write_hot_tenant_manifest(
        tmp_path / "hot_tenant_manifest.csv",
        tenant_rows,
        hot_tenant_count=hot_count,
    )

    assert hot_count == 25
    assert len(hot_rows) == 25
    lines = (tmp_path / "hot_tenant_manifest.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 26


def test_ssh_run_retries_transport_failure(monkeypatch) -> None:
    module = _load_module()
    results = [
        subprocess.CompletedProcess([], 255, "", "connection reset"),
        subprocess.CompletedProcess([], 0, "ok", ""),
    ]
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return results.pop(0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    result = module.ssh_run("192.0.2.1", "root", None, "true")

    assert result.returncode == 0
    assert len(calls) == 2
    assert "ServerAliveInterval=15" in calls[0]


def test_ssh_run_does_not_retry_remote_command_failure(monkeypatch) -> None:
    module = _load_module()
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "psql failed")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        module.ssh_run("192.0.2.1", "root", None, "false")

    assert len(calls) == 1
