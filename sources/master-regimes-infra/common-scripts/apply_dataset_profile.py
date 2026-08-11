#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"
DATAGEN_KEYS = (
    "DATAGEN_REGION",
    "DATAGEN_TENANT_START",
    "DATAGEN_TENANT_END",
    "DATAGEN_TENANT_RANGES",
    "DATAGEN_EVENT_ID_MODE",
    "DATAGEN_OUTPUT_DIR",
    "DATAGEN_RANDOM_SEED",
    "DATAGEN_EVENTS_PER_TENANT",
    "DATAGEN_USERS_PER_TENANT",
    "DATAGEN_GLOBAL_USERS_PER_TENANT",
    "DATAGEN_ENABLE_GLOBAL_USERS",
    "DATAGEN_LOOKBACK_DAYS",
    "DATAGEN_PROGRESS_EVERY_TENANTS",
    "DATAGEN_LOAD_METHOD",
    "DATAGEN_SQL_BATCH_TENANTS",
    "DATAGEN_DISTRIBUTION",
    "DATAGEN_HOT_TENANT_PCT",
    "DATAGEN_HOT_EVENT_PCT",
    "DATAGEN_BASE_TIME_UNIX",
    "DATAGEN_SHARD_COUNT",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a citus-datagen dataset profile.")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--region", default="eu")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "dataset-loads",
    )
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--remote-datagen-dir", default="/opt/citus-datagen")
    parser.add_argument("--load-method", choices=("sql", "csv", "copy_pipe"), default="sql")
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Collect dataset audit/mapping artifacts without rebuilding the dataset.",
    )
    return parser.parse_args()


def load_shell_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if not parts:
            continue
        assignment = parts[1] if parts[0] == "export" and len(parts) >= 2 else parts[0]
        if "=" not in assignment:
            continue
        key, value = assignment.split("=", 1)
        values[key] = value
    return values


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def load_coordinator(path: Path, *, region: str) -> tuple[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    coordinators = data["all"]["children"]["coordinators"]["hosts"]
    if not coordinators:
        raise RuntimeError("No coordinator found in generated inventory.")
    regional_hosts = (
        data["all"]["children"].get(region, {}).get("hosts", {})
        if isinstance(data["all"]["children"].get(region, {}), dict)
        else {}
    )
    regional_coordinators = sorted(
        name for name in coordinators if name in regional_hosts or name.startswith(f"{region}-")
    )
    if not regional_coordinators:
        available = ", ".join(sorted(coordinators))
        raise RuntimeError(
            f"No coordinator found for region {region!r}. Available coordinators: {available}"
        )
    name = regional_coordinators[0]
    return name, coordinators[name]


def ssh_base(host: str, user: str, key_file: Path | None) -> list[str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=4",
    ]
    if key_file is not None:
        command.extend(["-i", str(key_file), "-o", "IdentitiesOnly=yes"])
    command.append(f"{user}@{host}")
    return command


def ssh_run(
    host: str,
    user: str,
    key_file: Path | None,
    remote_script: str,
    *,
    attempts: int = 3,
    retry_delay_seconds: float = 2.0,
) -> subprocess.CompletedProcess[str]:
    command = [*ssh_base(host, user, key_file), f"bash -lc {shlex.quote(remote_script)}"]
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return result
        if result.returncode != 255 or attempt == attempts:
            result.check_returncode()
        time.sleep(retry_delay_seconds * attempt)
    raise AssertionError("unreachable")


def region_distribution(profile: dict[str, Any], *, region: str) -> dict[str, Any]:
    """Return global distribution with optional per-region overrides applied."""
    global_distribution = profile.get("distribution", {}) or {}
    if not isinstance(global_distribution, dict):
        global_distribution = {}
    regions = profile.get("regions", {}) or {}
    region_spec = regions.get(region, {}) if isinstance(regions, dict) else {}
    region_override = region_spec.get("distribution", {}) if isinstance(region_spec, dict) else {}
    if not isinstance(region_override, dict):
        region_override = {}
    return {**global_distribution, **region_override}


def expected_hot_tenant_count(
    profile: dict[str, Any],
    *,
    region: str,
    tenant_count: int,
) -> int:
    distribution = region_distribution(profile, region=region)
    skew_profile = str(distribution.get("skew_profile", "balanced"))
    if skew_profile not in {"heavy", "hot_tenants"} or tenant_count <= 0:
        return 0
    hot_tenant_pct = float(distribution.get("hot_tenant_pct", 1))
    hot_count = int((tenant_count * hot_tenant_pct / 100.0) + 0.5)
    return max(1, min(hot_count, tenant_count))


def dataset_env(profile: dict[str, Any], *, region: str, load_method: str) -> dict[str, str]:
    scale = profile.get("scale", {})
    regions = profile.get("regions", {})
    if region not in regions:
        raise ValueError(f"Dataset profile has no region entry: {region}")
    region_spec = regions[region]
    tenant_range = region_spec.get("tenant_id_range")
    tenant_ranges = region_spec.get("tenant_id_ranges")
    if tenant_ranges is None:
        if not isinstance(tenant_range, list) or len(tenant_range) != 2:
            raise ValueError(f"Invalid tenant_id_range for region {region}")
        logical_region = str(region_spec.get("data_region_id", region))
        normalized_ranges = [[tenant_range[0], tenant_range[1], logical_region]]
    else:
        if not isinstance(tenant_ranges, list) or not tenant_ranges:
            raise ValueError(f"Invalid tenant_id_ranges for region {region}")
        normalized_ranges = []
        for item in tenant_ranges:
            if not isinstance(item, list) or len(item) not in {2, 3}:
                raise ValueError(f"Invalid tenant_id_ranges entry for region {region}: {item}")
            logical_region = str(item[2] if len(item) == 3 else region)
            if int(item[0]) > int(item[1]) or not logical_region:
                raise ValueError(f"Invalid tenant_id_ranges entry for region {region}: {item}")
            normalized_ranges.append([int(item[0]), int(item[1]), logical_region])
        tenant_range = [normalized_ranges[0][0], normalized_ranges[0][1]]

    tenant_ranges_env = ",".join(
        f"{start}:{end}:{logical_region}"
        for start, end, logical_region in normalized_ranges
    )

    distribution = region_distribution(profile, region=region)
    skew_profile = str(distribution.get("skew_profile", "balanced"))
    datagen_distribution = "hot_tenants" if skew_profile in {"heavy", "hot_tenants"} else "uniform"
    hot_tenant_pct = max(1, int(distribution.get("hot_tenant_pct", 1)))
    hot_event_pct = max(1, int(distribution.get("hot_event_pct", 50)))
    dataset_id = str(profile.get("dataset_id", "dataset"))
    return {
        "DATAGEN_REGION": region,
        "DATAGEN_TENANT_START": str(tenant_range[0]),
        "DATAGEN_TENANT_END": str(tenant_range[1]),
        "DATAGEN_TENANT_RANGES": tenant_ranges_env,
        "DATAGEN_EVENT_ID_MODE": str(
            profile.get("identity", {}).get("event_id_mode", "local_sequential")
        ),
        "DATAGEN_OUTPUT_DIR": f"/var/lib/citus-datagen/generated/{dataset_id}/{region}",
        "DATAGEN_RANDOM_SEED": str(profile.get("seed", 42)),
        "DATAGEN_EVENTS_PER_TENANT": str(scale.get("events_per_tenant_avg", 100)),
        "DATAGEN_USERS_PER_TENANT": str(scale.get("users_per_tenant_avg", 50)),
        "DATAGEN_GLOBAL_USERS_PER_TENANT": str(
            scale.get(
                "global_users_per_tenant_avg",
                scale.get("users_per_tenant_avg", 50),
            )
        ),
        "DATAGEN_ENABLE_GLOBAL_USERS": "true",
        "DATAGEN_LOOKBACK_DAYS": str(scale.get("lookback_days", 30)),
        "DATAGEN_PROGRESS_EVERY_TENANTS": "1000",
        "DATAGEN_LOAD_METHOD": load_method,
        "DATAGEN_SQL_BATCH_TENANTS": "1000",
        "DATAGEN_DISTRIBUTION": datagen_distribution,
        "DATAGEN_HOT_TENANT_PCT": str(hot_tenant_pct),
        "DATAGEN_HOT_EVENT_PCT": str(hot_event_pct),
        "DATAGEN_BASE_TIME_UNIX": str(profile.get("base_time_unix", 0)),
        "DATAGEN_SHARD_COUNT": str(distribution.get("shard_count", 32)),
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remote_psql_csv(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    remote_datagen_dir: str,
    sql: str,
) -> subprocess.CompletedProcess[str]:
    remote_script = f"""
set -euo pipefail
cd {shlex.quote(remote_datagen_dir)}
set -a
. ./.env
set +a
PGHOST="${{POSTGRES_HOST:-${{PGHOST:-127.0.0.1}}}}"
PGPORT="${{POSTGRES_PORT:-${{PGPORT:-5432}}}}"
PGDATABASE="${{POSTGRES_DB:-${{PGDATABASE:-app}}}}"
PGUSER="${{POSTGRES_USER:-${{PGUSER:-postgres}}}}"
export PGPASSWORD="${{POSTGRES_PASSWORD:-${{PGPASSWORD:-}}}}"
export PGSSLMODE="${{POSTGRES_SSL_MODE:-${{PGSSLMODE:-disable}}}}"
PGSSLROOTCERT="${{POSTGRES_SSL_ROOT_CERT:-${{PGSSLROOTCERT:-}}}}"
if [ -n "$PGSSLROOTCERT" ]; then
  export PGSSLROOTCERT
fi
psql -X -v ON_ERROR_STOP=1 --csv \\
  -h "$PGHOST" \\
  -p "$PGPORT" \\
  -U "$PGUSER" \\
  -d "$PGDATABASE" <<'DATASET_AUDIT_SQL'
{sql.strip()}
DATASET_AUDIT_SQL
""".strip()
    return ssh_run(host, user, key_file, remote_script)


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    if value in ("", None):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _series_stats(values: list[float]) -> dict[str, float]:
    count = len(values)
    total = sum(values)
    mean = total / count if count else 0.0
    variance = sum((value - mean) ** 2 for value in values) / count if count else 0.0
    stddev = math.sqrt(variance)
    max_value = max(values) if values else 0.0
    min_value = min(values) if values else 0.0
    return {
        "count": float(count),
        "total": total,
        "mean": mean,
        "stddev": stddev,
        "cv": stddev / mean if mean else 0.0,
        "min": min_value,
        "max": max_value,
        "max_to_mean_ratio": max_value / mean if mean else 0.0,
    }


def _write_hot_tenant_manifest(
    path: Path,
    tenant_rows: list[dict[str, str]],
    *,
    hot_tenant_count: int,
) -> list[dict[str, str]]:
    total_events = sum(_float(row, "events_count") for row in tenant_rows)
    hot_rows = tenant_rows[:hot_tenant_count] if hot_tenant_count > 0 else []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["tenant_rank", "tenant_id", "events_count", "event_share", "total_value"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(hot_rows, start=1):
            events_count = _float(row, "events_count")
            writer.writerow(
                {
                    "tenant_rank": index,
                    "tenant_id": row.get("tenant_id", ""),
                    "events_count": row.get("events_count", ""),
                    "event_share": events_count / total_events if total_events else "",
                    "total_value": row.get("total_value", ""),
                }
            )
    return hot_rows


def _tenant_id(row: dict[str, str]) -> int:
    return int(_float(row, "tenant_id"))


def _tenant_events(row: dict[str, str]) -> int:
    return int(_float(row, "events_count"))


def _sql_values_for_tenants(
    *,
    selected_rows: list[dict[str, str]],
    hot_tenant_ids: set[int],
) -> str:
    values = []
    for row in selected_rows:
        tenant_id = _tenant_id(row)
        role = "hot" if tenant_id in hot_tenant_ids else "cold_probe"
        events_count = _tenant_events(row)
        values.append(f"({tenant_id}, {events_count}, '{role}')")
    return ",\n  ".join(values) if values else "(null::bigint, null::bigint, 'empty')"


def _write_hot_tenant_worker_summary(
    path: Path,
    mapping_rows: list[dict[str, str]],
) -> dict[str, Any]:
    hot_rows = [row for row in mapping_rows if row.get("tenant_role") == "hot"]
    by_worker: dict[str, dict[str, Any]] = {}
    for row in hot_rows:
        worker = row.get("node_name") or "unknown"
        bucket = by_worker.setdefault(
            worker,
            {
                "node_name": worker,
                "node_port": row.get("node_port", ""),
                "hot_tenant_ids": [],
                "hot_tenant_count": 0,
                "hot_events_count": 0,
            },
        )
        bucket["hot_tenant_ids"].append(_tenant_id(row))
        bucket["hot_tenant_count"] += 1
        bucket["hot_events_count"] += _tenant_events(row)

    total_hot_events = sum(int(item["hot_events_count"]) for item in by_worker.values())
    summary_rows = []
    for item in by_worker.values():
        hot_events_count = int(item["hot_events_count"])
        summary_rows.append(
            {
                "node_name": item["node_name"],
                "node_port": item["node_port"],
                "hot_tenant_count": item["hot_tenant_count"],
                "hot_events_count": hot_events_count,
                "hot_event_share": hot_events_count / total_hot_events if total_hot_events else "",
                "hot_tenant_ids": " ".join(str(value) for value in item["hot_tenant_ids"]),
            }
        )
    summary_rows.sort(
        key=lambda row: (
            -int(row["hot_events_count"]),
            str(row["node_name"]),
            str(row["node_port"]),
        )
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "node_name",
            "node_port",
            "hot_tenant_count",
            "hot_events_count",
            "hot_event_share",
            "hot_tenant_ids",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    dominant = summary_rows[0] if summary_rows else {}
    dominant_tenant_ids = [
        int(value) for value in str(dominant.get("hot_tenant_ids", "")).split() if value.strip()
    ]
    return {
        "path": str(path),
        "worker_count": len(summary_rows),
        "dominant_hot_worker": dominant.get("node_name", ""),
        "dominant_hot_worker_port": dominant.get("node_port", ""),
        "dominant_hot_worker_hot_tenant_count": int(dominant.get("hot_tenant_count", 0) or 0),
        "dominant_hot_worker_hot_event_share": float(dominant.get("hot_event_share", 0.0) or 0.0),
        "dominant_hot_worker_hot_tenant_ids": dominant_tenant_ids,
        "dominant_hot_worker_probe_ids": dominant_tenant_ids[:20],
    }


def _write_dataset_parameter_values(
    path: Path,
    *,
    profile: dict[str, Any],
    tenant_rows: list[dict[str, str]],
    hot_tenant_rows: list[dict[str, str]],
    tenant_worker_mapping_path: Path,
    hot_tenant_worker_mapping_path: Path,
    hot_tenant_worker_summary: dict[str, Any],
    hot_tenant_path: Path,
    tenant_distribution_path: Path,
) -> dict[str, Any]:
    tenant_ids = [
        int(_float(row, "tenant_id"))
        for row in sorted(tenant_rows, key=lambda item: _float(item, "tenant_id"))
        if row.get("tenant_id")
    ]
    hot_tenant_ids = [
        int(_float(row, "tenant_id")) for row in hot_tenant_rows if row.get("tenant_id")
    ]
    hot_set = set(hot_tenant_ids)
    cold_tenant_ids = [tenant_id for tenant_id in tenant_ids if tenant_id not in hot_set]
    hot_probe_ids = hot_tenant_ids[: min(20, len(hot_tenant_ids))]
    cold_probe_ids = cold_tenant_ids[: min(20, len(cold_tenant_ids))]
    parameter_sources = (
        profile.get("expected_audit_signals", {}).get("parameter_sources", {})
        if isinstance(profile.get("expected_audit_signals"), dict)
        else {}
    )
    payload = {
        "dataset_id": profile.get("dataset_id", ""),
        "sources": parameter_sources,
        "artifacts": {
            "tenant_distribution": str(tenant_distribution_path),
            "hot_tenant_manifest": str(hot_tenant_path),
            "tenant_worker_mapping": str(tenant_worker_mapping_path),
            "hot_tenant_worker_mapping": str(hot_tenant_worker_mapping_path),
            "hot_tenant_worker_summary": str(hot_tenant_worker_summary.get("path", "")),
        },
        "parameter_values": {
            "tenant_ids": tenant_ids,
            "hot_tenant_ids": hot_tenant_ids,
            "hot_tenant_probe_ids": hot_probe_ids,
            "cold_tenant_ids": cold_tenant_ids,
            "cold_tenant_probe_ids": cold_probe_ids,
            "skew_probe_tenant_ids": [*hot_probe_ids[:10], *cold_probe_ids[:10]],
            "dominant_hot_worker": hot_tenant_worker_summary.get("dominant_hot_worker", ""),
            "dominant_hot_worker_hot_tenant_ids": hot_tenant_worker_summary.get(
                "dominant_hot_worker_hot_tenant_ids", []
            ),
            "dominant_hot_worker_probe_ids": hot_tenant_worker_summary.get(
                "dominant_hot_worker_probe_ids", []
            ),
        },
    }
    write_json(path, payload)
    return {
        "path": str(path),
        "tenant_count": len(tenant_ids),
        "hot_tenant_count": len(hot_tenant_ids),
        "cold_tenant_count": len(cold_tenant_ids),
        "hot_tenant_probe_count": len(hot_probe_ids),
        "cold_tenant_probe_count": len(cold_probe_ids),
        "dominant_hot_worker": hot_tenant_worker_summary.get("dominant_hot_worker", ""),
        "dominant_hot_worker_hot_tenant_count": hot_tenant_worker_summary.get(
            "dominant_hot_worker_hot_tenant_count", 0
        ),
        "dominant_hot_worker_hot_event_share": hot_tenant_worker_summary.get(
            "dominant_hot_worker_hot_event_share", 0.0
        ),
    }


def _dataset_audit_payload(
    *,
    profile: dict[str, Any],
    counts_rows: list[dict[str, str]],
    tenant_rows: list[dict[str, str]],
    shard_rows: list[dict[str, str]],
    shard_error: str | None,
    dataset_parameter_values: dict[str, Any],
    hot_tenant_rows: list[dict[str, str]],
    hot_tenant_worker_summary: dict[str, Any],
) -> dict[str, Any]:
    capabilities = profile.get("capabilities", {}) or {}
    counts = {
        str(row.get("table_name", "")): int(_float(row, "row_count"))
        for row in counts_rows
        if row.get("table_name")
    }
    event_counts = [_float(row, "events_count") for row in tenant_rows]
    total_events = sum(event_counts)
    tenant_count = len(event_counts)
    mean_events = total_events / tenant_count if tenant_count else 0.0
    variance = (
        sum((value - mean_events) ** 2 for value in event_counts) / tenant_count
        if tenant_count
        else 0.0
    )
    stddev = math.sqrt(variance)
    max_events = max(event_counts) if event_counts else 0.0
    top1_share = (max_events / total_events) if total_events else 0.0
    top5_share = sum(sorted(event_counts, reverse=True)[:5]) / total_events if total_events else 0.0
    hot_event_share = (
        sum(_float(row, "events_count") for row in hot_tenant_rows) / total_events
        if total_events
        else 0.0
    )
    cv = stddev / mean_events if mean_events else 0.0
    max_to_mean = max_events / mean_events if mean_events else 0.0
    measured_hot_skew = (
        hot_event_share >= 0.25
        or top1_share >= 0.05
        or top5_share >= 0.25
        or cv >= 0.75
        or max_to_mean >= 2.5
    )
    shard_size_stats = _series_stats(
        [_float(row, "shard_size_bytes") for row in shard_rows if row.get("shard_size_bytes")]
    )
    measured_shard_skew = (
        shard_size_stats["cv"] >= 0.75 or shard_size_stats["max_to_mean_ratio"] >= 2.5
    )
    regions = profile.get("regions", {}) if isinstance(profile.get("regions"), dict) else {}
    dataset_time_contract = _dataset_time_contract(profile, tenant_rows)

    measured = {
        "supports_reference_join": counts.get("tenants", 0) > 0,
        "supports_colocated_user_join": counts.get("users", 0) > 0,
        "supports_global_users": counts.get("global_users", 0) > 0,
        "supports_global_user_dimension": counts.get("global_users", 0) > 0,
        "supports_non_colocated_join": counts.get("global_users", 0) > 0,
        "supports_cross_region_user_overlap": False,
        "supports_high_group_cardinality": counts.get("users", 0) >= 1000,
        "supports_hot_tenants": measured_hot_skew,
        "supports_hot_time_windows": False,
        "supports_hot_tenant_skew": measured_hot_skew,
        "supports_shard_skew": measured_shard_skew,
        "supports_wide_payload": False,
        "supports_large_scan": counts.get("events", 0) >= 100000,
        "supports_distribution_key_filter": counts.get("events", 0) > 0,
        "supports_region_partitioning": len(regions) > 1,
        "supports_etl_rollups": counts.get("events", 0) > 0,
        "supports_tenant_tiers": counts.get("tenants", 0) > 0,
        "supports_selective_filters": counts.get("events", 0) > 0,
        "supports_materialized_refresh": counts.get("events", 0) > 0,
    }
    warnings = []
    for capability, declared_value in sorted(capabilities.items()):
        if declared_value is True and measured.get(capability) is False:
            warnings.append(
                {
                    "capability": capability,
                    "declared": True,
                    "measured": False,
                    "severity": "warning",
                }
            )

    return {
        "dataset_id": profile.get("dataset_id", ""),
        "dataset_time_contract": dataset_time_contract,
        "declared_distribution": profile.get("distribution", {}),
        "declared_capabilities": capabilities,
        "expected_audit_signals": profile.get("expected_audit_signals", {}),
        "measured_capabilities": measured,
        "dataset_parameter_values": dataset_parameter_values,
        "table_counts": counts,
        "tenant_skew": {
            "tenant_count": tenant_count,
            "events_total": total_events,
            "events_mean": mean_events,
            "events_stddev": stddev,
            "events_cv": cv,
            "events_max": max_events,
            "max_to_mean_ratio": max_to_mean,
            "top1_event_share": top1_share,
            "top5_event_share": top5_share,
            "hot_tenant_count": len(hot_tenant_rows),
            "hot_event_share": hot_event_share,
        },
        "tenant_placement": {
            "hot_worker_count": hot_tenant_worker_summary.get("worker_count", 0),
            "dominant_hot_worker": hot_tenant_worker_summary.get("dominant_hot_worker", ""),
            "dominant_hot_worker_hot_tenant_count": hot_tenant_worker_summary.get(
                "dominant_hot_worker_hot_tenant_count", 0
            ),
            "dominant_hot_worker_hot_event_share": hot_tenant_worker_summary.get(
                "dominant_hot_worker_hot_event_share", 0.0
            ),
            "dominant_hot_worker_probe_ids": hot_tenant_worker_summary.get(
                "dominant_hot_worker_probe_ids", []
            ),
        },
        "shard_distribution": {
            "row_count": len(shard_rows),
            "status": "error" if shard_error else "ok",
            "error": shard_error or "",
            "shard_size_bytes": shard_size_stats,
        },
        "warnings": warnings,
        "status": "warning" if warnings else "ok",
    }


def _dataset_time_contract(
    profile: dict[str, Any], tenant_rows: list[dict[str, str]]
) -> dict[str, Any]:
    base_time_unix = int(profile.get("base_time_unix", 0) or 0)
    lookback_days = int(profile.get("scale", {}).get("lookback_days", 0) or 0)
    first_values = sorted(
        str(row.get("first_event_at", "")).strip()
        for row in tenant_rows
        if str(row.get("first_event_at", "")).strip()
    )
    last_values = sorted(
        str(row.get("last_event_at", "")).strip()
        for row in tenant_rows
        if str(row.get("last_event_at", "")).strip()
    )
    return {
        "base_time_unix": base_time_unix,
        "base_time_utc": (
            datetime.fromtimestamp(base_time_unix, tz=UTC).isoformat()
            if base_time_unix > 0
            else "not_frozen"
        ),
        "lookback_days": lookback_days,
        "wall_clock_anchored": base_time_unix <= 0,
        "measured_event_time_min": first_values[0] if first_values else "not_observed",
        "measured_event_time_max": last_values[-1] if last_values else "not_observed",
    }


def _dataset_snapshot_contract() -> dict[str, Any]:
    return {
        "contract_version": "profile-and-aggregate-audit-v1",
        "checksum_scope": "profile_and_aggregate_audit_artifacts",
        "row_level_checksum_included": False,
    }


def collect_dataset_audit(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    remote_datagen_dir: str,
    out_dir: Path,
    profile: dict[str, Any],
    region: str,
) -> dict[str, Any]:
    tenant_distribution_sql = """
SELECT
  tenant_id,
  count(*) AS events_count,
  sum(value) AS total_value,
  min(created_at) AS first_event_at,
  max(created_at) AS last_event_at
FROM events
GROUP BY tenant_id
ORDER BY events_count DESC, tenant_id;
"""
    shard_distribution_sql = """
SELECT
  table_name::text AS table_name,
  shardid::bigint AS shard_id,
  nodename::text AS node_name,
  nodeport::int AS node_port,
  coalesce(shard_size, 0)::bigint AS shard_size_bytes
FROM citus_shards
WHERE table_name IN ('events', 'tenants', 'users', 'global_users')
ORDER BY table_name, shard_id, node_name;
"""
    counts_path = out_dir / "dataset_counts.csv"
    tenant_path = out_dir / "tenant_distribution.csv"
    shard_path = out_dir / "shard_distribution.csv"
    hot_path = out_dir / "hot_tenant_manifest.csv"
    tenant_worker_mapping_path = out_dir / "tenant_worker_mapping.csv"
    hot_tenant_worker_mapping_path = out_dir / "hot_tenant_worker_mapping.csv"
    hot_tenant_worker_summary_path = out_dir / "hot_tenant_worker_summary.csv"
    parameter_values_path = out_dir / "dataset_parameter_values.json"

    # Keep these as separate statements. A UNION ALL over multiple Citus
    # distributed/reference tables can create a coordinator-side distributed
    # plan that opens an internal localhost worker connection and may fail on
    # password-authenticated clusters. Per-table counts avoid that planner path
    # and are enough for the dataset capability audit.
    count_tables = ["tenants", "users", "global_users", "events"]
    count_output = ["table_name,row_count"]
    count_stderr: list[str] = []
    for table_name in count_tables:
        counts = remote_psql_csv(
            host=host,
            user=user,
            key_file=key_file,
            remote_datagen_dir=remote_datagen_dir,
            sql=f"SELECT '{table_name}' AS table_name, count(*) AS row_count FROM {table_name};",
        )
        rows = list(csv.DictReader(counts.stdout.splitlines()))
        if not rows:
            raise RuntimeError(f"Dataset count query returned no rows for {table_name}")
        count_output.append(f"{table_name},{rows[0].get('row_count', '')}")
        if counts.stderr:
            count_stderr.append(f"-- {table_name}\n{counts.stderr.strip()}")
    counts_path.write_text("\n".join(count_output) + "\n", encoding="utf-8")
    (out_dir / "dataset_counts.stderr.log").write_text(
        "\n\n".join(count_stderr) + ("\n" if count_stderr else ""),
        encoding="utf-8",
    )

    tenants = remote_psql_csv(
        host=host,
        user=user,
        key_file=key_file,
        remote_datagen_dir=remote_datagen_dir,
        sql=tenant_distribution_sql,
    )
    tenant_path.write_text(tenants.stdout, encoding="utf-8")
    (out_dir / "tenant_distribution.stderr.log").write_text(tenants.stderr, encoding="utf-8")

    shard_error: str | None = None
    try:
        shards = remote_psql_csv(
            host=host,
            user=user,
            key_file=key_file,
            remote_datagen_dir=remote_datagen_dir,
            sql=shard_distribution_sql,
        )
        shard_path.write_text(shards.stdout, encoding="utf-8")
        (out_dir / "shard_distribution.stderr.log").write_text(shards.stderr, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        shard_error = (exc.stderr or str(exc)).strip()
        shard_path.write_text(
            "table_name,shard_id,node_name,node_port,shard_size_bytes\n",
            encoding="utf-8",
        )
        (out_dir / "shard_distribution.error.log").write_text(shard_error + "\n", encoding="utf-8")

    counts_rows = _read_csv_dicts(counts_path)
    tenant_rows = _read_csv_dicts(tenant_path)
    shard_rows = _read_csv_dicts(shard_path)
    hot_tenant_count = expected_hot_tenant_count(
        profile,
        region=region,
        tenant_count=len(tenant_rows),
    )
    hot_tenant_rows = _write_hot_tenant_manifest(
        hot_path,
        tenant_rows,
        hot_tenant_count=hot_tenant_count,
    )
    hot_tenant_ids = {_tenant_id(row) for row in hot_tenant_rows if row.get("tenant_id")}
    cold_probe_rows = [
        row
        for row in sorted(tenant_rows, key=lambda item: _tenant_id(item))
        if row.get("tenant_id") and _tenant_id(row) not in hot_tenant_ids
    ][:100]
    mapping_source_rows = [*hot_tenant_rows, *cold_probe_rows]
    mapping_sql_values = _sql_values_for_tenants(
        selected_rows=mapping_source_rows,
        hot_tenant_ids=hot_tenant_ids,
    )
    tenant_worker_mapping_sql = f"""
WITH selected_tenants(tenant_id, events_count, tenant_role) AS (
  VALUES
  {mapping_sql_values}
),
tenant_shards AS (
  SELECT
    tenant_id::bigint AS tenant_id,
    events_count::bigint AS events_count,
    tenant_role::text AS tenant_role,
    get_shard_id_for_distribution_column('events', tenant_id::bigint) AS shard_id
  FROM selected_tenants
  WHERE tenant_id IS NOT NULL
)
SELECT
  tenant_id,
  tenant_role,
  events_count,
  shard_id,
  coalesce(table_name::text, 'events') AS table_name,
  coalesce(nodename::text, '') AS node_name,
  coalesce(nodeport::text, '') AS node_port
FROM tenant_shards
LEFT JOIN citus_shards
  ON citus_shards.table_name = 'events'
 AND citus_shards.shardid = tenant_shards.shard_id
ORDER BY tenant_role DESC, events_count DESC, tenant_id;
"""
    try:
        mapping_result = remote_psql_csv(
            host=host,
            user=user,
            key_file=key_file,
            remote_datagen_dir=remote_datagen_dir,
            sql=tenant_worker_mapping_sql,
        )
        tenant_worker_mapping_path.write_text(
            mapping_result.stdout,
            encoding="utf-8",
        )
        (out_dir / "tenant_worker_mapping.stderr.log").write_text(
            mapping_result.stderr,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as exc:
        mapping_error = (exc.stderr or str(exc)).strip()
        tenant_worker_mapping_path.write_text(
            "tenant_id,tenant_role,events_count,shard_id,table_name,node_name,node_port\n",
            encoding="utf-8",
        )
        (out_dir / "tenant_worker_mapping.error.log").write_text(
            mapping_error + "\n",
            encoding="utf-8",
        )

    tenant_worker_mapping_rows = _read_csv_dicts(tenant_worker_mapping_path)
    hot_worker_rows = [row for row in tenant_worker_mapping_rows if row.get("tenant_role") == "hot"]
    with hot_tenant_worker_mapping_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "tenant_id",
            "tenant_role",
            "events_count",
            "shard_id",
            "table_name",
            "node_name",
            "node_port",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(hot_worker_rows)
    hot_tenant_worker_summary = _write_hot_tenant_worker_summary(
        hot_tenant_worker_summary_path,
        tenant_worker_mapping_rows,
    )
    parameter_values_summary = _write_dataset_parameter_values(
        parameter_values_path,
        profile=profile,
        tenant_rows=tenant_rows,
        hot_tenant_rows=hot_tenant_rows,
        tenant_worker_mapping_path=tenant_worker_mapping_path,
        hot_tenant_worker_mapping_path=hot_tenant_worker_mapping_path,
        hot_tenant_worker_summary=hot_tenant_worker_summary,
        hot_tenant_path=hot_path,
        tenant_distribution_path=tenant_path,
    )
    payload = _dataset_audit_payload(
        profile=profile,
        counts_rows=counts_rows,
        tenant_rows=tenant_rows,
        shard_rows=shard_rows,
        shard_error=shard_error,
        dataset_parameter_values=parameter_values_summary,
        hot_tenant_rows=hot_tenant_rows,
        hot_tenant_worker_summary=hot_tenant_worker_summary,
    )
    write_json(out_dir / "capability_audit.json", payload)
    return payload


def main() -> int:
    args = parse_args()
    profile_path = args.profile.resolve()
    profile = load_yaml(profile_path)
    env_values = {**load_shell_env(args.env_file), **os.environ}
    key_value = env_values.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    key_file = Path(key_value).expanduser() if key_value else None
    if key_file is not None and not key_file.exists():
        raise FileNotFoundError(f"SSH private key not found: {key_file}")

    coordinator_name, coordinator = load_coordinator(args.inventory, region=args.region)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dataset_id = str(profile.get("dataset_id", profile_path.stem))
    audit_suffix = "-audit-only" if args.audit_only else ""
    load_id = f"{timestamp}-{dataset_id}-{args.region}{audit_suffix}"
    out_dir = (args.out_root / load_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    effective_env = dataset_env(profile, region=args.region, load_method=args.load_method)
    effective_distribution = region_distribution(profile, region=args.region)
    overrides = "\n".join(f"{key}={value}" for key, value in effective_env.items()) + "\n"
    key_regex = "^(" + "|".join(DATAGEN_KEYS) + ")="

    remote_script = f"""
set -euo pipefail
cd {shlex.quote(args.remote_datagen_dir)}
backup="$(mktemp .env.dataset-profile.XXXXXX)"
cp .env "$backup"
chmod 600 "$backup"
datagen_pgid=""
cleanup_remote() {{
  status=$?
  if [ -n "$datagen_pgid" ]; then
    kill -TERM -- "-$datagen_pgid" 2>/dev/null || true
    sleep 2
    kill -KILL -- "-$datagen_pgid" 2>/dev/null || true
  fi
  mv "$backup" .env
  exit "$status"
}}
trap cleanup_remote EXIT HUP INT TERM
grep -Ev {shlex.quote(key_regex)} "$backup" > .env
cat >> .env <<'DATAGEN_OVERRIDES'
{overrides.rstrip()}
DATAGEN_OVERRIDES
chmod 600 .env
set -a
. ./.env
set +a
sudo -u postgres psql -X -d "${{POSTGRES_DB:-app}}" <<'DATASET_PRELOAD_CLEANUP' || true
select pg_terminate_backend(pid)
from pg_stat_activity
where datname = current_database()
  and pid <> pg_backend_pid()
  and (
    state = 'idle in transaction'
    or query ilike 'FETCH % FROM c%'
    or query ilike 'drop table if exists events%'
  );
drop view if exists public.mr_joined_events_colocated;
drop view if exists public.mr_joined_events_repartition;
DATASET_PRELOAD_CLEANUP
setsid ./bin/reset-and-load &
datagen_pgid=$!
wait "$datagen_pgid"
""".strip()
    if args.audit_only:
        print(
            f"Collecting dataset audit for {dataset_id} on {coordinator_name}...",
            flush=True,
        )
    else:
        print(f"Loading dataset {dataset_id} on {coordinator_name}...", flush=True)
        result = ssh_run(coordinator["ansible_host"], args.ssh_user, key_file, remote_script)
        (out_dir / "datagen.stdout.log").write_text(result.stdout, encoding="utf-8")
        (out_dir / "datagen.stderr.log").write_text(result.stderr, encoding="utf-8")
    audit_payload = collect_dataset_audit(
        host=coordinator["ansible_host"],
        user=args.ssh_user,
        key_file=key_file,
        remote_datagen_dir=args.remote_datagen_dir,
        out_dir=out_dir,
        profile=profile,
        region=args.region,
    )
    profile_copy = out_dir / "dataset_profile.yml"
    profile_copy.write_bytes(profile_path.read_bytes())
    datagen_commit_result = ssh_run(
        coordinator["ansible_host"],
        args.ssh_user,
        key_file,
        (
            f"cd {shlex.quote(args.remote_datagen_dir)} && "
            "git rev-parse HEAD 2>/dev/null || printf 'not_recorded\\n'"
        ),
    )
    table_counts = {
        row.get("table_name", ""): int(row.get("row_count", 0) or 0)
        for row in _read_csv_dicts(out_dir / "dataset_counts.csv")
        if row.get("table_name")
    }
    dataset_time_contract = audit_payload["dataset_time_contract"]
    snapshot_inputs = [
        profile_copy,
        out_dir / "dataset_counts.csv",
        out_dir / "shard_distribution.csv",
        out_dir / "hot_tenant_manifest.csv",
        out_dir / "hot_tenant_worker_mapping.csv",
        out_dir / "hot_tenant_worker_summary.csv",
    ]
    snapshot_component_hashes = {
        path.name: sha256_file(path) for path in snapshot_inputs if path.exists()
    }
    dataset_snapshot_id = hashlib.sha256(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "region": args.region,
                "seed": profile.get("seed", ""),
                "dataset_time_contract": dataset_time_contract,
                "datagen_commit": datagen_commit_result.stdout.strip(),
                "component_hashes": snapshot_component_hashes,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    write_json(
        out_dir / "dataset_load_manifest.json",
        {
            "load_id": load_id,
            "created_at_utc": timestamp,
            "dataset_id": dataset_id,
            "profile": str(profile_path),
            "profile_copy": str(profile_copy),
            "profile_sha256": sha256_file(profile_copy),
            "dataset_seed": profile.get("seed", ""),
            "dataset_time_contract": dataset_time_contract,
            "datagen_commit": datagen_commit_result.stdout.strip(),
            "table_counts": table_counts,
            "dataset_snapshot_id": dataset_snapshot_id,
            "dataset_snapshot_contract": _dataset_snapshot_contract(),
            "snapshot_component_hashes": snapshot_component_hashes,
            "region": args.region,
            "coordinator": coordinator_name,
            "audit_only": args.audit_only,
            "datagen_env": effective_env,
            "effective_distribution": effective_distribution,
            "dataset_capability_audit": {
                "status": audit_payload["status"],
                "path": str(out_dir / "capability_audit.json"),
                "warnings": audit_payload["warnings"],
            },
            "dataset_parameter_values": str(out_dir / "dataset_parameter_values.json"),
        },
    )
    print(str(out_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
