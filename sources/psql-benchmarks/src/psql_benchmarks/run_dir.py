from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import subprocess

from .settings import ROOT_DIR, Settings


def _safe_label(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value)
    encoded = safe.encode("utf-8")
    if len(encoded) <= 160:
        return safe
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    prefix = encoded[:140].decode("utf-8", errors="ignore").rstrip("-_")
    return f"{prefix}--{digest}"


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def create_run_dir(settings: Settings, *, mode: str, label: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = settings.run_root / f"{timestamp}-{mode}-{_safe_label(label)}"
    for child in ("queries", "results", "plans", "metrics", "logs", "snapshots"):
        (run_dir / child).mkdir(parents=True, exist_ok=True)

    metadata = {
        "timestamp_utc": timestamp,
        "mode": mode,
        "label": label,
        "node_role": settings.bench_node_role,
        "region": settings.bench_region,
        "application_name": settings.bench_application_name,
        "cluster_label": settings.bench_cluster_label,
        "dataset_label": settings.bench_dataset_label,
        "datagen_parameters": settings.datagen_parameters,
        "notes": settings.bench_notes,
        "sample_interval_seconds": settings.bench_sample_interval_seconds,
        "capture_duration_seconds": settings.bench_capture_duration_seconds,
        "warmup_iterations": settings.bench_warmup_iterations,
        "measurement_iterations": settings.bench_measurement_iterations,
        "pg": {
            "host": settings.pg_host,
            "port": settings.pg_port,
            "database": settings.pg_database,
            "user": settings.pg_user,
            "sslmode": settings.pg_sslmode,
            "sslrootcert": settings.pg_sslrootcert,
        },
        "tool_git_sha": _git_sha(),
        "platform": {
            "hostname": platform.node(),
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_dir
