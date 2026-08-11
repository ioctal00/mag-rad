from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "common-scripts"
    / "index_database_sweep.py"
)


def _load_indexer():
    spec = importlib.util.spec_from_file_location("index_database_sweep", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repeatability_identity_is_preserved_in_query_runs() -> None:
    indexer = _load_indexer()

    assert "condition_id" in indexer.CORPUS_METADATA_FIELDS
    assert "repetition_index" in indexer.CORPUS_METADATA_FIELDS
    assert "run_order" in indexer.CORPUS_METADATA_FIELDS
    assert "remote_shape_id" in indexer.CORPUS_METADATA_FIELDS
    assert "edge_stress_scope" in indexer.CORPUS_METADATA_FIELDS
    assert "transfer_volume_level" in indexer.CORPUS_METADATA_FIELDS
    assert "network_subblock" in indexer.CORPUS_METADATA_FIELDS


def test_versioned_derived_feature_is_preserved_in_query_runs() -> None:
    indexer = _load_indexer()
    query_rows = [
        {"query_run_id": "run-a"},
        {"query_run_id": "run-b"},
        {"query_run_id": "run-without-index-row"},
    ]
    execution_feature_rows = [
        {"query_run_id": "run-a", "citus_repartition_observed_v2": "True"},
        {"query_run_id": "run-b", "citus_repartition_observed_v2": "False"},
    ]

    indexer.enrich_query_rows_from_execution_features(
        query_rows,
        execution_feature_rows,
    )

    assert "citus_repartition_observed_v2" in (
        indexer.QUERY_RUN_DERIVED_PASSTHROUGH_FIELDS
    )
    assert query_rows[0]["citus_repartition_observed_v2"] == "True"
    assert query_rows[1]["citus_repartition_observed_v2"] == "False"
    assert "citus_repartition_observed_v2" not in query_rows[2]


def test_worker_network_proxies_are_preserved_in_query_runs() -> None:
    indexer = _load_indexer()

    for field in (
        "worker_rx_bytes_sum",
        "worker_tx_bytes_sum",
        "worker_rx_bytes_cv",
        "worker_tx_bytes_cv",
        "worker_rx_bytes_max_share",
        "worker_tx_bytes_max_share",
        "worker_network_regions_json",
    ):
        assert field in indexer.QUERY_RUN_DERIVED_PASSTHROUGH_FIELDS


def test_coordinator_pressure_fields_are_preserved_in_query_runs() -> None:
    indexer = _load_indexer()
    query_rows = [{"query_run_id": "run-a"}]
    execution_feature_rows = [
        {
            "query_run_id": "run-a",
            "coordinator_fanin_rows": "1200",
            "coordinator_join_input_rows_sum": "2400",
            "coordinator_spill_present": "true",
        }
    ]

    indexer.enrich_query_rows_from_execution_features(
        query_rows,
        execution_feature_rows,
    )

    assert "coordinator_fanin_rows" in indexer.COORDINATOR_PRESSURE_PASSTHROUGH_FIELDS
    assert query_rows[0]["coordinator_fanin_rows"] == "1200"
    assert query_rows[0]["coordinator_join_input_rows_sum"] == "2400"
    assert query_rows[0]["coordinator_spill_present"] == "true"


def test_stats_correctness_contract_is_a_normalized_index_table() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'out_dir / "result_validations.csv"' in source
    assert '"database_result_rows_persisted"' in source


def test_remote_edge_observations_are_a_normalized_child_table() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'out_dir / "remote_edge_observations.csv"' in source
    assert '"query_run_id",' in source
    assert '"edge_id",' in source


def test_read_csv_accepts_large_plan_fields(tmp_path: Path) -> None:
    indexer = _load_indexer()
    path = tmp_path / "query_runs.csv"
    large_plan = "x" * 200_000
    path.write_text(
        f"query_run_id,plan_json\nrun-a,{large_plan}\n",
        encoding="utf-8",
    )

    assert indexer.read_csv(path) == [
        {"query_run_id": "run-a", "plan_json": large_plan}
    ]
