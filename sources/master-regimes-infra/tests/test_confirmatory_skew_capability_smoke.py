from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
import yaml


def load_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "common-scripts"
        / "run_confirmatory_skew_capability_smoke.py"
    )
    spec = importlib.util.spec_from_file_location(
        "confirmatory_skew_capability_smoke",
        script,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_greedy_assignment_balances_hot_mass_deterministically() -> None:
    module = load_module()
    assignment = module.greedy_hot_shard_assignment(
        shard_mass={11: 50, 12: 40, 13: 10, 14: 10},
        workers=["worker-b", "worker-a"],
    )

    assert assignment == {
        11: "worker-a",
        12: "worker-b",
        13: "worker-b",
        14: "worker-a",
    }


def test_hot_share_threshold_is_not_applied_to_balanced_region() -> None:
    module = load_module()

    module.validate_hot_share_threshold(
        state_id="C",
        region="us",
        hot_tenant_ids=set(),
        observed_share=0.0,
        threshold=0.8,
    )
    with pytest.raises(RuntimeError, match="C concentration threshold failed"):
        module.validate_hot_share_threshold(
            state_id="C",
            region="eu",
            hot_tenant_ids={1, 2},
            observed_share=0.5,
            threshold=0.8,
        )


def test_invariants_ignore_placement_but_not_data() -> None:
    module = load_module()
    before = {
        "eu": {
            "table_counts": {"events": 100},
            "hot_tenant_ids": [1],
            "hot_tenant_event_counts": {"1": 50},
            "hot_event_share": 0.5,
            "tenant_distribution_sha256": "same",
            "event_placement_sha256": "before",
        }
    }
    after = {
        "eu": {
            **before["eu"],
            "event_placement_sha256": "after",
        }
    }

    equal, differences = module.invariants_equal(before, after)
    assert equal
    assert differences == []

    after["eu"]["table_counts"] = {"events": 99}
    equal, differences = module.invariants_equal(before, after)
    assert not equal
    assert differences == ["eu.table_counts"]


def test_runtime_contract_requires_same_fixed_profile_for_b_and_c(
    tmp_path: Path,
) -> None:
    module = load_module()
    runtime = {
        "id": "worker_fixed_remote",
        "pg_options": {},
        "psql_variables": {"FETCH_COUNT": "1000"},
        "fdw_server_options": {"fetch_size": "1000"},
        "network_profile": {
            "id": "worker_fixed_remote",
            "scope": "region_egress_to_analytics",
            "configured_delay_ms": 20,
        },
    }
    groups = []
    for state_id in ("B", "C"):
        sweep = tmp_path / f"{state_id}.yml"
        sweep.write_text(
            yaml.safe_dump({"runtime_configs": [runtime]}),
            encoding="utf-8",
        )
        groups.append(
            {
                "state_id": state_id,
                "sweep_config": str(sweep),
            }
        )

    assert module.runtime_contract({"groups": groups}) == runtime

    changed = dict(runtime)
    changed["psql_variables"] = {"FETCH_COUNT": "10000"}
    (tmp_path / "C.yml").write_text(
        yaml.safe_dump({"runtime_configs": [changed]}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="same fixed runtime"):
        module.runtime_contract({"groups": groups})


def test_remote_psql_csv_retries_only_ssh_transport_failure(
    monkeypatch,
) -> None:
    module = load_module()
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            return subprocess.CompletedProcess(
                args[0],
                255,
                "",
                "ssh timeout",
            )
        return subprocess.CompletedProcess(
            args[0],
            0,
            "value\n1\n",
            "",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    rows = module.remote_psql_csv(
        coordinator={"ansible_host": "192.0.2.1"},
        user="root",
        key_file=None,
        sql="SELECT 1 AS value",
        retry_delay_seconds=0,
    )

    assert rows == [{"value": "1"}]
    assert calls == 3


def test_skew_query_capture_profiles_all_database_nodes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = load_module()
    manifest = tmp_path / "instances.csv"
    manifest.write_text("instance_id\ninstance-1\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run_streaming_path(command, *, component):
        commands.append(command)
        return tmp_path / component.lower()

    monkeypatch.setattr(module, "run_streaming_path", fake_run_streaming_path)

    module.run_query_smoke(
        state_id="B",
        manifest_path=manifest,
        out_root=tmp_path / "runs",
        hard_timeout_seconds=60,
        timeout_grace_seconds=5,
        pg_options={},
        psql_variables={},
        result_signature_required=False,
        result_signature_scope="first_repetition",
        result_snapshot_only=False,
        result_snapshot_max_rows=100,
        result_snapshot_max_bytes=1024,
    )

    capture_command = commands[0]
    group_index = capture_command.index("--os-sampler-node-group")
    assert capture_command[group_index + 1] == "db_nodes"


def test_skew_correctness_capture_keeps_placement_identity_and_skips_index(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = load_module()
    source_manifest = tmp_path / "source.csv"
    source_manifest.write_text(
        "query_condition_id,repetition_index,condition_id,execution_slot_id,"
        "repeat_id,pair_id,intervention_role,instance_id,run_order\n"
        "top_tenants_short,0,source-condition,source-slot,source-repeat,"
        "source-pair,source-role,instance-1,1\n",
        encoding="utf-8",
    )
    plan = {
        "groups": [
            {"state_id": "B", "instance_manifest": str(source_manifest)},
        ]
    }
    out_manifest = tmp_path / "selected.csv"
    module.build_smoke_manifest(
        plan=plan,
        state_id="B",
        out_path=out_manifest,
        conditions=("top_tenants_short",),
        repetition_indices=(0,),
        recovery_members={
            ("B", "top_tenants_short"): {
                "condition_id": "condition-b",
                "recovery_id": "pair-1::mitigated",
                "pair_id": "pair-1",
                "member": "mitigated",
            }
        },
    )
    selected = module.read_csv(out_manifest)
    assert selected[0]["execution_slot_id"] == "pair-1::mitigated"
    assert selected[0]["pair_id"] == "pair-1"

    commands: list[list[str]] = []

    def fake_run_streaming_path(command, *, component):
        commands.append(command)
        return tmp_path / component.lower()

    monkeypatch.setattr(module, "run_streaming_path", fake_run_streaming_path)
    _, index_dir = module.run_query_smoke(
        state_id="B",
        manifest_path=out_manifest,
        out_root=tmp_path / "runs",
        hard_timeout_seconds=60,
        timeout_grace_seconds=5,
        pg_options={},
        psql_variables={},
        result_signature_required=False,
        result_signature_scope="first_repetition",
        result_snapshot_only=True,
        result_snapshot_max_rows=100,
        result_snapshot_max_bytes=1024,
    )
    assert index_dir is None
    assert len(commands) == 1
    assert "--result-snapshot-only" in commands[0]
    assert "--fdw-auto-explain" not in commands[0]
