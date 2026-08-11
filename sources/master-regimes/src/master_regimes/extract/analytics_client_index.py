from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _rel(root: Path, path: Path | str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(candidate)


def index_analytics_fdw_run(*, run_dir: Path, out_dir: Path | None = None) -> Path:
    root = run_dir.resolve()
    if out_dir is None:
        out_dir = root / "_index"
    else:
        out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    feature_file = root / "results" / "master_regimes_fdw_features.csv"
    options_file = root / "results" / "fdw_options_snapshot.csv"
    features = _read_csv(feature_file)
    options = _read_csv(options_file)

    feature_rows: list[dict[str, Any]] = []
    for row in features:
        indexed = dict(row)
        indexed["analytics_client_run_dir"] = str(root)
        indexed["source_feature_file"] = _rel(root, feature_file)
        feature_rows.append(indexed)

    option_rows: list[dict[str, Any]] = []
    for row in options:
        indexed = dict(row)
        indexed["analytics_client_run_dir"] = str(root)
        indexed["source_options_file"] = _rel(root, options_file)
        option_rows.append(indexed)

    feature_fields = [
        "feature_contract",
        "run_id",
        "execution_id",
        "template_id",
        "instance_id",
        "query_id",
        "query_shape",
        "variables_json",
        "remote_sql_class",
        "remote_sql_count",
        "has_remote_reduction",
        "has_remote_predicate",
        "has_local_reduction",
        "has_local_filter",
        "classification_error",
        "classification_notes",
        "remote_sql_json",
        "explain_file",
        "classification_file",
        "fdw_options_snapshot_file",
        "analytics_client_run_dir",
        "source_feature_file",
    ]
    option_fields = [
        "object_type",
        "server_name",
        "role_name",
        "schema_name",
        "foreign_table_name",
        "option_name",
        "option_value",
        "is_secret",
        "is_master_regimes_relevant",
        "analytics_client_run_dir",
        "source_options_file",
    ]
    _write_csv(out_dir / "analytics_fdw_features.csv", feature_rows, feature_fields)
    _write_csv(out_dir / "analytics_fdw_options.csv", option_rows, option_fields)

    summary = {
        "analytics_client_run_dir": str(root),
        "index_dir": str(out_dir),
        "feature_file": str(feature_file),
        "options_file": str(options_file),
        "feature_count": len(feature_rows),
        "fdw_option_count": len(option_rows),
        "feature_contract": "analytics_client_fdw_classifier_v1",
    }
    (out_dir / "index_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_dir
