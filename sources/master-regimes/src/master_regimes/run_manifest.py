from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_yaml, stable_slug, write_yaml


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_metadata(root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"repository": root.name, "commit": commit, "dirty": dirty}
    except Exception:
        return {"repository": root.name, "commit": "unknown", "dirty": None}


def create_run_manifest(
    *,
    root: Path,
    system_path: Path,
    dataset_path: Path,
    sweep_path: Path,
    output_root: Path,
    run_id: str | None = None,
) -> Path:
    now = datetime.now(UTC)
    system = load_yaml(system_path)
    dataset = load_yaml(dataset_path)
    sweep = load_yaml(sweep_path)
    run_id = run_id or (
        f"{now.strftime('%Y%m%dT%H%M%SZ')}__"
        f"{stable_slug(str(sweep.get('sweep_id', 'sweep')))}__"
        f"{stable_slug(str(dataset.get('dataset_id', 'dataset')))}"
    )
    run_dir = output_root / run_id
    for child in (
        "rendered_sql",
        "raw/explain_json",
        "raw/explain_text",
        "raw/query_results",
        "raw/pg_snapshots",
        "raw/citus_snapshots",
        "raw/os_metrics",
        "raw/network",
        "extracted",
        "features",
        "models",
        "reports",
    ):
        (run_dir / child).mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": run_id,
        "created_at_utc": now.isoformat().replace("+00:00", "Z"),
        "purpose": sweep.get("purpose", sweep.get("sweep_id", "unspecified")),
        "system": system,
        "dataset": {
            **dataset,
            "profile_file": str(dataset_path),
            "profile_sha256": _sha256(dataset_path),
        },
        "workload": sweep.get("workload", {}),
        "configuration": sweep.get("configuration", {}),
        "budgets": sweep.get("budgets", {}),
        "artifacts": {
            "rendered_sql_dir": "rendered_sql/",
            "explain_json_dir": "raw/explain_json/",
            "query_timings_csv": "raw/query_timings.csv",
            "pg_snapshots_dir": "raw/pg_snapshots/",
            "citus_snapshots_dir": "raw/citus_snapshots/",
            "os_metrics_dir": "raw/os_metrics/",
            "network_report": "raw/network/network-calibration.json",
        },
        "git": _git_metadata(root),
        "tooling": {
            "package_manager": "uv",
            "python_version": "3.14.5",
        },
        "source_files": {
            "system": str(system_path),
            "system_sha256": _sha256(system_path),
            "dataset": str(dataset_path),
            "sweep": str(sweep_path),
            "sweep_sha256": _sha256(sweep_path),
        },
    }
    write_yaml(run_dir / "run_manifest.yml", manifest)
    return run_dir
