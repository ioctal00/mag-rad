from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "common-scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_regional_loader_targets_isolated_stats_schema() -> None:
    module = _load("apply_stats_ceb_profile")
    script = module.regional_load_script(
        dump_path="/cache/stats_dump.pg",
        ddl_path="/cache/citus.sql",
        regional_database="app",
        regional_schema="stats",
        staging_database="stats_stage",
    )

    assert "DROP SCHEMA IF EXISTS stats CASCADE" in script
    assert "pg_restore --exit-on-error --no-owner --no-privileges" in script
    assert "--schema=public" in script
    assert "pg_dump --no-owner --no-privileges --schema=stats" in script
    assert "-d app -f /cache/citus.sql" in script
    assert "Expected eight STATS tables" in script
    assert "Expected eight STATS Citus metadata rows" in script


def test_citus_design_keeps_nullable_tags_as_reference_table() -> None:
    ddl = (
        ROOT.parent
        / "master-regimes"
        / "configs"
        / "stats-ceb"
        / "citus-post-centric-v1.sql"
    ).read_text(encoding="utf-8")

    assert "create_reference_table('stats.tags')" in ddl
    assert "create_distributed_table(\n  'stats.tags'" not in ddl


def test_fdw_bootstrap_uses_existing_regional_servers() -> None:
    module = _load("run_stats_ceb_fdw_bootstrap")
    sql = module.fdw_sql(
        database="analytics",
        source_schema="stats",
        target_schema="stats_eu",
        server_name="eu_citus",
        options={"fetch_size": "1000"},
    )

    assert "IMPORT FOREIGN SCHEMA stats" in sql
    assert "FROM SERVER eu_citus" in sql
    assert "INTO stats_eu" in sql
    assert "Expected eight STATS foreign tables" in sql
    assert "ALTER SERVER eu_citus" in sql


def test_correctness_hash_is_stable_and_does_not_encode_rows() -> None:
    module = _load("validate_stats_ceb_correctness")
    assert module.result_hash("79851") == module.result_hash("79851\n")
    assert module.result_hash("79851") != module.result_hash("79852")
    assert module.schema_hash()


def test_correctness_failure_classification_separates_timeout_and_infrastructure() -> None:
    module = _load("validate_stats_ceb_correctness")

    assert (
        module.classify_psql_failure(
            "ERROR: canceling statement due to statement timeout"
        )
        == "timeout"
    )
    assert (
        module.classify_psql_failure(
            "server closed the connection unexpectedly"
        )
        == "infrastructure_failure"
    )
    assert module.classify_psql_failure("ERROR: syntax error at or near FROM") == "unsupported_sql"


def test_database_sweep_filters_collection_manifest_to_passed_queries(
    tmp_path: Path,
) -> None:
    module = _load("run_database_sweep")
    source = tmp_path / "instance_manifest.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instance_id", "param_json"])
        writer.writeheader()
        writer.writerow({"instance_id": "q1", "param_json": json.dumps({"query_id": 1})})
        writer.writerow({"instance_id": "q2", "param_json": json.dumps({"query_id": 2})})
    correctness_dir = tmp_path / "correctness"
    correctness_dir.mkdir()
    with (correctness_dir / "result_equivalence.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["query_id", "comparison_status"],
        )
        writer.writeheader()
        writer.writerow({"query_id": 1, "comparison_status": "passed"})
        writer.writerow({"query_id": 2, "comparison_status": "timeout"})

    out_path, count = module.filter_instance_manifest_by_correctness(
        instance_manifest=source,
        correctness_dir=correctness_dir,
        out_path=tmp_path / "eligible.csv",
    )

    with out_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert count == 1
    assert [row["instance_id"] for row in rows] == ["q1"]


def test_database_sweep_filters_recovery_manifest_by_runtime(
    tmp_path: Path,
) -> None:
    module = _load("run_database_sweep")
    source = tmp_path / "instances.csv"
    source.write_text(
        "instance_id,runtime_config_id\nfirst,stressed\nsecond,mitigated\n",
        encoding="utf-8",
    )

    out_path, count = module.filter_instance_manifest_by_runtime(
        instance_manifest=source,
        runtime_config_id="mitigated",
        out_path=tmp_path / "selected.csv",
    )

    assert count == 1
    assert out_path.read_text(encoding="utf-8").splitlines() == [
        "instance_id,runtime_config_id",
        "second,mitigated",
    ]


def test_database_sweep_dispatches_stats_fdw_adapter(monkeypatch, tmp_path: Path) -> None:
    module = _load("run_database_sweep")
    observed: list[str] = []

    def fake_run(command, *, component):
        observed.extend(str(value) for value in command)
        assert component == "FDW"
        return tmp_path / "fdw"

    monkeypatch.setattr(module, "run_and_get_path", fake_run)
    module.run_fdw_bootstrap(
        region="eu",
        sweep_label="pilot",
        dataset_id="stats",
        profile_path=tmp_path / "profile.yml",
        out_root=tmp_path,
        fdw_bootstrap={"adapter": "stats_ceb", "region": "eu"},
    )

    assert any(value.endswith("run_stats_ceb_fdw_bootstrap.py") for value in observed)
    assert "--profile" in observed
