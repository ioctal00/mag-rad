#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
MASTER_REGIMES_ROOT = WORKSPACE_ROOT / "master-regimes"
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"

DEFAULT_SMOKE_CONDITIONS = (
    "top_tenants__regional_reduced",
    "top_tenants__raw_gac_finalize",
)


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def log_event(component: str, message: str) -> None:
    clock = datetime.now(UTC).strftime("%H:%M:%SZ")
    print(f"[{clock}] [{component}] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the bounded Plan-10 B/C worker-placement capability smoke. "
            "This is not the 48-slot confirmatory experiment."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=MASTER_REGIMES_ROOT
        / "configs"
        / "validation"
        / "confirmatory_skew_v1.yml",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=MASTER_REGIMES_ROOT
        / "generated"
        / "corpus"
        / "confirmatory-skew-v1"
        / "corpus_execution_plan.yml",
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT
        / "generated"
        / "runs"
        / "confirmatory-skew-capability-smoke",
    )
    parser.add_argument("--label", default="confirmatory-skew-v1-capability")
    parser.add_argument("--load-method", choices=("sql", "csv", "copy_pipe"), default="copy_pipe")
    parser.add_argument("--hard-timeout-seconds", type=int, default=300)
    parser.add_argument("--timeout-grace-seconds", type=int, default=30)
    parser.add_argument(
        "--result-snapshot-only",
        action="store_true",
        help=(
            "Run bounded typed result snapshots while retaining the B/C "
            "placement intervention and audit."
        ),
    )
    parser.add_argument("--result-snapshot-max-rows", type=int, default=100)
    parser.add_argument(
        "--result-snapshot-max-bytes",
        type=int,
        default=10 * 1024 * 1024,
    )
    parser.add_argument("--ssh-user", default="root")
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def workspace_path(raw_path: str) -> Path:
    path = Path(raw_path)
    return path.resolve() if path.is_absolute() else (WORKSPACE_ROOT / path).resolve()


def kv_args(flag: str, values: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for key, value in sorted(values.items()):
        args.extend([flag, f"{key}={value}"])
    return args


def runtime_contract(plan: dict[str, Any]) -> dict[str, Any]:
    contracts: list[dict[str, Any]] = []
    for state_id in ("B", "C"):
        group = next(
            item for item in plan["groups"] if str(item["state_id"]) == state_id
        )
        sweep = load_yaml(workspace_path(str(group["sweep_config"])))
        runtime_configs = sweep.get("runtime_configs") or []
        if len(runtime_configs) != 1 or not isinstance(runtime_configs[0], dict):
            raise RuntimeError(
                f"Expected one runtime config for placement state {state_id}"
            )
        contracts.append(runtime_configs[0])
    if canonical_sha256(contracts[0]) != canonical_sha256(contracts[1]):
        raise RuntimeError("B/C placement states must use the same fixed runtime config")
    return contracts[0]


def write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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
        assignment = parts[1] if parts[0] == "export" and len(parts) > 1 else parts[0]
        if "=" in assignment:
            key, value = assignment.split("=", 1)
            values[key] = value
    return values


def ssh_base(
    *,
    host: str,
    user: str,
    key_file: Path | None,
) -> list[str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
    ]
    if key_file is not None:
        command.extend(["-i", str(key_file), "-o", "IdentitiesOnly=yes"])
    command.append(f"{user}@{host}")
    return command


def coordinator_inventory(
    inventory: dict[str, Any],
    *,
    region: str,
) -> tuple[str, dict[str, Any]]:
    hosts = inventory["all"]["children"]["coordinators"]["hosts"]
    matches = [
        (name, value)
        for name, value in hosts.items()
        if str(value.get("logical_region", "")) == region
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one coordinator for {region}, got {len(matches)}"
        )
    return matches[0]


def remote_psql_csv(
    *,
    coordinator: dict[str, Any],
    user: str,
    key_file: Path | None,
    sql: str,
    transport_attempts: int = 3,
    retry_delay_seconds: float = 2.0,
) -> list[dict[str, str]]:
    host = str(coordinator["ansible_host"])
    command = [
        *ssh_base(host=host, user=user, key_file=key_file),
        (
            "sudo -u postgres psql -v ON_ERROR_STOP=1 "
            "-d app --csv -c "
            + shlex.quote(sql)
        ),
    ]
    completed: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, max(1, transport_attempts) + 1):
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 255 or attempt >= transport_attempts:
            break
        log_event(
            "SSH",
            (
                "transient transport failure; retrying read-only SQL audit "
                f"{attempt + 1}/{transport_attempts} for {host}"
            ),
        )
        time.sleep(retry_delay_seconds)
    if completed is None:
        raise AssertionError("unreachable")
    if completed.returncode != 0:
        raise RuntimeError(
            f"Remote SQL failed on {host}: {completed.stderr.strip()}"
        )
    return list(csv.DictReader(completed.stdout.splitlines()))


def run_streaming_path(
    command: list[str],
    *,
    component: str,
    cwd: Path = REPO_ROOT,
) -> Path:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        stripped = line.strip()
        if stripped:
            if stripped.startswith("["):
                print(stripped, flush=True)
            else:
                log_event(component, stripped)
    returncode = process.wait()
    output = "".join(lines)
    if returncode != 0:
        raise subprocess.CalledProcessError(
            returncode,
            command,
            output=output,
        )
    for line in reversed(output.splitlines()):
        candidate = line.strip()
        if candidate.startswith("/"):
            return Path(candidate).resolve()
    raise RuntimeError(f"Could not parse artifact path from {' '.join(command)}")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def node_rows(
    *,
    coordinator: dict[str, Any],
    user: str,
    key_file: Path | None,
) -> list[dict[str, str]]:
    return remote_psql_csv(
        coordinator=coordinator,
        user=user,
        key_file=key_file,
        sql="""
SELECT
  nodeid::int AS node_id,
  nodename::text AS node_name,
  nodeport::int AS node_port
FROM pg_dist_node
WHERE isactive AND groupid <> 0 AND noderole = 'primary'
ORDER BY nodename, nodeport;
""",
    )


def table_counts(
    *,
    coordinator: dict[str, Any],
    user: str,
    key_file: Path | None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ("tenants", "events", "users", "global_users"):
        rows = remote_psql_csv(
            coordinator=coordinator,
            user=user,
            key_file=key_file,
            sql=f"SELECT count(*)::bigint AS row_count FROM {table};",
        )
        counts[table] = int(rows[0]["row_count"])
    return counts


def tenant_worker_rows(
    *,
    coordinator: dict[str, Any],
    user: str,
    key_file: Path | None,
) -> list[dict[str, str]]:
    return remote_psql_csv(
        coordinator=coordinator,
        user=user,
        key_file=key_file,
        sql="""
WITH tenant_counts AS (
  SELECT tenant_id::bigint AS tenant_id, count(*)::bigint AS events_count
  FROM events
  GROUP BY tenant_id
),
tenant_shards AS (
  SELECT
    tenant_id,
    events_count,
    get_shard_id_for_distribution_column('events', tenant_id) AS shard_id
  FROM tenant_counts
)
SELECT
  tenant_id,
  events_count,
  shard_id::bigint AS shard_id,
  s.nodename::text AS node_name,
  s.nodeport::int AS node_port
FROM tenant_shards
JOIN citus_shards s
  ON s.table_name = 'events'::regclass
 AND s.shardid = tenant_shards.shard_id
ORDER BY tenant_id;
""",
    )


def event_placement_rows(
    *,
    coordinator: dict[str, Any],
    user: str,
    key_file: Path | None,
) -> list[dict[str, str]]:
    return remote_psql_csv(
        coordinator=coordinator,
        user=user,
        key_file=key_file,
        sql="""
SELECT
  shardid::bigint AS shard_id,
  nodename::text AS node_name,
  nodeport::int AS node_port,
  coalesce(shard_size, 0)::bigint AS shard_size_bytes
FROM citus_shards
WHERE table_name = 'events'::regclass
ORDER BY shardid, nodename, nodeport;
""",
    )


def audit_region(
    *,
    region: str,
    coordinator: dict[str, Any],
    hot_tenant_ids: set[int],
    user: str,
    key_file: Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    counts = table_counts(
        coordinator=coordinator,
        user=user,
        key_file=key_file,
    )
    tenants = tenant_worker_rows(
        coordinator=coordinator,
        user=user,
        key_file=key_file,
    )
    placements = event_placement_rows(
        coordinator=coordinator,
        user=user,
        key_file=key_file,
    )

    worker_events: dict[str, int] = defaultdict(int)
    worker_hot_events: dict[str, int] = defaultdict(int)
    hot_counts: dict[int, int] = {}
    tenant_distribution: list[tuple[int, int]] = []
    enriched: list[dict[str, Any]] = []
    for row in tenants:
        tenant_id = int(row["tenant_id"])
        events_count = int(row["events_count"])
        node_name = row["node_name"]
        is_hot = tenant_id in hot_tenant_ids
        worker_events[node_name] += events_count
        if is_hot:
            worker_hot_events[node_name] += events_count
            hot_counts[tenant_id] = events_count
        tenant_distribution.append((tenant_id, events_count))
        enriched.append(
            {
                "region": region,
                "tenant_id": tenant_id,
                "events_count": events_count,
                "tenant_role": "hot" if is_hot else "cold",
                "shard_id": int(row["shard_id"]),
                "node_name": node_name,
                "node_port": int(row["node_port"]),
            }
        )

    total_hot_events = sum(hot_counts.values())
    dominant_worker = ""
    dominant_hot_events = 0
    if worker_hot_events:
        dominant_worker, dominant_hot_events = sorted(
            worker_hot_events.items(),
            key=lambda item: (-item[1], item[0]),
        )[0]
    dominant_share = (
        dominant_hot_events / total_hot_events
        if total_hot_events
        else 0.0
    )
    placement_contract = [
        (
            int(row["shard_id"]),
            row["node_name"],
            int(row["node_port"]),
        )
        for row in placements
    ]
    summary = {
        "region": region,
        "coordinator": str(coordinator.get("ansible_host", "")),
        "table_counts": counts,
        "hot_tenant_ids": sorted(hot_tenant_ids),
        "hot_tenant_event_counts": {
            str(key): hot_counts[key] for key in sorted(hot_counts)
        },
        "hot_event_count": total_hot_events,
        "hot_event_share": (
            total_hot_events / counts["events"] if counts["events"] else 0.0
        ),
        "worker_event_rows": dict(sorted(worker_events.items())),
        "worker_hot_event_rows": dict(sorted(worker_hot_events.items())),
        "dominant_hot_worker": dominant_worker,
        "dominant_hot_worker_hot_event_share": dominant_share,
        "tenant_distribution_sha256": canonical_sha256(
            sorted(tenant_distribution)
        ),
        "event_placement_sha256": canonical_sha256(placement_contract),
        "event_shard_count": len(placements),
    }
    return summary, enriched, placements


def hot_shard_mass(
    tenant_rows: list[dict[str, Any]],
) -> dict[int, int]:
    mass: dict[int, int] = defaultdict(int)
    for row in tenant_rows:
        if row["tenant_role"] == "hot":
            mass[int(row["shard_id"])] += int(row["events_count"])
    return dict(mass)


def validate_hot_share_threshold(
    *,
    state_id: str,
    region: str,
    hot_tenant_ids: set[int],
    observed_share: float,
    threshold: float,
) -> None:
    if not hot_tenant_ids:
        return
    if state_id == "B" and observed_share > threshold:
        raise RuntimeError(
            f"B dispersed threshold failed in {region}: "
            f"{observed_share:.4f} > {threshold}"
        )
    if state_id == "C" and observed_share < threshold:
        raise RuntimeError(
            f"C concentration threshold failed in {region}: "
            f"{observed_share:.4f} < {threshold}"
        )


def greedy_hot_shard_assignment(
    *,
    shard_mass: dict[int, int],
    workers: list[str],
) -> dict[int, str]:
    if len(workers) < 2:
        raise ValueError("At least two workers are required")
    totals = {worker: 0 for worker in sorted(workers)}
    assignment: dict[int, str] = {}
    for shard_id, mass in sorted(
        shard_mass.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        target = min(totals, key=lambda worker: (totals[worker], worker))
        assignment[shard_id] = target
        totals[target] += mass
    return assignment


def current_placement(
    placements: list[dict[str, str]],
) -> dict[int, tuple[str, int]]:
    result: dict[int, tuple[str, int]] = {}
    for row in placements:
        shard_id = int(row["shard_id"])
        value = (row["node_name"], int(row["node_port"]))
        if shard_id in result and result[shard_id] != value:
            raise RuntimeError(
                f"Shard {shard_id} has multiple active placements"
            )
        result[shard_id] = value
    return result


def move_shard(
    *,
    region: str,
    phase: str,
    shard_id: int,
    source: tuple[str, int],
    target: tuple[str, int],
    coordinator: dict[str, Any],
    nodes_by_name: dict[str, dict[str, str]],
    user: str,
    key_file: Path | None,
) -> dict[str, Any]:
    source_node = nodes_by_name[source[0]]
    target_node = nodes_by_name[target[0]]
    log_event(
        "PLACEMENT",
        (
            f"{region} {phase} shard={shard_id} "
            f"{source[0]}:{source[1]} -> {target[0]}:{target[1]}"
        ),
    )
    remote_psql_csv(
        coordinator=coordinator,
        user=user,
        key_file=key_file,
        sql=(
            "SELECT citus_move_shard_placement("
            f"{shard_id}::bigint,"
            f"{int(source_node['node_id'])}::int,"
            f"{int(target_node['node_id'])}::int,"
            "'block_writes'"
            ");"
        ),
    )
    return {
        "region": region,
        "phase": phase,
        "shard_id": shard_id,
        "source_node_id": int(source_node["node_id"]),
        "source_node_name": source[0],
        "source_node_port": source[1],
        "target_node_id": int(target_node["node_id"]),
        "target_node_name": target[0],
        "target_node_port": target[1],
        "transfer_mode": "block_writes",
        "status": "completed",
    }


def apply_assignment(
    *,
    region: str,
    phase: str,
    assignment: dict[int, str],
    placements: list[dict[str, str]],
    coordinator: dict[str, Any],
    nodes: list[dict[str, str]],
    user: str,
    key_file: Path | None,
) -> list[dict[str, Any]]:
    nodes_by_name = {row["node_name"]: row for row in nodes}
    placement = current_placement(placements)
    moves: list[dict[str, Any]] = []
    for shard_id, target_name in sorted(assignment.items()):
        source = placement[shard_id]
        target_row = nodes_by_name[target_name]
        target = (target_name, int(target_row["node_port"]))
        if source == target:
            continue
        moves.append(
            move_shard(
                region=region,
                phase=phase,
                shard_id=shard_id,
                source=source,
                target=target,
                coordinator=coordinator,
                nodes_by_name=nodes_by_name,
                user=user,
                key_file=key_file,
            )
        )
        placement[shard_id] = target
    return moves


def inverse_moves(
    *,
    moves: list[dict[str, Any]],
    coordinators: dict[str, dict[str, Any]],
    nodes_by_region: dict[str, list[dict[str, str]]],
    user: str,
    key_file: Path | None,
) -> list[dict[str, Any]]:
    restored: list[dict[str, Any]] = []
    for move in reversed(moves):
        region = str(move["region"])
        restored.append(
            move_shard(
                region=region,
                phase="restore_b",
                shard_id=int(move["shard_id"]),
                source=(
                    str(move["target_node_name"]),
                    int(move["target_node_port"]),
                ),
                target=(
                    str(move["source_node_name"]),
                    int(move["source_node_port"]),
                ),
                coordinator=coordinators[region],
                nodes_by_name={
                    row["node_name"]: row
                    for row in nodes_by_region[region]
                },
                user=user,
                key_file=key_file,
            )
        )
    return restored


def build_smoke_manifest(
    *,
    plan: dict[str, Any],
    state_id: str,
    out_path: Path,
    conditions: tuple[str, ...],
    repetition_indices: tuple[int, ...],
    recovery_members: dict[tuple[str, str], dict[str, str]] | None = None,
) -> Path:
    group = next(
        item for item in plan["groups"] if str(item["state_id"]) == state_id
    )
    manifest_path = WORKSPACE_ROOT / str(group["instance_manifest"])
    rows = read_csv(manifest_path)
    selected: list[dict[str, str]] = []
    for repetition_index in repetition_indices:
        for condition in conditions:
            matches = [
                row
                for row in rows
                if row.get("query_condition_id") == condition
                and int(row.get("repetition_index", "0") or 0)
                == repetition_index
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"Expected one {state_id}/{condition}/r{repetition_index} "
                    f"smoke row, got {len(matches)}"
                )
            selected.append(dict(matches[0]))
    for index, row in enumerate(selected, start=1):
        row["run_order"] = str(index)
        if recovery_members is not None:
            key = (state_id, str(row.get("query_condition_id", "")))
            if key not in recovery_members:
                raise RuntimeError(f"Missing correctness recovery identity for {key}")
            recovery = recovery_members[key]
            row["condition_id"] = recovery["condition_id"]
            row["execution_slot_id"] = recovery["recovery_id"]
            row["repeat_id"] = recovery["recovery_id"]
            row["pair_id"] = recovery["pair_id"]
            row["intervention_role"] = recovery["member"]
            row["repetition_index"] = "0"
    fieldnames = list(rows[0])
    write_csv(out_path, selected, fieldnames=fieldnames)
    return out_path


def run_query_smoke(
    *,
    state_id: str,
    manifest_path: Path,
    out_root: Path,
    hard_timeout_seconds: int,
    timeout_grace_seconds: int,
    pg_options: dict[str, Any],
    psql_variables: dict[str, Any],
    result_signature_required: bool,
    result_signature_scope: str,
    result_snapshot_only: bool,
    result_snapshot_max_rows: int,
    result_snapshot_max_bytes: int,
) -> tuple[Path, Path | None]:
    instance_count = len(read_csv(manifest_path))
    checkpoint_file = os.environ.get("PRESSURE_RAW_CHECKPOINT_FILE", "")
    sweep_dir = run_streaming_path(
        [
            sys.executable,
            str(REPO_ROOT / "common-scripts" / "run_query_collection_sweep.py"),
            "--instance-manifest",
            str(manifest_path),
            "--label",
            f"confirmatory-skew-v1-capability-{state_id.lower()}",
            "--max-instances",
            str(instance_count),
            "--global-stats-scope",
            "none",
            "--target-group",
            "analytics_clients",
            "--hard-timeout-seconds",
            str(hard_timeout_seconds),
            "--timeout-grace-seconds",
            str(timeout_grace_seconds),
            "--cache-policy",
            "mixed_cache_capability_smoke",
            "--order-policy",
            "manifest_order",
            *(
                [
                    "--result-snapshot-only",
                    "--result-snapshot-max-rows",
                    str(result_snapshot_max_rows),
                    "--result-snapshot-max-bytes",
                    str(result_snapshot_max_bytes),
                ]
                if result_snapshot_only
                else [
                    "--fdw-auto-explain",
                    "--os-sampler",
                    "--os-sampler-node-group",
                    "db_nodes",
                ]
            ),
            *(
                ["--result-signature"]
                if result_signature_required and not result_snapshot_only
                else []
            ),
            *(
                ["--result-signature-scope", result_signature_scope]
                if result_signature_required and not result_snapshot_only
                else []
            ),
            *(
                ["--checkpoint-file", checkpoint_file]
                if checkpoint_file
                else []
            ),
            *kv_args("--pg-option", pg_options),
            *kv_args("--var", psql_variables),
            "--out-root",
            str(out_root),
        ],
        component=f"QUERY-{state_id}",
    )
    if result_snapshot_only:
        return sweep_dir, None
    index_dir = run_streaming_path(
        [
            "uv",
            "run",
            "--project",
            str(MASTER_REGIMES_ROOT),
            "master-regimes",
            "index-query-sweep",
            "--sweep-dir",
            str(sweep_dir),
        ],
        component=f"INDEX-{state_id}",
    )
    return sweep_dir, index_dir


def invariants_equal(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for region in sorted(before):
        for field in (
            "table_counts",
            "hot_tenant_ids",
            "hot_tenant_event_counts",
            "hot_event_share",
            "tenant_distribution_sha256",
        ):
            if before[region][field] != after[region][field]:
                errors.append(f"{region}.{field}")
    return not errors, errors


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    plan_path = args.plan.resolve()
    inventory_path = args.inventory.resolve()
    config = load_yaml(config_path)
    plan = load_yaml(plan_path)
    fixed_runtime = runtime_contract(plan)
    runtime_id = str(fixed_runtime.get("id", "default"))
    pg_options = dict(fixed_runtime.get("pg_options") or {})
    psql_variables = dict(fixed_runtime.get("psql_variables") or {})
    fdw_server_options = dict(fixed_runtime.get("fdw_server_options") or {})
    network_profile = dict(fixed_runtime.get("network_profile") or {})
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    capability_config = config.get("capability_smoke") or {}
    conditions = tuple(
        str(value)
        for value in capability_config.get(
            "condition_ids",
            DEFAULT_SMOKE_CONDITIONS,
        )
    )
    repetition_indices = tuple(
        int(value)
        for value in capability_config.get("repetition_indices", [1])
    )
    recovery_config = config.get("correctness_recovery") or {}
    recovery_members: dict[tuple[str, str], dict[str, str]] | None = None
    if args.result_snapshot_only:
        if not bool(recovery_config.get("enabled", False)):
            raise RuntimeError(
                "--result-snapshot-only requires correctness_recovery.enabled=true"
            )
        recovery_members = {}
        for member in recovery_config.get("members") or []:
            key = (str(member["state_id"]), str(member["query_condition_id"]))
            if key in recovery_members:
                raise RuntimeError(
                    f"Duplicate correctness recovery identity for {key}"
                )
            recovery_members[key] = {
                field: str(member[field])
                for field in ("condition_id", "recovery_id", "pair_id", "member")
            }
        expected_keys = {
            (state_id, condition)
            for state_id in ("B", "C")
            for condition in conditions
        }
        if set(recovery_members) != expected_keys:
            raise RuntimeError(
                "Correctness recovery members do not match selected B/C conditions"
            )
    if bool(capability_config.get("require_checkpoint", True)):
        checkpoint = load_yaml(
            MASTER_REGIMES_ROOT / str(config["checkpoint"])
        )
        if (
            checkpoint.get("decision") != "GO"
            or int(checkpoint.get("next_plan", 0)) != 10
        ):
            raise RuntimeError("Plan 09 checkpoint does not authorize Plan 10")
    if not bool(plan.get("dry_run_only_until_capability_gate")):
        raise RuntimeError("Expected preregistered plan to remain dry-run-only")

    env = {**load_shell_env(args.env_file), **os.environ}
    key_text = env.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    key_file = Path(key_text).expanduser() if key_text else None
    if key_file is not None and not key_file.exists():
        raise FileNotFoundError(f"SSH key not found: {key_file}")

    run_id = f"{utc_timestamp()}-{args.label}"
    run_dir = (args.out_root / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    status_path = run_dir / "capability_smoke_status.json"
    raw_manifest_path = run_dir / "capability_smoke_manifest.json"
    started = time.monotonic()
    write_json(
        status_path,
        {
            "run_id": run_id,
            "status": "running",
            "created_at_utc": utc_timestamp(),
        },
    )

    coordinators: dict[str, dict[str, Any]] = {}
    coordinator_names: dict[str, str] = {}
    nodes_by_region: dict[str, list[dict[str, str]]] = {}
    hot_ids = {
        "eu": {
            int(value)
            for value in config["hot_tenant_contract"]["eu_hot_tenant_ids"]
        },
        "us": {
            int(value)
            for value in config["hot_tenant_contract"]["us_hot_tenant_ids"]
        },
    }
    for region in ("eu", "us"):
        name, coordinator = coordinator_inventory(inventory, region=region)
        coordinators[region] = coordinator
        coordinator_names[region] = name

    profile_path = (
        MASTER_REGIMES_ROOT
        / str(config["hot_tenant_contract"]["source_profile"])
    ).resolve()
    load_dirs: dict[str, str] = {}
    fdw_dirs: dict[str, str] = {}
    b_setup_moves: list[dict[str, Any]] = []
    c_moves: list[dict[str, Any]] = []
    restore_moves: list[dict[str, Any]] = []
    query_sweeps: dict[str, dict[str, str]] = {}
    audit_payloads: dict[str, dict[str, dict[str, Any]]] = {}
    audit_rows: dict[str, list[dict[str, Any]]] = {}
    placement_rows: dict[str, list[dict[str, str]]] = {}
    error: BaseException | None = None
    restore_status = "not_required"
    network_apply_dir: Path | None = None
    network_reset_dir: Path | None = None

    try:
        bounded_query_count = (
            2 * len(conditions) * len(repetition_indices)
        )
        log_event(
            "SMOKE",
            f"run_id={run_id} bounded_query_count={bounded_query_count}",
        )
        for region in ("eu", "us"):
            log_event("DATASET", f"clean load region={region}")
            load_dir = run_streaming_path(
                [
                    sys.executable,
                    str(REPO_ROOT / "common-scripts" / "apply_dataset_profile.py"),
                    "--profile",
                    str(profile_path),
                    "--region",
                    region,
                    "--load-method",
                    args.load_method,
                ],
                component=f"DATASET-{region.upper()}",
            )
            load_dirs[region] = str(load_dir)

        for region in ("eu", "us"):
            log_event("FDW", f"bootstrap region={region}")
            fdw_dir = run_streaming_path(
                [
                    sys.executable,
                    str(REPO_ROOT / "common-scripts" / "run_gac_fdw_bootstrap.py"),
                    "--label",
                    f"{run_id}-fdw-{region}",
                    "--region",
                    region,
                    *kv_args("--fdw-server-option", fdw_server_options),
                ],
                component=f"FDW-{region.upper()}",
            )
            fdw_dirs[region] = str(fdw_dir)

        if network_profile:
            if network_profile.get("scope") != "region_egress_to_analytics":
                raise RuntimeError(
                    "Placement runner only supports region_egress_to_analytics "
                    "network profiles"
                )
            log_event(
                "NET",
                f"apply fixed runtime={runtime_id} profile={network_profile.get('id', '')}",
            )
            network_apply_dir = run_streaming_path(
                [
                    sys.executable,
                    str(REPO_ROOT / "common-scripts" / "manage_network_pressure.py"),
                    "--action",
                    "apply",
                    "--profile-json",
                    json.dumps(network_profile, sort_keys=True),
                    "--label",
                    f"{run_id}-{runtime_id}-apply",
                    "--out-dir",
                    str(run_dir / "network-interventions"),
                ],
                component="NET",
            )

        for region in ("eu", "us"):
            nodes_by_region[region] = node_rows(
                coordinator=coordinators[region],
                user=args.ssh_user,
                key_file=key_file,
            )
            initial, rows, placements = audit_region(
                region=region,
                coordinator=coordinators[region],
                hot_tenant_ids=hot_ids[region],
                user=args.ssh_user,
                key_file=key_file,
            )
            audit_payloads.setdefault("initial", {})[region] = initial
            audit_rows[f"initial_{region}"] = rows
            placement_rows[f"initial_{region}"] = placements

            masses = hot_shard_mass(rows)
            workers = [row["node_name"] for row in nodes_by_region[region]]
            assignment = greedy_hot_shard_assignment(
                shard_mass=masses,
                workers=workers,
            )
            b_setup_moves.extend(
                apply_assignment(
                    region=region,
                    phase="establish_b",
                    assignment=assignment,
                    placements=placements,
                    coordinator=coordinators[region],
                    nodes=nodes_by_region[region],
                    user=args.ssh_user,
                    key_file=key_file,
                )
            )

        for region in ("eu", "us"):
            summary, rows, placements = audit_region(
                region=region,
                coordinator=coordinators[region],
                hot_tenant_ids=hot_ids[region],
                user=args.ssh_user,
                key_file=key_file,
            )
            audit_payloads.setdefault("B", {})[region] = summary
            audit_rows[f"B_{region}"] = rows
            placement_rows[f"B_{region}"] = placements
            max_share = float(
                config["placement"]["dispersed"][
                    "dominant_hot_event_share_max"
                ]
            )
            validate_hot_share_threshold(
                state_id="B",
                region=region,
                hot_tenant_ids=hot_ids[region],
                observed_share=float(
                    summary["dominant_hot_worker_hot_event_share"]
                ),
                threshold=max_share,
            )

        smoke_manifest_dir = run_dir / "smoke-manifests"
        b_manifest = build_smoke_manifest(
            plan=plan,
            state_id="B",
            out_path=smoke_manifest_dir / "B.csv",
            conditions=conditions,
            repetition_indices=repetition_indices,
            recovery_members=recovery_members,
        )
        b_sweep, b_index = run_query_smoke(
            state_id="B",
            manifest_path=b_manifest,
            out_root=run_dir / "query-sweeps",
            hard_timeout_seconds=args.hard_timeout_seconds,
            timeout_grace_seconds=args.timeout_grace_seconds,
            pg_options=pg_options,
            psql_variables=psql_variables,
            result_signature_required=bool(
                config.get("artifact_contract", {}).get(
                    "result_signature_required",
                    False,
                )
            ),
            result_signature_scope=str(
                config.get("artifact_contract", {}).get(
                    "result_signature_scope",
                    "every_execution",
                )
            ),
            result_snapshot_only=args.result_snapshot_only,
            result_snapshot_max_rows=args.result_snapshot_max_rows,
            result_snapshot_max_bytes=args.result_snapshot_max_bytes,
        )
        query_sweeps["B"] = {
            "sweep_dir": str(b_sweep),
            "index_dir": "" if b_index is None else str(b_index),
        }

        for region in ("eu", "us"):
            b_placements = placement_rows[f"B_{region}"]
            masses = hot_shard_mass(audit_rows[f"B_{region}"])
            designated = sorted(
                row["node_name"] for row in nodes_by_region[region]
            )[0]
            assignment = {
                shard_id: designated for shard_id in sorted(masses)
            }
            c_moves.extend(
                apply_assignment(
                    region=region,
                    phase="concentrate_c",
                    assignment=assignment,
                    placements=b_placements,
                    coordinator=coordinators[region],
                    nodes=nodes_by_region[region],
                    user=args.ssh_user,
                    key_file=key_file,
                )
            )

        for region in ("eu", "us"):
            summary, rows, placements = audit_region(
                region=region,
                coordinator=coordinators[region],
                hot_tenant_ids=hot_ids[region],
                user=args.ssh_user,
                key_file=key_file,
            )
            audit_payloads.setdefault("C", {})[region] = summary
            audit_rows[f"C_{region}"] = rows
            placement_rows[f"C_{region}"] = placements
            min_share = float(
                config["placement"]["concentrated"][
                    "dominant_hot_event_share_min"
                ]
            )
            validate_hot_share_threshold(
                state_id="C",
                region=region,
                hot_tenant_ids=hot_ids[region],
                observed_share=float(
                    summary["dominant_hot_worker_hot_event_share"]
                ),
                threshold=min_share,
            )

        equal, differences = invariants_equal(
            audit_payloads["B"],
            audit_payloads["C"],
        )
        if not equal:
            raise RuntimeError(
                "B/C dataset invariants differ: " + ", ".join(differences)
            )

        c_manifest = build_smoke_manifest(
            plan=plan,
            state_id="C",
            out_path=smoke_manifest_dir / "C.csv",
            conditions=conditions,
            repetition_indices=repetition_indices,
            recovery_members=recovery_members,
        )
        c_sweep, c_index = run_query_smoke(
            state_id="C",
            manifest_path=c_manifest,
            out_root=run_dir / "query-sweeps",
            hard_timeout_seconds=args.hard_timeout_seconds,
            timeout_grace_seconds=args.timeout_grace_seconds,
            pg_options=pg_options,
            psql_variables=psql_variables,
            result_signature_required=bool(
                config.get("artifact_contract", {}).get(
                    "result_signature_required",
                    False,
                )
            ),
            result_signature_scope=str(
                config.get("artifact_contract", {}).get(
                    "result_signature_scope",
                    "every_execution",
                )
            ),
            result_snapshot_only=args.result_snapshot_only,
            result_snapshot_max_rows=args.result_snapshot_max_rows,
            result_snapshot_max_bytes=args.result_snapshot_max_bytes,
        )
        query_sweeps["C"] = {
            "sweep_dir": str(c_sweep),
            "index_dir": "" if c_index is None else str(c_index),
        }
    except BaseException as exc:
        error = exc
        log_event("SMOKE", f"{type(exc).__name__}: {exc}")
    finally:
        if network_profile:
            try:
                log_event(
                    "NET",
                    f"reset fixed runtime={runtime_id} profile={network_profile.get('id', '')}",
                )
                network_reset_dir = run_streaming_path(
                    [
                        sys.executable,
                        str(REPO_ROOT / "common-scripts" / "manage_network_pressure.py"),
                        "--action",
                        "reset",
                        "--profile-json",
                        json.dumps(network_profile, sort_keys=True),
                        "--label",
                        f"{run_id}-{runtime_id}-reset",
                        "--out-dir",
                        str(run_dir / "network-interventions"),
                    ],
                    component="NET",
                )
            except BaseException as network_reset_exc:
                log_event(
                    "NET",
                    f"reset failed: {type(network_reset_exc).__name__}: {network_reset_exc}",
                )
                if error is None:
                    error = network_reset_exc
        if c_moves:
            try:
                log_event("RESTORE", f"inverse moves={len(c_moves)}")
                restore_moves = inverse_moves(
                    moves=c_moves,
                    coordinators=coordinators,
                    nodes_by_region=nodes_by_region,
                    user=args.ssh_user,
                    key_file=key_file,
                )
                restore_status = "inverse_moves_completed"
                for region in ("eu", "us"):
                    summary, rows, placements = audit_region(
                        region=region,
                        coordinator=coordinators[region],
                        hot_tenant_ids=hot_ids[region],
                        user=args.ssh_user,
                        key_file=key_file,
                    )
                    audit_payloads.setdefault("restored_B", {})[
                        region
                    ] = summary
                    audit_rows[f"restored_B_{region}"] = rows
                    placement_rows[f"restored_B_{region}"] = placements
                restored = all(
                    audit_payloads["B"][region]["event_placement_sha256"]
                    == audit_payloads["restored_B"][region][
                        "event_placement_sha256"
                    ]
                    for region in ("eu", "us")
                )
                if not restored:
                    restore_status = "inverse_moves_mismatch"
                    if error is None:
                        error = RuntimeError(
                            "Inverse placement restore did not reproduce B"
                        )
            except BaseException as restore_exc:
                restore_status = "inverse_moves_failed"
                log_event(
                    "RESTORE",
                    f"{type(restore_exc).__name__}: {restore_exc}",
                )
                if error is None:
                    error = restore_exc

        placement_fields = [
            "state_id",
            "region",
            "shard_id",
            "node_name",
            "node_port",
            "shard_size_bytes",
        ]
        for state_id, suffix in (
            ("B", "before"),
            ("C", "after"),
            ("restored_B", "restored"),
        ):
            rows: list[dict[str, Any]] = []
            for region in ("eu", "us"):
                for row in placement_rows.get(f"{state_id}_{region}", []):
                    rows.append(
                        {
                            "state_id": state_id,
                            "region": region,
                            **row,
                        }
                    )
            write_csv(
                run_dir / f"placement_{suffix}.csv",
                rows,
                fieldnames=placement_fields,
            )

        if "B" in audit_payloads:
            write_json(
                run_dir / "dataset_invariants_before.json",
                audit_payloads["B"],
            )
        if "C" in audit_payloads:
            write_json(
                run_dir / "dataset_invariants_after.json",
                audit_payloads["C"],
            )
        write_json(run_dir / "dataset_audits.json", audit_payloads)
        write_yaml(
            run_dir / "placement_intervention_manifest.yml",
            {
                "run_id": run_id,
                "b_setup_moves": b_setup_moves,
                "c_concentration_moves": c_moves,
                "restore_moves": restore_moves,
                "restore_status": restore_status,
                "transfer_mode": "block_writes",
            },
        )
        raw_manifest = {
            "run_id": run_id,
            "analysis_id": config["analysis_id"],
            "status": "completed" if error is None else "failed",
            "created_at_utc": utc_timestamp(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "config": str(config_path),
            "config_sha256": hashlib.sha256(
                config_path.read_bytes()
            ).hexdigest(),
            "plan": str(plan_path),
            "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "bounded_query_count": (
                2 * len(conditions) * len(repetition_indices)
            ),
            "smoke_conditions": list(conditions),
            "repetition_indices": list(repetition_indices),
            "dataset_load_dirs": load_dirs,
            "fdw_bootstrap_dirs": fdw_dirs,
            "query_sweeps": query_sweeps,
            "runtime_config": fixed_runtime,
            "runtime_config_sha256": canonical_sha256(fixed_runtime),
            "network_intervention_apply_dir": (
                "" if network_apply_dir is None else str(network_apply_dir)
            ),
            "network_intervention_reset_dir": (
                "" if network_reset_dir is None else str(network_reset_dir)
            ),
            "restore_status": restore_status,
            "database_result_rows_stored": args.result_snapshot_only,
            "collection_mode": (
                "correctness_only_result_snapshot"
                if args.result_snapshot_only
                else "full_instrumentation"
            ),
            "error_type": type(error).__name__ if error else "",
            "error": str(error) if error else "",
        }
        write_json(raw_manifest_path, raw_manifest)
        write_json(
            status_path,
            {
                "run_id": run_id,
                "status": raw_manifest["status"],
                "updated_at_utc": utc_timestamp(),
                "restore_status": restore_status,
                "error": raw_manifest["error"],
            },
        )

    print(str(run_dir), flush=True)
    if error is not None:
        raise error
    log_event(
        "SMOKE",
        f"completed restore={restore_status} artifact={run_dir}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
