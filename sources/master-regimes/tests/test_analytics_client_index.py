from __future__ import annotations

import csv
from pathlib import Path

from master_regimes.extract.analytics_client_index import index_analytics_fdw_run


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_index_analytics_fdw_run_links_features_and_fdw_options(tmp_path: Path) -> None:
    run_dir = tmp_path / "analytics-run"
    _write_csv(
        run_dir / "results" / "master_regimes_fdw_features.csv",
        [
            {
                "feature_contract": "analytics_client_fdw_classifier_v1",
                "run_id": "run-1",
                "execution_id": "run-1:a1",
                "template_id": "analytics-client:a1",
                "instance_id": "analytics-client:a1__x",
                "query_id": "a1",
                "query_shape": "daily_kpi",
                "variables_json": "{}",
                "remote_sql_class": "reduction_pushdown",
                "remote_sql_count": "1",
                "has_remote_reduction": "True",
                "has_remote_predicate": "True",
                "has_local_reduction": "False",
                "has_local_filter": "False",
                "classification_error": "",
                "classification_notes": "",
                "remote_sql_json": "[]",
                "explain_file": "results/fdw_explain_a1.txt",
                "classification_file": "results/fdw_explain_a1.classification.json",
                "fdw_options_snapshot_file": "results/fdw_options_snapshot.csv",
            }
        ],
    )
    _write_csv(
        run_dir / "results" / "fdw_options_snapshot.csv",
        [
            {
                "object_type": "server",
                "server_name": "eu_citus",
                "role_name": "",
                "schema_name": "",
                "foreign_table_name": "",
                "option_name": "fetch_size",
                "option_value": "1000",
                "is_secret": "false",
                "is_master_regimes_relevant": "true",
            }
        ],
    )

    out_dir = index_analytics_fdw_run(run_dir=run_dir)

    features = list(csv.DictReader((out_dir / "analytics_fdw_features.csv").open()))
    options = list(csv.DictReader((out_dir / "analytics_fdw_options.csv").open()))

    assert features[0]["execution_id"] == "run-1:a1"
    assert features[0]["remote_sql_class"] == "reduction_pushdown"
    assert options[0]["option_name"] == "fetch_size"
    assert options[0]["is_master_regimes_relevant"] == "true"
