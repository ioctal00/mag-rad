from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd

SCRIPT_PATH = Path(
    "analysis/scripts/agent/40_build_reproducibility_package.py"
)
SPEC = spec_from_file_location("reproducibility_package", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_collection_protocol_does_not_store_result_rows() -> None:
    query_runs = pd.DataFrame(
        {"hard_timeout_seconds": [10], "execution_status": ["completed"]}
    )
    model = {
        "feature_matrix": {"matrix_id": "fixture", "feature_count": 2},
        "primary_model": {"k": 4, "fuzzifier": 1.7},
    }
    protocol = MODULE.build_collection_protocol(
        "fixture-run",
        {"corpus_manifest": None},
        query_runs,
        model,
    )
    setting = protocol.set_index("setting")
    assert setting.loc["database_result_rows_stored", "value"] is False
    assert setting.loc["observation_unit", "value"] == "query_run_id"
    assert setting.loc["hard_timeout_seconds", "provenance"] == (
        MODULE.PROVENANCE_RECORDED
    )


def test_infrastructure_uses_observed_hardware() -> None:
    hardware = pd.DataFrame(
        [
            {
                "node_name": "eu-worker-1",
                "hardware_snapshot_id": "snapshot-1",
                "cpu_model": "Observed CPU",
                "logical_cpus": 8,
                "physical_cores": 4,
                "threads_per_core": 2,
                "ram_total_bytes": 16,
                "disk_total_bytes": 32,
            }
        ]
    )
    environment = {
        "software": {"postgresql_version": "18", "citus_version": "14.0"},
        "node_locations": {"eu-worker-1": "ams"},
        "distribution": {"shard_replication_factor": None},
        "source": {
            "repository": "master-regimes-infra",
            "commit": "fixture",
            "path": "configs/systems/fixture.yml",
        },
    }
    result = MODULE.build_infrastructure("fixture-run", hardware, environment)
    assert result.iloc[0]["cpu_model"] == "Observed CPU"
    assert result.iloc[0]["physical_provider_region"] == "ams"
    assert result.iloc[0]["hardware_provenance"] == MODULE.PROVENANCE_RECORDED
    assert result.iloc[0]["shard_replication_factor"] == (
        MODULE.PROVENANCE_MISSING
    )


def test_runtime_delay_is_not_reported_as_rtt() -> None:
    sweeps = pd.DataFrame(
        [
            {
                "query_sweep_id": "s1",
                "runtime_config_id": "wan_40ms",
                "runtime_intervention_axis": "wan_latency",
                "network_intervention_scope": "analytics_egress_to_region",
                "configured_latency_ms": 40,
                "configured_jitter_ms": 0,
                "configured_loss_percent": 0,
                "network_intervention_apply_status": "ok",
                "network_intervention_reset_status": "ok",
                "pg_options_json": "{}",
                "psql_variables_json": "{}",
                "fdw_server_options_json": "{}",
                "network_profile_json": "{}",
                "query_count": 3,
            }
        ]
    )
    result = MODULE.build_runtime_interventions(
        "fixture-run",
        sweeps,
        {"runtime_configs": {}},
    )
    row = result.iloc[0]
    assert row["configured_netem_delay_ms"] == 40
    assert bool(row["configured_delay_is_rtt"]) is False
    assert row["netem_semantics"] == (
        "one_way_analytics_egress_to_region_coordinator"
    )


def test_public_path_removes_local_workspace_prefix() -> None:
    path = MODULE.WORKSPACE_ROOT / "master-regimes" / "docs" / "README.md"
    assert MODULE.public_path(path) == "master-regimes/docs/README.md"


def test_manifest_digest_is_deterministic() -> None:
    payload = {"b": [2, 1], "a": {"x": True}}
    assert MODULE.canonical_payload_sha256(payload) == (
        MODULE.canonical_payload_sha256(payload)
    )
