#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"
MAX_EXECUTION_ID_CHARS = 120


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect one query-bounded psql-benchmarks execution across DB nodes."
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--sql-file", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "query-collections",
    )
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--remote-bench-dir", default="/opt/psql-benchmarks")
    parser.add_argument(
        "--target-group",
        default="coordinators",
        help="Inventory group containing the node where the SQL is executed.",
    )
    parser.add_argument(
        "--target-host",
        default="",
        help="Optional explicit inventory host name inside --target-group.",
    )
    parser.add_argument("--var", action="append", default=[], help="psql variable as name=value")
    parser.add_argument(
        "--execution-metadata-json",
        default="{}",
        help="Versioned execution identity metadata copied into the raw collection manifest.",
    )
    parser.add_argument(
        "--pg-option",
        action="append",
        default=[],
        help="Session PostgreSQL option as name=value. May be repeated.",
    )
    parser.add_argument(
        "--skip-db-snapshots",
        action="store_true",
        help=("Compatibility flag. Per-query DB snapshots are disabled by default."),
    )
    parser.add_argument(
        "--db-snapshots",
        action="store_true",
        help=(
            "Opt in to before/after PostgreSQL/Citus snapshots for profiling. "
            "Not part of the core thesis collection contract."
        ),
    )
    parser.add_argument(
        "--os-sampler",
        action="store_true",
        help=(
            "Opt in to query-window OS/network/disk sampling for profiling. "
            "Not part of the core thesis collection contract."
        ),
    )
    parser.add_argument(
        "--os-sampler-node-group",
        action="append",
        default=[],
        help=(
            "Additional inventory group sampled during the query window. "
            "May be repeated and only applies with --os-sampler."
        ),
    )
    parser.add_argument(
        "--os-sampler-interval-seconds",
        type=float,
        default=0.25,
        help=(
            "OS sampler interval for query-aligned profiling. The default "
            "captures short queries without invoking qdisc inspection on "
            "every intermediate sample."
        ),
    )
    parser.add_argument(
        "--result-signature",
        action="store_true",
        help=(
            "Execute the SQL once after the instrumented capture and persist only "
            "an order-independent result hash and row count. Result rows are never stored."
        ),
    )
    parser.add_argument(
        "--result-snapshot-only",
        action="store_true",
        help="Execute only a bounded typed result snapshot for correctness recovery.",
    )
    parser.add_argument("--result-snapshot-max-rows", type=int, default=100)
    parser.add_argument(
        "--result-snapshot-max-bytes",
        type=int,
        default=10 * 1024 * 1024,
    )
    parser.add_argument(
        "--remote-edge-context",
        action="store_true",
        help=(
            "Collect lightweight route and RTT context from every regional "
            "coordinator to the selected analytics/GAC node immediately before "
            "and after the primary instrumented query."
        ),
    )
    parser.add_argument(
        "--hard-timeout-seconds",
        type=int,
        default=0,
        help=(
            "Maximum wall-clock seconds for the remote explain-sql command. "
            "Timeouts are recorded as execution_status=timeout and do not make "
            "the surrounding sweep stop."
        ),
    )
    parser.add_argument(
        "--timeout-grace-seconds",
        type=int,
        default=30,
        help="Seconds to wait before force-killing a timed-out remote command.",
    )
    parser.add_argument(
        "--fdw-auto-explain",
        action="store_true",
        help=(
            "Enable instrumented regional auto_explain capture around this query. "
            "This is intended for GAC postgres_fdw runs and requires SSH access to "
            "regional coordinators plus superuser psql on those nodes."
        ),
    )
    parser.add_argument("--fdw-auto-explain-role", default="postgres")
    parser.add_argument("--fdw-auto-explain-database", default="app")
    parser.add_argument("--fdw-auto-explain-analytics-database", default="analytics")
    parser.add_argument("--fdw-auto-explain-coordinator-group", default="coordinators")
    parser.add_argument(
        "--fdw-auto-explain-region",
        action="append",
        default=[],
        help=(
            "Limit regional auto_explain and remote-edge collection to one or "
            "more logical regions. May be repeated; the default captures every "
            "coordinator in --fdw-auto-explain-coordinator-group."
        ),
    )
    parser.add_argument("--fdw-auto-explain-log-min-duration-ms", type=int, default=0)
    parser.add_argument("--no-citus-explain-all-tasks", action="store_true")
    return parser.parse_args()


def safe_path_component(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in {".", "_", "-"} else "-"
        for character in value
    ).strip(".-_")


def bounded_execution_id(timestamp: str, label: str) -> str:
    safe_label = safe_path_component(label) or "query"
    raw_value = f"{timestamp}-{safe_label}"
    if len(raw_value) <= MAX_EXECUTION_ID_CHARS:
        return raw_value

    label_hash = hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]
    prefix_chars = 36
    suffix_chars = MAX_EXECUTION_ID_CHARS - len(timestamp) - len(label_hash) - 5 - prefix_chars
    suffix_chars = max(24, suffix_chars)
    bounded_label = f"{safe_label[:prefix_chars]}--{label_hash}--{safe_label[-suffix_chars:]}"
    return f"{timestamp}-{bounded_label}"[:MAX_EXECUTION_ID_CHARS]


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


def resolve_path(path: Path) -> Path:
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([REPO_ROOT / path, REPO_ROOT.parent / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"File not found: {path}")


def load_inventory(
    path: Path,
    *,
    target_group: str,
    target_host: str,
) -> tuple[dict[str, dict[str, Any]], str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    children = data["all"]["children"]
    hosts = children.get(target_group, {}).get("hosts", {})
    if not hosts:
        raise RuntimeError(f"No hosts found in generated Ansible inventory group: {target_group}")
    hosts = rewrite_inventory_hosts_for_ssh(hosts)
    if target_host:
        if target_host not in hosts:
            raise RuntimeError(
                f"Host {target_host!r} not found in inventory group {target_group!r}."
            )
        selected_name = target_host
    else:
        selected_name = sorted(hosts)[0]
    return hosts, selected_name, hosts[selected_name]


def load_inventory_group(path: Path, *, group: str) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    hosts = data["all"]["children"].get(group, {}).get("hosts", {})
    if not hosts:
        raise RuntimeError(f"No hosts found in generated Ansible inventory group: {group}")
    return rewrite_inventory_hosts_for_ssh(hosts)


def rewrite_inventory_hosts_for_ssh(hosts: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    host_field = os.environ.get("MASTER_REGIMES_SSH_HOST_FIELD", "ansible_host").strip()
    if not host_field or host_field == "ansible_host":
        return hosts

    rewritten: dict[str, dict[str, Any]] = {}
    for name, host_info in hosts.items():
        preferred_host = str(host_info.get(host_field, "") or "").strip()
        if not preferred_host:
            rewritten[name] = host_info
            continue
        rewritten[name] = {
            **host_info,
            "original_ansible_host": host_info.get("ansible_host", ""),
            "ansible_host": preferred_host,
        }
    return rewritten


def run_command(
    command: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=check,
        )
    except subprocess.CalledProcessError as error:
        if error.stdout:
            sys.stderr.write(error.stdout[-4000:])
            if not error.stdout.endswith("\n"):
                sys.stderr.write("\n")
        if error.stderr:
            sys.stderr.write(error.stderr[-4000:])
            if not error.stderr.endswith("\n"):
                sys.stderr.write("\n")
        raise


def ssh_base(host: str, user: str, key_file: Path | None) -> list[str]:
    control_path = Path.home() / ".ssh" / "master-regimes-%C"
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ControlMaster=auto",
        "-o",
        "ControlPersist=120",
        "-o",
        f"ControlPath={control_path}",
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
    input_text: str | None = None,
    check: bool = True,
    transport_attempts: int = 1,
    retry_delay_seconds: float = 2.0,
) -> subprocess.CompletedProcess[str]:
    command = [
        *ssh_base(host, user, key_file),
        f"bash -lc {shlex.quote(remote_script)}",
    ]
    for attempt in range(1, max(1, transport_attempts) + 1):
        try:
            result = run_command(
                command,
                input_text=input_text,
                check=check,
            )
            if result.returncode != 255 or attempt >= transport_attempts:
                return result
            sys.stderr.write(
                "[SSH] transient transport failure; retrying "
                f"{attempt + 1}/{transport_attempts} for {host}\n"
            )
            time.sleep(retry_delay_seconds)
        except subprocess.CalledProcessError as error:
            if error.returncode != 255 or attempt >= transport_attempts:
                raise
            sys.stderr.write(
                "[SSH] transient transport failure; retrying "
                f"{attempt + 1}/{transport_attempts} for {host}\n"
            )
            time.sleep(retry_delay_seconds)
    raise AssertionError("unreachable")


def _remote_edge_probe_script(target_ip: str) -> str:
    return f"""
import json
import re
import statistics
import subprocess
import time

TARGET_IP = {target_ip!r}

def run(command):
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    return {{
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }}

route = run(["ip", "-j", "route", "get", TARGET_IP])
try:
    route_json = json.loads(route["stdout"])
except json.JSONDecodeError:
    route_json = []
route_row = route_json[0] if route_json else {{}}
device = str(route_row.get("dev", ""))
ping = run(["ping", "-n", "-c", "5", "-W", "2", TARGET_IP])
times = [
    float(value)
    for value in re.findall(r"time[=<]([0-9.]+)\\s*ms", ping["stdout"])
]
loss_match = re.search(r"([0-9.]+)%\\s+packet loss", ping["stdout"])
rtt_match = re.search(
    r"=\\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\\s*ms",
    ping["stdout"],
)
qdisc = run(["tc", "-j", "-s", "qdisc", "show", "dev", device]) if device else {{}}
filters = (
    run(["tc", "-j", "-s", "filter", "show", "dev", device, "parent", "1:0"])
    if device
    else {{}}
)
try:
    qdisc_json = json.loads(qdisc.get("stdout", "") or "[]")
except json.JSONDecodeError:
    qdisc_json = []
try:
    filter_json = json.loads(filters.get("stdout", "") or "[]")
except json.JSONDecodeError:
    filter_json = []

print(json.dumps({{
    "observed_at_unix": time.time(),
    "target_ip": TARGET_IP,
    "route_status": "available" if route_row else "missing",
    "route": route_row,
    "route_device": device,
    "route_source_ip": route_row.get("prefsrc", ""),
    "ping_status": "available" if times else "missing",
    "ping_packets_requested": 5,
    "ping_packets_received": len(times),
    "packet_loss_percent": (
        float(loss_match.group(1)) if loss_match else ""
    ),
    "rtt_min_ms": float(rtt_match.group(1)) if rtt_match else "",
    "rtt_avg_ms": float(rtt_match.group(2)) if rtt_match else "",
    "rtt_max_ms": float(rtt_match.group(3)) if rtt_match else "",
    "rtt_mdev_ms": float(rtt_match.group(4)) if rtt_match else "",
    "rtt_median_ms": statistics.median(times) if times else "",
    "rtt_samples_ms": times,
    "ping_raw": ping,
    "qdisc_json": qdisc_json,
    "qdisc_status": "available" if qdisc.get("returncode") == 0 else "missing",
    "filter_json": filter_json,
    "filter_status": "available" if filters.get("returncode") == 0 else "missing",
}}, sort_keys=True))
"""


def collect_remote_edge_context(
    *,
    coordinator_hosts: dict[str, dict[str, Any]],
    destination_name: str,
    destination: dict[str, Any],
    ssh_user: str,
    key_file: Path | None,
    stage: str,
) -> dict[str, dict[str, Any]]:
    destination_ip = str(destination.get("private_ip", "") or "").strip()
    if not destination_ip:
        return {}
    observations: dict[str, dict[str, Any]] = {}
    for host_name, host_info in sorted(coordinator_hosts.items()):
        source_cluster_id = str(
            host_info.get("logical_region") or logical_region_for_host(host_name)
        )
        edge_id = f"{source_cluster_id}->{destination_name}"
        result = ssh_run(
            str(host_info["ansible_host"]),
            ssh_user,
            key_file,
            f"python3 - <<'PY'\n{_remote_edge_probe_script(destination_ip)}\nPY",
            check=False,
        )
        try:
            payload = json.loads(result.stdout.strip() or "{}")
        except json.JSONDecodeError:
            payload = {}
        availability_status = (
            "available"
            if result.returncode == 0
            and payload.get("route_status") == "available"
            and payload.get("ping_status") == "available"
            else "partial"
        )
        observations[edge_id] = {
            "edge_id": edge_id,
            "source_cluster_id": source_cluster_id,
            "source_node": host_name,
            "source_host": host_info.get("ansible_host", ""),
            "source_private_ip": host_info.get("private_ip", ""),
            "destination_gac_id": destination_name,
            "destination_host": destination.get("ansible_host", ""),
            "destination_private_ip": destination_ip,
            "stage": stage,
            "availability_status": availability_status,
            "measurement_quality": "lightweight_context_not_query_socket_measurement",
            "ssh_returncode": result.returncode,
            "ssh_stderr": result.stderr,
            **payload,
        }
    return observations


def merge_remote_edge_context(
    *,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for edge_id in sorted(set(before) | set(after)):
        before_row = before.get(edge_id, {})
        after_row = after.get(edge_id, {})
        identity = before_row or after_row
        rows.append(
            {
                key: identity.get(key, "")
                for key in (
                    "edge_id",
                    "source_cluster_id",
                    "source_node",
                    "source_host",
                    "source_private_ip",
                    "destination_gac_id",
                    "destination_host",
                    "destination_private_ip",
                )
            }
            | {
                "before": before_row,
                "after": after_row,
                "availability_status": (
                    "available"
                    if before_row.get("availability_status") == "available"
                    and after_row.get("availability_status") == "available"
                    else "partial"
                ),
                "measurement_quality": "lightweight_context_not_query_socket_measurement",
            }
        )
    return rows


def parse_run_dir(output: str) -> str:
    for line in reversed(output.splitlines()):
        if line.startswith("Run directory: "):
            return line.split(": ", 1)[1].strip()
        if line.startswith("/"):
            return line.strip()
    raise RuntimeError(f"Unable to parse run directory from output:\n{output}")


def query_capture_start_script(
    *,
    remote_bench_dir: str,
    remote_label: str,
    capture_db_snapshots: bool,
    capture_os_samples: bool,
    sample_interval_seconds: float,
) -> str:
    """Build an idempotent remote capture start for SSH transport retries."""
    safe_label = safe_path_component(remote_label)
    if not safe_label or safe_label != remote_label:
        raise ValueError(f"Unsafe remote capture label: {remote_label!r}")

    snapshot_arg = " --db-snapshots" if capture_db_snapshots else ""
    os_sampler_arg = " --os-sampler" if capture_os_samples else ""
    sampler_env = (
        f"BENCH_SAMPLE_INTERVAL_SECONDS={sample_interval_seconds:g} "
        if capture_os_samples
        else ""
    )
    start_command = (
        f"cd {shlex.quote(remote_bench_dir)} && "
        f"{sampler_env}./bin/query-capture-start --label "
        f"{shlex.quote(remote_label)}{snapshot_arg}{os_sampler_arg}"
    )
    active_file = (
        '"${BENCH_RUN_ROOT:-/var/lib/psql-benchmarks/runs}/.active/'
        f'{safe_label}.json"'
    )
    recover_command = (
        "python3 -c "
        + shlex.quote(
            "import json,sys; "
            "print(json.load(open(sys.argv[1], encoding='utf-8'))['run_dir'])"
        )
        + ' "$active_file"'
    )
    command = (
        f"active_file={active_file}; "
        f"if test -s \"$active_file\"; then {recover_command}; "
        f"else {start_command}; fi"
    )
    if capture_os_samples:
        command = (
            "printf '__MR_CLOCK_BEFORE__='; date +%s.%N; "
            f"{command}; capture_status=$?; "
            "printf '__MR_CLOCK_AFTER__='; date +%s.%N; "
            "exit $capture_status"
        )
    return command


def parse_clock_calibration(
    output: str,
    *,
    controller_started_at_unix: float,
    controller_finished_at_unix: float,
) -> dict[str, Any]:
    values: dict[str, float] = {}
    for line in output.splitlines():
        for marker, key in (
            ("__MR_CLOCK_BEFORE__=", "remote_started_at_unix"),
            ("__MR_CLOCK_AFTER__=", "remote_finished_at_unix"),
        ):
            if line.startswith(marker):
                values[key] = float(line.split("=", 1)[1])
    if set(values) != {
        "remote_started_at_unix",
        "remote_finished_at_unix",
    }:
        return {
            "status": "missing",
            "controller_started_at_unix": controller_started_at_unix,
            "controller_finished_at_unix": controller_finished_at_unix,
        }
    controller_midpoint = (
        controller_started_at_unix + controller_finished_at_unix
    ) / 2
    remote_midpoint = (
        values["remote_started_at_unix"]
        + values["remote_finished_at_unix"]
    ) / 2
    controller_duration = (
        controller_finished_at_unix - controller_started_at_unix
    )
    remote_duration = (
        values["remote_finished_at_unix"]
        - values["remote_started_at_unix"]
    )
    return {
        "status": "available",
        "method": "capture_start_envelope",
        **values,
        "controller_started_at_unix": controller_started_at_unix,
        "controller_finished_at_unix": controller_finished_at_unix,
        "remote_minus_controller_seconds": (
            remote_midpoint - controller_midpoint
        ),
        "uncertainty_seconds": max(
            0.0,
            (controller_duration - remote_duration) / 2,
        ),
    }


def probe_remote_clock(
    host: str,
    user: str,
    key_file: Path | None,
    *,
    probe_count: int = 3,
) -> dict[str, Any]:
    probes: list[dict[str, Any]] = []
    for probe_index in range(probe_count):
        controller_started_at_unix = time.time()
        result = ssh_run(
            host,
            user,
            key_file,
            "date +%s.%N",
            check=False,
        )
        controller_finished_at_unix = time.time()
        if result.returncode != 0:
            continue
        try:
            remote_at_unix = float(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            continue
        controller_midpoint = (
            controller_started_at_unix + controller_finished_at_unix
        ) / 2
        probes.append(
            {
                "probe_index": probe_index,
                "controller_started_at_unix": controller_started_at_unix,
                "controller_finished_at_unix": controller_finished_at_unix,
                "remote_at_unix": remote_at_unix,
                "remote_minus_controller_seconds": (
                    remote_at_unix - controller_midpoint
                ),
                "uncertainty_seconds": (
                    controller_finished_at_unix
                    - controller_started_at_unix
                )
                / 2,
            }
        )
    if not probes:
        return {
            "status": "missing",
            "method": "minimum_rtt_multiplexed_ssh_probe",
            "probe_count": probe_count,
        }
    best = min(probes, key=lambda probe: probe["uncertainty_seconds"])
    return {
        "status": "available",
        "method": "minimum_rtt_multiplexed_ssh_probe",
        "probe_count": probe_count,
        "selected_probe_index": best["probe_index"],
        "probe_uncertainty_seconds": [
            probe["uncertainty_seconds"] for probe in probes
        ],
        **{
            key: value
            for key, value in best.items()
            if key != "probe_index"
        },
    }


def remote_query_window(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    run_dir: str,
    clock_calibration: dict[str, Any],
    fallback_started_at_unix: float,
    fallback_finished_at_unix: float,
) -> dict[str, Any]:
    result = ssh_run(
        host,
        user,
        key_file,
        f"cat {shlex.quote(run_dir)}/execution_manifest.json",
        check=False,
    )
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout)
            timing = payload.get("timing") or {}
            remote_started = float(timing["query_started_at_unix"])
            remote_finished = float(timing["query_finished_at_unix"])
            offset = float(
                clock_calibration.get(
                    "remote_minus_controller_seconds",
                    0.0,
                )
            )
            return {
                "status": "available",
                "source": "gac_execution_manifest",
                "gac_started_at_unix": remote_started,
                "gac_finished_at_unix": remote_finished,
                "controller_started_at_unix": remote_started - offset,
                "controller_finished_at_unix": remote_finished - offset,
            }
        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            pass
    return {
        "status": "fallback",
        "source": "controller_ssh_envelope",
        "controller_started_at_unix": fallback_started_at_unix,
        "controller_finished_at_unix": fallback_finished_at_unix,
    }


def validate_vars(vars_raw: list[str]) -> None:
    for item in vars_raw:
        if "=" not in item:
            raise ValueError(f"Invalid --var value, expected name=value: {item}")


def key_value_map(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        key, value = item.split("=", 1)
        result[key] = value
    return result


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def logical_region_for_host(host_name: str) -> str:
    return host_name.split("-", 1)[0].lower()


def filter_hosts_by_regions(
    hosts: dict[str, dict[str, Any]],
    *,
    regions: list[str],
) -> dict[str, dict[str, Any]]:
    normalized = {region.strip().lower() for region in regions if region.strip()}
    if not normalized:
        return hosts
    filtered = {
        host_name: host_info
        for host_name, host_info in hosts.items()
        if logical_region_for_host(host_name) in normalized
    }
    if not filtered:
        raise RuntimeError(
            "No regional coordinators matched --fdw-auto-explain-region: "
            + ", ".join(sorted(normalized))
        )
    return filtered


def auto_explain_application_name(*, remote_label_hash: str, suffix: str) -> str:
    value = f"mr-{remote_label_hash}-{suffix}"
    return value[:63]


def regional_auto_explain_settings_sql(
    *,
    role: str,
    database: str,
    log_min_duration_ms: int,
) -> str:
    role_sql = sql_identifier(role)
    database_sql = sql_identifier(database)
    reset_sql = regional_auto_explain_reset_sql(role=role, database=database)
    return f"""
{reset_sql}
ALTER ROLE {role_sql} IN DATABASE {database_sql} SET session_preload_libraries = 'auto_explain';
ALTER ROLE {role_sql} IN DATABASE {database_sql}
  SET auto_explain.log_min_duration = {int(log_min_duration_ms)};
ALTER ROLE {role_sql} IN DATABASE {database_sql} SET auto_explain.log_analyze = on;
ALTER ROLE {role_sql} IN DATABASE {database_sql} SET auto_explain.log_format = 'json';
ALTER ROLE {role_sql} IN DATABASE {database_sql} SET auto_explain.log_verbose = on;
ALTER ROLE {role_sql} IN DATABASE {database_sql} SET auto_explain.log_buffers = on;
ALTER ROLE {role_sql} IN DATABASE {database_sql} SET auto_explain.log_timing = off;
ALTER ROLE {role_sql} IN DATABASE {database_sql} SET citus.explain_all_tasks = on;
""".strip()


def regional_auto_explain_reset_sql(*, role: str, database: str) -> str:
    role_sql = sql_identifier(role)
    database_sql = sql_identifier(database)
    settings = [
        "session_preload_libraries",
        "auto_explain.log_min_duration",
        "auto_explain.log_analyze",
        "auto_explain.log_format",
        "auto_explain.log_verbose",
        "auto_explain.log_buffers",
        "auto_explain.log_timing",
        "citus.explain_all_tasks",
    ]
    return "\n".join(
        f"ALTER ROLE {role_sql} IN DATABASE {database_sql} RESET {setting};" for setting in settings
    )


def fdw_application_name_sql(
    *,
    regions: list[str],
    remote_label_hash: str,
) -> str:
    checks: list[str] = []
    alters: list[str] = []
    for region in regions:
        server = f"{region}_citus"
        checks.append(
            f"""
  IF NOT EXISTS (SELECT 1 FROM pg_foreign_server WHERE srvname = {sql_literal(server)}) THEN
    RAISE EXCEPTION 'FDW server not found: %', {sql_literal(server)};
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_foreign_server
    WHERE srvname = {sql_literal(server)}
      AND EXISTS (SELECT 1 FROM unnest(srvoptions) opt WHERE opt LIKE 'application_name=%')
  ) THEN
    RAISE EXCEPTION 'FDW server already has application_name option: %', {sql_literal(server)};
  END IF;
""".rstrip()
        )
        app_name = auto_explain_application_name(
            remote_label_hash=remote_label_hash,
            suffix=region,
        )
        application_name = sql_literal(app_name)
        alters.append(
            f"ALTER SERVER {sql_identifier(server)} "
            f"OPTIONS (ADD application_name {application_name});"
        )
    return "DO $$\nBEGIN\n" + "\n".join(checks) + "\nEND $$;\n" + "\n".join(alters)


def fdw_application_name_reset_sql(*, regions: list[str]) -> str:
    statements: list[str] = []
    for region in regions:
        server = f"{region}_citus"
        statements.append(
            f"""
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_foreign_server
    WHERE srvname = {sql_literal(server)}
      AND EXISTS (SELECT 1 FROM unnest(srvoptions) opt WHERE opt LIKE 'application_name=%')
  ) THEN
    ALTER SERVER {sql_identifier(server)} OPTIONS (DROP application_name);
  END IF;
END $$;
""".strip()
        )
    return "\n".join(statements)


def fetch_remote_dir(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    remote_dir: str,
    local_dir: Path,
) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    remote_parent = shlex.quote(str(Path(remote_dir).parent))
    remote_name = shlex.quote(Path(remote_dir).name)
    command = f"tar -C {remote_parent} -czf - {remote_name}"
    tar_result = subprocess.run(
        [*ssh_base(host, user, key_file), command],
        check=True,
        capture_output=True,
    )
    extract = subprocess.run(
        ["tar", "-xzf", "-", "-C", str(local_dir)],
        input=tar_result.stdout,
        check=True,
        capture_output=True,
    )
    if extract.stderr:
        sys.stderr.write(extract.stderr.decode(errors="replace"))


def psql_superuser_script(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    database: str,
    sql: str,
    check: bool = True,
    transport_attempts: int = 1,
    retry_delay_seconds: float = 2.0,
) -> subprocess.CompletedProcess[str]:
    script = f"sudo -u postgres psql -v ON_ERROR_STOP=1 -d {shlex.quote(database)}"
    command = [*ssh_base(host, user, key_file), script]
    for attempt in range(1, max(1, transport_attempts) + 1):
        try:
            result = run_command(
                command,
                input_text=sql,
                check=check,
            )
            if result.returncode != 255 or attempt >= transport_attempts:
                return result
            sys.stderr.write(
                "[SSH] transient transport failure; retrying PostgreSQL setup "
                f"{attempt + 1}/{transport_attempts} for {host}\n"
            )
            time.sleep(retry_delay_seconds)
        except subprocess.CalledProcessError as error:
            if error.returncode != 255 or attempt >= transport_attempts:
                raise
            sys.stderr.write(
                "[SSH] transient transport failure; retrying PostgreSQL setup "
                f"{attempt + 1}/{transport_attempts} for {host}\n"
            )
            time.sleep(retry_delay_seconds)
    raise AssertionError("unreachable")


def enable_regional_auto_explain(
    *,
    coordinator_hosts: dict[str, dict[str, Any]],
    ssh_user: str,
    key_file: Path | None,
    role: str,
    database: str,
    log_min_duration_ms: int,
) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for host_name, host_info in sorted(coordinator_hosts.items()):
        host = host_info["ansible_host"]
        log_file = "/var/log/postgresql/postgresql-18-main.log"
        line_result = ssh_run(
            host,
            ssh_user,
            key_file,
            f"wc -l < {shlex.quote(log_file)}",
            transport_attempts=3,
        )
        start_line = int(line_result.stdout.strip() or "0")
        psql_superuser_script(
            host=host,
            user=ssh_user,
            key_file=key_file,
            database=database,
            sql=regional_auto_explain_settings_sql(
                role=role,
                database=database,
                log_min_duration_ms=log_min_duration_ms,
            )
            + "\n",
            transport_attempts=3,
        )
        state[host_name] = {
            "host": host,
            "region": logical_region_for_host(host_name),
            "log_file": log_file,
            "start_line": start_line,
            "status": "enabled",
        }
    return state


def reset_regional_auto_explain(
    *,
    state: dict[str, dict[str, Any]],
    ssh_user: str,
    key_file: Path | None,
    role: str,
    database: str,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    sql = regional_auto_explain_reset_sql(role=role, database=database) + "\n"
    for host_name, entry in sorted(state.items()):
        result = psql_superuser_script(
            host=str(entry["host"]),
            user=ssh_user,
            key_file=key_file,
            database=database,
            sql=sql,
            check=False,
            transport_attempts=3,
        )
        if result.returncode != 0:
            errors.append(
                {
                    "host": host_name,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
    return errors


def fetch_regional_auto_explain_logs(
    *,
    state: dict[str, dict[str, Any]],
    ssh_user: str,
    key_file: Path | None,
    out_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    logs_dir = out_dir / "regional-auto-explain"
    logs_dir.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, str]] = []
    updated: dict[str, dict[str, Any]] = {}
    for host_name, entry in sorted(state.items()):
        log_file = str(entry["log_file"])
        start_line = int(entry["start_line"])
        local_file = logs_dir / f"{host_name}.postgresql-auto-explain.log"
        result = ssh_run(
            str(entry["host"]),
            ssh_user,
            key_file,
            f"tail -n +{start_line + 1} {shlex.quote(log_file)}",
            check=False,
            transport_attempts=3,
        )
        payload = {**entry}
        if result.returncode == 0:
            local_file.write_text(result.stdout, encoding="utf-8")
            payload["local_log_file"] = str(local_file.relative_to(out_dir))
            payload["captured_bytes"] = len(result.stdout.encode("utf-8"))
            payload["captured_lines"] = len(result.stdout.splitlines())
            payload["capture_status"] = "ok"
        else:
            payload["capture_status"] = "failed"
            errors.append(
                {
                    "host": host_name,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        updated[host_name] = payload
    return updated, errors


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_status(
    path: Path,
    *,
    execution_id: str,
    timestamp: str,
    status: str,
    sql_file: Path,
    variables: list[str],
    pg_options: list[str],
    coordinator: str | None = None,
    started: dict[str, str] | None = None,
    timeout: dict[str, Any] | None = None,
    error: BaseException | None = None,
) -> None:
    payload: dict[str, Any] = {
        "execution_id": execution_id,
        "created_at_utc": timestamp,
        "updated_at_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "status": status,
        "sql_file": str(sql_file),
        "variables": variables,
        "pg_options": pg_options,
    }
    if coordinator is not None:
        payload["coordinator"] = coordinator
    if started:
        payload["started_node_run_dirs"] = started
    if timeout is not None:
        payload["timeout"] = timeout
        payload["timed_out"] = True
        payload["hard_timeout_seconds"] = timeout.get("hard_timeout_seconds", "")
        payload["timeout_phase"] = timeout.get("phase", "")
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)
    write_json(path, payload)


def tail_text(value: str, *, max_chars: int = 4000) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def command_timed_out(result: subprocess.CompletedProcess[str]) -> bool:
    output = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode in {124, 137} or (
        "canceling statement due to statement timeout" in output
    )


def prune_fetched_query_copies(
    *,
    out_dir: Path,
    local_artifacts: dict[str, str],
) -> None:
    canonical_query = out_dir / "input" / "query.sql"
    for artifact_dir in local_artifacts.values():
        node_dir = out_dir / artifact_dir
        queries_dir = node_dir / "queries"
        if queries_dir.exists():
            shutil.rmtree(queries_dir)

        manifest_file = node_dir / "execution_manifest.json"
        if not manifest_file.exists():
            continue
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        manifest["query_copy"] = ""
        manifest["canonical_query_copy"] = os.path.relpath(canonical_query, node_dir)
        manifest["query_copy_policy"] = "deduplicated_to_query_collection_input"
        write_json(manifest_file, manifest)


def run_result_snapshot_only(
    *,
    args: argparse.Namespace,
    sql_path: Path,
    execution_metadata: dict[str, Any],
    target_name: str,
    target: dict[str, Any],
    key_file: Path | None,
    timestamp: str,
    execution_id: str,
    out_dir: Path,
    status_file: Path,
    remote_label: str,
    remote_sql: str,
) -> int:
    var_args = " ".join(f"--var {shlex.quote(item)}" for item in args.var)
    pg_option_args = " ".join(
        f"--pg-option {shlex.quote(item)}" for item in args.pg_option
    )
    remote_dir = ""
    timeout_event: dict[str, Any] | None = None
    error_event: dict[str, Any] | None = None
    try:
        ssh_run(
            target["ansible_host"],
            args.ssh_user,
            key_file,
            f"cat > {shlex.quote(remote_sql)}",
            input_text=sql_path.read_text(encoding="utf-8"),
            transport_attempts=3,
        )
        command = (
            f"./bin/result-snapshot --label {shlex.quote(remote_label)} "
            f"--sql-file {shlex.quote(remote_sql)} {var_args} {pg_option_args}"
        )
        if args.hard_timeout_seconds > 0:
            client_timeout = args.hard_timeout_seconds + max(
                args.timeout_grace_seconds,
                1,
            )
            command = (
                f"timeout --kill-after={max(args.timeout_grace_seconds, 1)}s "
                f"{client_timeout}s {command}"
            )
        result = ssh_run(
            target["ansible_host"],
            args.ssh_user,
            key_file,
            f"cd {shlex.quote(args.remote_bench_dir)} && {command}",
            check=False,
        )
        if result.returncode == 0:
            remote_dir = parse_run_dir(result.stdout)
        elif command_timed_out(result):
            timeout_event = {
                "phase": "result_snapshot",
                "hard_timeout_seconds": args.hard_timeout_seconds,
                "returncode": result.returncode,
                "stderr_tail": tail_text(result.stderr),
            }
        else:
            error_event = {
                "phase": "result_snapshot",
                "returncode": result.returncode,
                "stdout_tail": tail_text(result.stdout),
                "stderr_tail": tail_text(result.stderr),
            }
    finally:
        ssh_run(
            target["ansible_host"],
            args.ssh_user,
            key_file,
            f"rm -f {shlex.quote(remote_sql)}",
            check=False,
        )

    local_artifacts: dict[str, str] = {}
    snapshot_payload: dict[str, Any] = {}
    if remote_dir:
        local_node_dir = out_dir / "nodes" / target_name
        fetch_remote_dir(
            host=target["ansible_host"],
            user=args.ssh_user,
            key_file=key_file,
            remote_dir=remote_dir,
            local_dir=local_node_dir,
        )
        artifact_dir = local_node_dir / Path(remote_dir).name
        local_artifacts[target_name] = str(artifact_dir.relative_to(out_dir))
        snapshot_path = artifact_dir / "results/result_snapshot.json"
        snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        row_count = int(snapshot_payload.get("row_count", -1))
        output_bytes = int(snapshot_payload.get("output_byte_count", -1))
        if row_count > args.result_snapshot_max_rows:
            error_event = {
                "phase": "result_snapshot_contract",
                "error": (
                    f"row_count={row_count} exceeds "
                    f"limit={args.result_snapshot_max_rows}"
                ),
            }
        if output_bytes > args.result_snapshot_max_bytes:
            error_event = {
                "phase": "result_snapshot_contract",
                "error": (
                    f"output_byte_count={output_bytes} exceeds "
                    f"limit={args.result_snapshot_max_bytes}"
                ),
            }

    execution_status = "timeout" if timeout_event else "failed" if error_event else "completed"
    manifest = {
        "execution_id": execution_id,
        "attempt_id": execution_id,
        "created_at_utc": timestamp,
        "label": args.label,
        "collection_mode": "correctness_only_result_snapshot",
        "execution_status": execution_status,
        "timed_out": bool(timeout_event),
        "timeout": timeout_event,
        "error": error_event,
        "sql_file": str(sql_path),
        "query_copy": "input/query.sql",
        "query_bindings": "input/query_bindings.json",
        "variables": args.var,
        "pg_options": args.pg_option,
        "coordinator": target_name,
        "target_group": args.target_group,
        "execution_metadata": execution_metadata,
        "database_result_rows_stored": True,
        "result_snapshot": snapshot_payload,
        "local_artifacts": local_artifacts,
    }
    write_json(out_dir / "execution_manifest.json", manifest)
    write_status(
        status_file,
        execution_id=execution_id,
        timestamp=timestamp,
        status=execution_status,
        sql_file=sql_path,
        variables=args.var,
        pg_options=args.pg_option,
        coordinator=target_name,
        timeout=timeout_event,
        error=RuntimeError(str(error_event)) if error_event else None,
    )
    print(str(out_dir), flush=True)
    return 0 if execution_status == "completed" else 2


def main() -> int:
    args = parse_args()
    validate_vars(args.var)
    validate_vars(args.pg_option)
    if args.os_sampler_interval_seconds <= 0:
        raise ValueError("--os-sampler-interval-seconds must be positive.")
    if args.hard_timeout_seconds > 0 and not any(
        option.split("=", 1)[0].strip().lower() == "statement_timeout" for option in args.pg_option
    ):
        # The shell timeout bounds the client process. A server-side timeout is
        # also required so killing an SSH wrapper cannot leave a backend query running.
        args.pg_option.append(f"statement_timeout={args.hard_timeout_seconds * 1000}")
    execution_metadata = json.loads(args.execution_metadata_json)
    if not isinstance(execution_metadata, dict):
        raise ValueError("--execution-metadata-json must decode to a JSON object.")
    sql_path = resolve_path(args.sql_file)
    env_values = {**load_shell_env(args.env_file), **os.environ}
    key_value = env_values.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    key_file = Path(key_value).expanduser() if key_value else None
    if key_file is not None and not key_file.exists():
        raise FileNotFoundError(f"SSH private key not found: {key_file}")

    target_nodes, target_name, target = load_inventory(
        args.inventory,
        target_group=args.target_group,
        target_host=args.target_host,
    )
    if args.remote_edge_context and args.target_group != "analytics_clients":
        raise ValueError("--remote-edge-context requires --target-group analytics_clients")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    execution_id = bounded_execution_id(timestamp, args.label)
    out_dir = (args.out_root / execution_id).resolve()
    input_dir = out_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    status_file = out_dir / "execution_status.json"
    shutil.copy2(sql_path, input_dir / "query.sql")
    write_json(
        input_dir / "query_bindings.json",
        {
            "sql_parameterization": "psql_variables_not_inlined",
            "psql_variables": key_value_map(args.var),
            "pg_options": key_value_map(args.pg_option),
            "raw_psql_variables": args.var,
            "raw_pg_options": args.pg_option,
            "execution_metadata": execution_metadata,
        },
    )
    write_status(
        status_file,
        execution_id=execution_id,
        timestamp=timestamp,
        status="running",
        sql_file=sql_path,
        variables=args.var,
        pg_options=args.pg_option,
        coordinator=target_name,
    )

    remote_label_hash = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:16]
    remote_label = f"{timestamp}-{remote_label_hash}"
    remote_sql_hash = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:16]
    remote_sql = f"/tmp/master-regimes-query-{timestamp}-{remote_sql_hash}.sql"
    if args.result_snapshot_only:
        if any(
            (
                args.result_signature,
                args.os_sampler,
                args.db_snapshots,
                args.fdw_auto_explain,
                args.remote_edge_context,
            )
        ):
            raise ValueError(
                "--result-snapshot-only cannot be combined with collector instrumentation"
            )
        return run_result_snapshot_only(
            args=args,
            sql_path=sql_path,
            execution_metadata=execution_metadata,
            target_name=target_name,
            target=target,
            key_file=key_file,
            timestamp=timestamp,
            execution_id=execution_id,
            out_dir=out_dir,
            status_file=status_file,
            remote_label=remote_label,
            remote_sql=remote_sql,
        )
    bench_application_name = auto_explain_application_name(
        remote_label_hash=remote_label_hash,
        suffix="gac",
    )
    # The query executes on one selected host. Additional profiling nodes must
    # be requested explicitly through --os-sampler-node-group; capturing every
    # host in target_group creates unrelated artifacts for idle coordinators.
    capture_nodes = {target_name: target}
    if args.os_sampler:
        for group in args.os_sampler_node_group:
            capture_nodes.update(load_inventory_group(args.inventory, group=group))
    started: dict[str, str] = {}
    errors: list[dict[str, str]] = []
    timeout_event: dict[str, Any] | None = None
    query_error_event: dict[str, Any] | None = None
    result_signature_event: dict[str, Any] = {
        "enabled": args.result_signature,
        "status": "disabled" if not args.result_signature else "pending",
        "database_result_rows_stored": False,
    }
    fdw_auto_explain_state: dict[str, dict[str, Any]] = {}
    fdw_auto_explain_regions: list[str] = []
    fdw_application_name_enabled = False
    fdw_auto_explain_manifest: dict[str, Any] = {
        "enabled": args.fdw_auto_explain,
        "status": "disabled" if not args.fdw_auto_explain else "pending",
    }
    edge_coordinator_hosts = {}
    if args.remote_edge_context:
        edge_coordinator_hosts = filter_hosts_by_regions(
            load_inventory_group(
                args.inventory,
                group=args.fdw_auto_explain_coordinator_group,
            ),
            regions=args.fdw_auto_explain_region,
        )
    remote_edge_before: dict[str, dict[str, Any]] = {}
    remote_edge_after: dict[str, dict[str, Any]] = {}
    clock_calibrations: dict[str, dict[str, Any]] = {}
    primary_query_window: dict[str, Any] = {
        "status": "not_started",
        "source": "",
    }
    try:
        if args.fdw_auto_explain:
            coordinator_hosts = filter_hosts_by_regions(
                load_inventory_group(
                    args.inventory,
                    group=args.fdw_auto_explain_coordinator_group,
                ),
                regions=args.fdw_auto_explain_region,
            )
            if args.os_sampler and args.target_group == "analytics_clients":
                capture_nodes.update(coordinator_hosts)
            fdw_auto_explain_state = enable_regional_auto_explain(
                coordinator_hosts=coordinator_hosts,
                ssh_user=args.ssh_user,
                key_file=key_file,
                role=args.fdw_auto_explain_role,
                database=args.fdw_auto_explain_database,
                log_min_duration_ms=args.fdw_auto_explain_log_min_duration_ms,
            )
            fdw_auto_explain_regions = sorted(
                {
                    str(entry["region"])
                    for entry in fdw_auto_explain_state.values()
                    if entry.get("region")
                }
            )
            if args.target_group == "analytics_clients":
                psql_superuser_script(
                    host=target["ansible_host"],
                    user=args.ssh_user,
                    key_file=key_file,
                    database=args.fdw_auto_explain_analytics_database,
                    sql=fdw_application_name_sql(
                        regions=fdw_auto_explain_regions,
                        remote_label_hash=remote_label_hash,
                    )
                    + "\n",
                    transport_attempts=3,
                )
                fdw_application_name_enabled = True
            fdw_auto_explain_manifest = {
                "enabled": True,
                "status": "enabled",
                "coordinator_group": args.fdw_auto_explain_coordinator_group,
                "requested_regions": list(args.fdw_auto_explain_region),
                "role": args.fdw_auto_explain_role,
                "database": args.fdw_auto_explain_database,
                "analytics_database": args.fdw_auto_explain_analytics_database,
                "log_min_duration_ms": args.fdw_auto_explain_log_min_duration_ms,
                "regions": fdw_auto_explain_regions,
                "bench_application_name": bench_application_name,
                "fdw_application_name_enabled": fdw_application_name_enabled,
                "fdw_application_name_policy": (
                    "analytics_clients_only"
                    if not fdw_application_name_enabled
                    else "enabled_for_analytics_clients"
                ),
                "regional_hosts": fdw_auto_explain_state,
            }

        ssh_run(
            target["ansible_host"],
            args.ssh_user,
            key_file,
            f"cat > {shlex.quote(remote_sql)}",
            input_text=sql_path.read_text(encoding="utf-8"),
            transport_attempts=3,
        )
        if args.remote_edge_context:
            print("Collecting pre-query remote edge context...", flush=True)
            remote_edge_before = collect_remote_edge_context(
                coordinator_hosts=edge_coordinator_hosts,
                destination_name=target_name,
                destination=target,
                ssh_user=args.ssh_user,
                key_file=key_file,
                stage="before_primary_query",
            )
        for host_name, host_info in sorted(capture_nodes.items()):
            host = host_info["ansible_host"]
            print(f"Starting query capture on {host_name} ({host})...", flush=True)
            capture_command = query_capture_start_script(
                remote_bench_dir=args.remote_bench_dir,
                remote_label=remote_label,
                capture_db_snapshots=(
                    args.db_snapshots and not args.skip_db_snapshots
                ),
                capture_os_samples=args.os_sampler,
                sample_interval_seconds=args.os_sampler_interval_seconds,
            )
            controller_started_at_unix = time.time()
            result = ssh_run(
                host,
                args.ssh_user,
                key_file,
                capture_command,
                transport_attempts=3,
            )
            controller_finished_at_unix = time.time()
            started[host_name] = parse_run_dir(result.stdout)
            if args.os_sampler:
                fallback_calibration = parse_clock_calibration(
                    result.stdout,
                    controller_started_at_unix=controller_started_at_unix,
                    controller_finished_at_unix=controller_finished_at_unix,
                )
                clock_calibration = probe_remote_clock(
                    host,
                    args.ssh_user,
                    key_file,
                )
                if clock_calibration.get("status") != "available":
                    clock_calibration = fallback_calibration
                clock_calibration["fallback_capture_start_calibration"] = (
                    fallback_calibration
                )
                clock_calibrations[host_name] = clock_calibration
            write_status(
                status_file,
                execution_id=execution_id,
                timestamp=timestamp,
                status="running",
                sql_file=sql_path,
                variables=args.var,
                pg_options=args.pg_option,
                coordinator=target_name,
                started=started,
            )

        var_args = " ".join(f"--var {shlex.quote(item)}" for item in args.var)
        pg_option_args = " ".join(f"--pg-option {shlex.quote(item)}" for item in args.pg_option)
        citus_arg = " --no-citus-explain-all-tasks" if args.no_citus_explain_all_tasks else ""
        print(f"Executing EXPLAIN ANALYZE on {target_name}...", flush=True)
        explain_env = {
            "BENCH_APPLICATION_NAME": bench_application_name,
        }
        if args.fdw_auto_explain:
            explain_env["BENCH_FDW_REMOTE_PLAN_PROBE"] = "false"
        explain_env_prefix = " ".join(
            f"{key}={shlex.quote(value)}" for key, value in sorted(explain_env.items())
        )
        explain_command = (
            f"env {explain_env_prefix} "
            f"./bin/explain-sql --label {shlex.quote(remote_label)} "
            f"--sql-file {shlex.quote(remote_sql)} "
            f"{var_args} {pg_option_args}{citus_arg}"
        )
        if args.hard_timeout_seconds > 0:
            client_timeout_seconds = args.hard_timeout_seconds + max(args.timeout_grace_seconds, 1)
            explain_command = (
                f"timeout --kill-after={max(args.timeout_grace_seconds, 1)}s "
                f"{client_timeout_seconds}s {explain_command}"
            )
        fallback_started_at_unix = time.time()
        explain_result = ssh_run(
            target["ansible_host"],
            args.ssh_user,
            key_file,
            (f"cd {shlex.quote(args.remote_bench_dir)} && {explain_command}"),
            check=False,
        )
        fallback_finished_at_unix = time.time()
        primary_query_window = remote_query_window(
            host=target["ansible_host"],
            user=args.ssh_user,
            key_file=key_file,
            run_dir=started[target_name],
            clock_calibration=clock_calibrations.get(target_name, {}),
            fallback_started_at_unix=fallback_started_at_unix,
            fallback_finished_at_unix=fallback_finished_at_unix,
        )
        if command_timed_out(explain_result):
            timeout_event = {
                "phase": "explain_analyze",
                "hard_timeout_seconds": args.hard_timeout_seconds,
                "timeout_grace_seconds": max(args.timeout_grace_seconds, 1),
                "returncode": explain_result.returncode,
                "stdout_tail": tail_text(explain_result.stdout),
                "stderr_tail": tail_text(explain_result.stderr),
            }
            print(
                (
                    f"EXPLAIN ANALYZE timed out after "
                    f"{args.hard_timeout_seconds}s on {target_name}; continuing."
                ),
                flush=True,
            )
            write_status(
                status_file,
                execution_id=execution_id,
                timestamp=timestamp,
                status="timeout",
                sql_file=sql_path,
                variables=args.var,
                pg_options=args.pg_option,
                coordinator=target_name,
                started=started,
                timeout=timeout_event,
            )
        elif explain_result.returncode != 0:
            query_error_event = {
                "phase": "explain_analyze",
                "returncode": explain_result.returncode,
                "stdout_tail": tail_text(explain_result.stdout),
                "stderr_tail": tail_text(explain_result.stderr),
            }
            errors.append(
                {
                    "host": target_name,
                    "phase": "explain_analyze",
                    "stdout": explain_result.stdout,
                    "stderr": explain_result.stderr,
                }
            )
            print(
                (
                    f"EXPLAIN ANALYZE failed on {target_name} "
                    f"with return code {explain_result.returncode}; "
                    "recording failed query and continuing."
                ),
                flush=True,
            )
            write_status(
                status_file,
                execution_id=execution_id,
                timestamp=timestamp,
                status="failed",
                sql_file=sql_path,
                variables=args.var,
                pg_options=args.pg_option,
                coordinator=target_name,
                started=started,
                timeout=timeout_event,
                error=RuntimeError("EXPLAIN ANALYZE failed"),
            )
    except Exception as exc:
        write_status(
            status_file,
            execution_id=execution_id,
            timestamp=timestamp,
            status="failed",
            sql_file=sql_path,
            variables=args.var,
            pg_options=args.pg_option,
            coordinator=target_name,
            started=started,
            timeout=timeout_event,
            error=exc,
        )
        raise
    finally:
        for host_name, host_info in sorted(capture_nodes.items()):
            if host_name not in started:
                continue
            host = host_info["ansible_host"]
            print(f"Stopping query capture on {host_name} ({host})...", flush=True)
            clock_offset = float(
                clock_calibrations.get(host_name, {}).get(
                    "remote_minus_controller_seconds",
                    0.0,
                )
            )
            query_window_args = ""
            if primary_query_window.get("status") in {
                "available",
                "fallback",
            }:
                host_started_at_unix = (
                    float(primary_query_window["controller_started_at_unix"])
                    + clock_offset
                )
                host_finished_at_unix = (
                    float(primary_query_window["controller_finished_at_unix"])
                    + clock_offset
                )
                query_window_args = (
                    " --query-started-at-unix "
                    f"{host_started_at_unix:.9f}"
                    " --query-finished-at-unix "
                    f"{host_finished_at_unix:.9f}"
                )
            result = ssh_run(
                host,
                args.ssh_user,
                key_file,
                (
                    f"cd {shlex.quote(args.remote_bench_dir)} && "
                    "BENCH_SAMPLE_INTERVAL_SECONDS="
                    f"{args.os_sampler_interval_seconds:g} "
                    f"./bin/query-capture-stop --label {shlex.quote(remote_label)}"
                    f"{query_window_args}"
                ),
                check=False,
            )
            if result.returncode != 0:
                errors.append(
                    {
                        "host": host_name,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
        if args.remote_edge_context:
            print("Collecting post-query remote edge context...", flush=True)
            remote_edge_after = collect_remote_edge_context(
                coordinator_hosts=edge_coordinator_hosts,
                destination_name=target_name,
                destination=target,
                ssh_user=args.ssh_user,
                key_file=key_file,
                stage="after_primary_query",
            )
        if fdw_auto_explain_state:
            updated_state, log_errors = fetch_regional_auto_explain_logs(
                state=fdw_auto_explain_state,
                ssh_user=args.ssh_user,
                key_file=key_file,
                out_dir=out_dir,
            )
            fdw_auto_explain_state = updated_state
            fdw_auto_explain_manifest["regional_hosts"] = updated_state
            if log_errors:
                fdw_auto_explain_manifest["log_capture_errors"] = log_errors
                errors.extend(
                    {"host": item["host"], "stdout": item["stdout"], "stderr": item["stderr"]}
                    for item in log_errors
                )
        if fdw_application_name_enabled:
            result = psql_superuser_script(
                host=target["ansible_host"],
                user=args.ssh_user,
                key_file=key_file,
                database=args.fdw_auto_explain_analytics_database,
                sql=fdw_application_name_reset_sql(regions=fdw_auto_explain_regions) + "\n",
                check=False,
                transport_attempts=3,
            )
            if result.returncode != 0:
                errors.append(
                    {
                        "host": target_name,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                fdw_auto_explain_manifest["fdw_application_name_cleanup_status"] = "failed"
            else:
                fdw_auto_explain_manifest["fdw_application_name_cleanup_status"] = "ok"
        if fdw_auto_explain_state:
            reset_errors = reset_regional_auto_explain(
                state=fdw_auto_explain_state,
                ssh_user=args.ssh_user,
                key_file=key_file,
                role=args.fdw_auto_explain_role,
                database=args.fdw_auto_explain_database,
            )
            if reset_errors:
                fdw_auto_explain_manifest["regional_cleanup_status"] = "failed"
                fdw_auto_explain_manifest["regional_cleanup_errors"] = reset_errors
                errors.extend(
                    {"host": item["host"], "stdout": item["stdout"], "stderr": item["stderr"]}
                    for item in reset_errors
                )
            else:
                fdw_auto_explain_manifest["regional_cleanup_status"] = "ok"
                if fdw_auto_explain_manifest.get("status") == "enabled":
                    fdw_auto_explain_manifest["status"] = "captured"
        if (
            args.result_signature
            and target_name in started
            and timeout_event is None
            and query_error_event is None
        ):
            print(f"Computing stream-only result signature on {target_name}...", flush=True)
            signature_command = (
                f"./bin/result-signature --label {shlex.quote(remote_label)} "
                f"--run-dir {shlex.quote(started[target_name])} "
                f"--sql-file {shlex.quote(remote_sql)} "
                f"{var_args} {pg_option_args}"
            )
            if args.hard_timeout_seconds > 0:
                client_timeout_seconds = args.hard_timeout_seconds + max(
                    args.timeout_grace_seconds, 1
                )
                signature_command = (
                    f"timeout --kill-after={max(args.timeout_grace_seconds, 1)}s "
                    f"{client_timeout_seconds}s {signature_command}"
                )
            signature_result = ssh_run(
                target["ansible_host"],
                args.ssh_user,
                key_file,
                (f"cd {shlex.quote(args.remote_bench_dir)} && {signature_command}"),
                check=False,
            )
            if signature_result.returncode == 0:
                result_signature_event["status"] = "completed"
                result_signature_event["artifact"] = (
                    f"nodes/{target_name}/{Path(started[target_name]).name}/results/"
                    f"{Path(remote_sql).stem}.result-signature.json"
                )
            elif command_timed_out(signature_result):
                result_signature_event.update(
                    {
                        "status": "timeout",
                        "returncode": signature_result.returncode,
                        "hard_timeout_seconds": args.hard_timeout_seconds,
                        "stderr_tail": tail_text(signature_result.stderr),
                    }
                )
            else:
                result_signature_event.update(
                    {
                        "status": "failed",
                        "returncode": signature_result.returncode,
                        "stdout_tail": tail_text(signature_result.stdout),
                        "stderr_tail": tail_text(signature_result.stderr),
                    }
                )
                errors.append(
                    {
                        "host": target_name,
                        "phase": "result_signature",
                        "stdout": signature_result.stdout,
                        "stderr": signature_result.stderr,
                    }
                )
        elif args.result_signature:
            result_signature_event["status"] = "skipped_primary_execution_incomplete"
        ssh_run(
            target["ansible_host"],
            args.ssh_user,
            key_file,
            f"rm -f {shlex.quote(remote_sql)}",
            check=False,
        )

    try:
        for host_name, remote_dir in started.items():
            host = capture_nodes[host_name]["ansible_host"]
            print(f"Fetching artifacts from {host_name}...", flush=True)
            fetch_remote_dir(
                host=host,
                user=args.ssh_user,
                key_file=key_file,
                remote_dir=remote_dir,
                local_dir=out_dir / "nodes" / host_name,
            )
    except Exception as exc:
        write_status(
            status_file,
            execution_id=execution_id,
            timestamp=timestamp,
            status="failed",
            sql_file=sql_path,
            variables=args.var,
            pg_options=args.pg_option,
            coordinator=target_name,
            started=started,
            error=exc,
        )
        raise

    local_artifacts = {
        host_name: str((out_dir / "nodes" / host_name / Path(remote_dir).name).relative_to(out_dir))
        for host_name, remote_dir in started.items()
    }
    prune_fetched_query_copies(out_dir=out_dir, local_artifacts=local_artifacts)
    remote_edge_context = {
        "contract_version": "remote-edge-context-v1",
        "query_run_id": execution_id,
        "collection_scope": "lightweight_context_before_after_primary_query",
        "network_profile_id": execution_metadata.get("network_profile_id", ""),
        "network_profile_json": execution_metadata.get("network_profile_json", ""),
        "edges": merge_remote_edge_context(
            before=remote_edge_before,
            after=remote_edge_after,
        ),
    }
    remote_edge_context_file = out_dir / "remote_edge_context.json"
    if args.remote_edge_context:
        write_json(remote_edge_context_file, remote_edge_context)
    final_execution_status = "failed" if errors else ("timeout" if timeout_event else "completed")

    manifest = {
        "execution_id": execution_id,
        "attempt_id": execution_id,
        "remote_execution_label": remote_label,
        "created_at_utc": timestamp,
        "label": args.label,
        "path_component_policy": "bounded_timestamp_label_hash",
        "path_component_max_chars": MAX_EXECUTION_ID_CHARS,
        "sql_file": str(sql_path),
        "query_copy": "input/query.sql",
        "query_bindings": "input/query_bindings.json",
        "variables": args.var,
        "pg_options": args.pg_option,
        "coordinator": target_name,
        "target_group": args.target_group,
        "target_host": target_name,
        "execution_status": final_execution_status,
        "timed_out": timeout_event is not None,
        "hard_timeout_seconds": args.hard_timeout_seconds,
        "timeout_phase": timeout_event.get("phase", "") if timeout_event else "",
        "timeout": timeout_event,
        "query_error": query_error_event,
        "result_signature": result_signature_event,
        "execution_metadata": execution_metadata,
        "bench_application_name": bench_application_name,
        "fdw_auto_explain": fdw_auto_explain_manifest,
        "remote_edge_context": {
            "enabled": args.remote_edge_context,
            "status": (
                "available"
                if args.remote_edge_context and remote_edge_context["edges"]
                else "disabled"
                if not args.remote_edge_context
                else "missing"
            ),
            "artifact": (
                remote_edge_context_file.name if args.remote_edge_context else ""
            ),
            "edge_count": len(remote_edge_context["edges"]),
        },
        "query_telemetry_window": primary_query_window,
        "node_clock_calibrations": clock_calibrations,
        "node_run_dirs": started,
        "local_artifacts": local_artifacts,
        "collection_contract": {
            "feature_contract": "core_v1",
            "query_parallelism": "single query at a time",
            "text_plan": "EXPLAIN BUFFERS VERBOSE",
            "json_plan": "EXPLAIN ANALYZE BUFFERS VERBOSE FORMAT JSON",
            "citus_explain_all_tasks": not args.no_citus_explain_all_tasks,
            "query_results_saved": False,
            "result_signature_stream_only": args.result_signature,
            "hard_timeout_seconds": args.hard_timeout_seconds,
            "timeout_status_policy": (
                "record_and_continue" if args.hard_timeout_seconds > 0 else "disabled"
            ),
            "query_sql_copy_policy": "single canonical copy in input/query.sql",
            "captured_nodes": sorted(capture_nodes),
            "os_sampler_node_groups": (list(args.os_sampler_node_group) if args.os_sampler else []),
            "static_database_metadata_per_query": False,
            "per_query_global_db_snapshots": args.db_snapshots and not args.skip_db_snapshots,
            "global_db_snapshot_scope": (
                "query" if args.db_snapshots and not args.skip_db_snapshots else "disabled"
            ),
            "per_query_dynamic_snapshots": (
                [
                    "pg_stat_io",
                    "pg_stat_database",
                    "pg_stat_user_tables",
                    "pg_stat_user_indexes",
                    "pg_statio_user_tables",
                    "pg_statio_user_indexes",
                    "pg_stat_statements",
                    "citus_stat_counters on coordinator",
                    "citus_stat_statements on coordinator",
                ]
                if args.db_snapshots and not args.skip_db_snapshots
                else []
            ),
            "os_sampling": "profiling_enabled" if args.os_sampler else "disabled",
            "os_sampler_interval_seconds": (
                args.os_sampler_interval_seconds
                if args.os_sampler
                else None
            ),
            "os_query_alignment": (
                "clock_calibrated_query_bracket"
                if args.os_sampler
                else "disabled"
            ),
            "network_sampling": "profiling_enabled" if args.os_sampler else "disabled",
            "remote_edge_context": (
                "lightweight_before_after"
                if args.remote_edge_context
                else "disabled"
            ),
            "core_signal_sources": [
                "GAC/coordinator textual EXPLAIN",
                "GAC/coordinator EXPLAIN ANALYZE JSON",
                "query bindings",
                "runtime PGOPTIONS",
                "query timing",
            ],
            "debug_signal_sources": [
                "OS/network/disk samples when --os-sampler is passed",
                "PostgreSQL/Citus snapshot deltas when --db-snapshots is passed",
            ],
        },
        "errors": errors,
    }
    write_json(out_dir / "execution_manifest.json", manifest)
    if errors:
        write_status(
            status_file,
            execution_id=execution_id,
            timestamp=timestamp,
            status="failed",
            sql_file=sql_path,
            variables=args.var,
            pg_options=args.pg_option,
            coordinator=target_name,
            started=started,
            timeout=timeout_event,
            error=RuntimeError("query collection completed with errors"),
        )
    else:
        final_status = "timeout" if timeout_event else "completed"
        write_status(
            status_file,
            execution_id=execution_id,
            timestamp=timestamp,
            status=final_status,
            sql_file=sql_path,
            variables=args.var,
            pg_options=args.pg_option,
            coordinator=target_name,
            started=started,
            timeout=timeout_event,
        )
    print(str(out_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
