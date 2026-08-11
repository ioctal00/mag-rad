#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"
DEFAULT_GROUPS = "db_nodes,analytics_clients"

REMOTE_COLLECTOR = r'''
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time


def run_command(command, timeout=20):
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {
            "available": False,
            "command": command,
            "returncode": 127,
            "stdout": "",
            "stderr": "command not found",
        }
    except subprocess.TimeoutExpired as error:
        return {
            "available": shutil.which(command[0]) is not None,
            "command": command,
            "returncode": 124,
            "stdout": error.stdout or "",
            "stderr": error.stderr or "timeout",
        }
    return {
        "available": shutil.which(command[0]) is not None,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def parse_json_command(command_result):
    if command_result.get("returncode") != 0:
        return {}
    try:
        parsed = json.loads(command_result.get("stdout") or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def scalar(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def parse_lscpu(command_result):
    parsed = parse_json_command(command_result)
    rows = parsed.get("lscpu", [])
    values = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            field = str(row.get("field", "")).strip().rstrip(":")
            if field:
                values[field] = row.get("data", "")
    sockets = scalar(values.get("Socket(s)"))
    cores_per_socket = scalar(values.get("Core(s) per socket"))
    physical_cores = None
    if isinstance(sockets, int) and isinstance(cores_per_socket, int):
        physical_cores = sockets * cores_per_socket
    return {
        "architecture": values.get("Architecture"),
        "vendor_id": values.get("Vendor ID"),
        "model_name": values.get("Model name"),
        "logical_cpus": scalar(values.get("CPU(s)")),
        "threads_per_core": scalar(values.get("Thread(s) per core")),
        "cores_per_socket": cores_per_socket,
        "sockets": sockets,
        "physical_cores": physical_cores,
        "cpu_mhz": scalar(values.get("CPU MHz")),
        "cpu_min_mhz": scalar(values.get("CPU min MHz")),
        "cpu_max_mhz": scalar(values.get("CPU max MHz")),
        "hypervisor_vendor": values.get("Hypervisor vendor"),
        "virtualization_type": values.get("Virtualization type"),
        "caches": {
            "l1d": values.get("L1d cache"),
            "l1i": values.get("L1i cache"),
            "l2": values.get("L2 cache"),
            "l3": values.get("L3 cache"),
        },
        "raw_fields": values,
    }


def parse_meminfo():
    values = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError):
        lines = []
    for line in lines:
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        unit = parts[1].lower() if len(parts) > 1 else ""
        values[key] = value * 1024 if unit == "kb" else value
    return values


def memory_speed_values(text):
    speeds = []
    pattern = r"^\s*(?:Configured Memory Speed|Speed):\s+([0-9]+)\s+MT/s"
    for match in re.finditer(pattern, text, re.M):
        speeds.append(int(match.group(1)))
    return sorted(set(speeds))


def memory_devices(text):
    devices = []
    for block in re.split(r"\n\s*\n", text):
        if "Memory Device" not in block:
            continue
        values = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
        size = values.get("Size", "")
        if size and "No Module Installed" not in size:
            devices.append(
                {
                    "size": size,
                    "type": values.get("Type", ""),
                    "speed": values.get("Speed", ""),
                    "configured_speed": values.get("Configured Memory Speed", ""),
                    "manufacturer": values.get("Manufacturer", ""),
                    "part_number": values.get("Part Number", ""),
                }
            )
    return devices


def parse_lsblk(command_result):
    parsed = parse_json_command(command_result)
    devices = parsed.get("blockdevices", [])
    flat = []

    def as_bool(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        return str(value).strip() in {"1", "true", "True"}

    def infer_storage_class(device, root_disk):
        name = str(device.get("name") or device.get("kname") or "")
        path = str(device.get("path") or "")
        device_type = str(device.get("type") or "")
        transport = str(device.get("tran") or "").lower()
        model = str(device.get("model") or "").lower()
        rotational = as_bool(root_disk.get("rota", device.get("rota")))
        if device_type in {"loop", "rom"}:
            return device_type
        if transport == "nvme" or name.startswith("nvme") or "/nvme" in path:
            return "nvme"
        if name.startswith("vd") or path.startswith("/dev/vd") or "virtual" in model:
            return "virtual_disk_rotational_reported" if rotational else "virtual_ssd"
        if rotational is True:
            return "hdd"
        if rotational is False and transport in {"sata", "ata", "scsi", "sas"}:
            return "ssd"
        if rotational is False and transport in {"virtio", ""}:
            return "virtual_ssd"
        if "ssd" in model:
            return "ssd"
        if "nvme" in model:
            return "nvme"
        return "unknown"

    def visit(device, parent_name=None, root_disk=None):
        if not isinstance(device, dict):
            return
        current_root = device if device.get("type") == "disk" else root_disk or device
        mountpoints = device.get("mountpoints")
        if mountpoints is None:
            mountpoint = device.get("mountpoint")
            mountpoints = [] if mountpoint in (None, "") else [mountpoint]
        if isinstance(mountpoints, str):
            mountpoints = [mountpoints]
        row = {
            "name": device.get("name"),
            "kname": device.get("kname"),
            "path": device.get("path"),
            "type": device.get("type"),
            "size_bytes": scalar(device.get("size")),
            "model": device.get("model"),
            "serial": device.get("serial"),
            "rotational": as_bool(device.get("rota")),
            "transport": device.get("tran"),
            "physical_sector_bytes": scalar(device.get("phy-sec")),
            "logical_sector_bytes": scalar(device.get("log-sec")),
            "fstype": device.get("fstype"),
            "mountpoints": [item for item in mountpoints if item],
            "parent_name": parent_name,
            "root_disk_name": current_root.get("name"),
            "storage_class": infer_storage_class(device, current_root),
        }
        flat.append(row)
        for child in device.get("children") or []:
            visit(child, row["name"], current_root)

    if isinstance(devices, list):
        for device in devices:
            visit(device)

    top_disks = [item for item in flat if item.get("type") == "disk"]
    storage_classes = sorted(
        {item.get("storage_class") for item in top_disks if item.get("storage_class")}
    )

    def class_for_mount(target):
        for item in flat:
            if target in (item.get("mountpoints") or []):
                root_name = item.get("root_disk_name")
                for disk in top_disks:
                    if disk.get("name") == root_name:
                        return disk.get("storage_class")
                return item.get("storage_class")
        return ""

    return {
        "disk_count": len(top_disks),
        "disk_total_bytes": sum(int(item.get("size_bytes") or 0) for item in top_disks),
        "storage_classes": storage_classes,
        "root_storage_class": class_for_mount("/"),
        "postgres_storage_class": class_for_mount("/var/lib/postgresql") or class_for_mount("/"),
        "devices": flat,
    }


commands = {
    "lscpu_json": run_command(["lscpu", "--json"]),
    "lsblk_json": run_command(
        [
            "lsblk",
            "--json",
            "--bytes",
            "--output",
            "NAME,KNAME,PATH,TYPE,SIZE,MODEL,SERIAL,ROTA,TRAN,PHY-SEC,LOG-SEC,MOUNTPOINTS,FSTYPE",
        ]
    ),
    "free_bytes": run_command(["free", "-b"]),
    "df_root_postgres": run_command(["df", "-B1", "-PT", "/", "/var/lib/postgresql"]),
    "findmnt_root_json": run_command(["findmnt", "-J", "/"]),
    "findmnt_postgres_json": run_command(["findmnt", "-J", "/var/lib/postgresql"]),
    "dmidecode_memory": run_command(["dmidecode", "--type", "memory"], timeout=30),
    "dmidecode_processor": run_command(["dmidecode", "--type", "processor"], timeout=30),
    "lshw_json": run_command(
        [
            "lshw",
            "-json",
            "-class",
            "processor",
            "-class",
            "memory",
            "-class",
            "disk",
            "-class",
            "storage",
        ],
        timeout=30,
    ),
}

meminfo = parse_meminfo()
dmidecode_memory = commands["dmidecode_memory"].get("stdout") or ""
summary = {
    "hostname": platform.node(),
    "kernel": platform.release(),
    "platform": platform.platform(),
    "cpu": parse_lscpu(commands["lscpu_json"]),
    "memory": {
        "total_bytes": meminfo.get("MemTotal"),
        "available_bytes": meminfo.get("MemAvailable"),
        "speed_values_mt_s": memory_speed_values(dmidecode_memory),
        "devices": memory_devices(dmidecode_memory),
        "speed_source": (
            "dmidecode"
            if commands["dmidecode_memory"].get("returncode") == 0
            else "unavailable"
        ),
    },
    "storage": parse_lsblk(commands["lsblk_json"]),
}

print(
    json.dumps(
        {
            "collected_at_unix": time.time(),
            "collector": "collect_hardware_snapshot.py",
            "summary": summary,
            "commands": commands,
        },
        sort_keys=True,
    )
)
'''


def utc_clock() -> str:
    return datetime.now(UTC).strftime("%H:%M:%SZ")


def format_duration(started_at: float) -> str:
    return f"{time.monotonic() - started_at:.1f}s"


def short_path(path_text: str) -> str:
    path = Path(path_text)
    if not path.is_absolute():
        return path_text
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        pass
    try:
        return "../" + str(path.relative_to(REPO_ROOT.parent))
    except ValueError:
        return path_text


def log_event(component: str, message: str) -> None:
    print(f"[{utc_clock()}] [{component}] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect static hardware characteristics from database/analytics nodes."
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "hardware-snapshots",
    )
    parser.add_argument(
        "--groups",
        default=DEFAULT_GROUPS,
        help=(
            "Comma-separated inventory groups to collect. Defaults to DB nodes "
            "plus analytics clients."
        ),
    )
    parser.add_argument(
        "--scope",
        default="database_sweep_global",
        choices=(
            "database_sweep_global",
            "corpus_attempt_global",
            "pressure_batch_global",
        ),
        help="Lifecycle scope in which this static snapshot is collected once.",
    )
    parser.add_argument("--ssh-user", default="root")
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


def load_target_hosts(
    path: Path,
    groups: list[str],
) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    children = data["all"]["children"]
    targets: dict[str, dict[str, Any]] = {}
    for group in groups:
        group_hosts = children.get(group, {}).get("hosts", {})
        for host_name, host_info in group_hosts.items():
            current = targets.setdefault(host_name, {**host_info, "groups": []})
            current["groups"].append(group)
    if not targets:
        raise RuntimeError(f"No hosts found in inventory groups: {', '.join(groups)}")
    return targets


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
    command = [
        *ssh_base(host, user, key_file),
        f"bash -lc {shlex.quote(remote_script)}",
    ]
    for attempt in range(1, attempts + 1):
        try:
            return subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            if error.returncode != 255 or attempt == attempts:
                raise
            log_event(
                "HW",
                (
                    f"transient SSH failure host={host} "
                    f"attempt={attempt}/{attempts}; retrying"
                ),
            )
            time.sleep(retry_delay_seconds)
    raise RuntimeError("unreachable")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def csv_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def node_csv_row(
    *,
    snapshot_id: str,
    out_dir: Path,
    node_name: str,
    host_info: dict[str, Any],
    node_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    summary = payload.get("summary", {})
    cpu = summary.get("cpu", {}) if isinstance(summary.get("cpu"), dict) else {}
    memory = summary.get("memory", {}) if isinstance(summary.get("memory"), dict) else {}
    storage = summary.get("storage", {}) if isinstance(summary.get("storage"), dict) else {}
    return {
        "snapshot_id": snapshot_id,
        "node_name": node_name,
        "groups": csv_text(host_info.get("groups", [])),
        "ansible_host": host_info.get("ansible_host", ""),
        "hostname": summary.get("hostname", ""),
        "kernel": summary.get("kernel", ""),
        "cpu_model": cpu.get("model_name", ""),
        "logical_cpus": cpu.get("logical_cpus", ""),
        "physical_cores": cpu.get("physical_cores", ""),
        "sockets": cpu.get("sockets", ""),
        "cores_per_socket": cpu.get("cores_per_socket", ""),
        "threads_per_core": cpu.get("threads_per_core", ""),
        "cpu_mhz": cpu.get("cpu_mhz", ""),
        "cpu_max_mhz": cpu.get("cpu_max_mhz", ""),
        "hypervisor_vendor": cpu.get("hypervisor_vendor", ""),
        "ram_total_bytes": memory.get("total_bytes", ""),
        "ram_available_bytes": memory.get("available_bytes", ""),
        "ram_speed_values_mt_s": csv_text(memory.get("speed_values_mt_s", [])),
        "ram_speed_source": memory.get("speed_source", ""),
        "disk_count": storage.get("disk_count", ""),
        "disk_total_bytes": storage.get("disk_total_bytes", ""),
        "storage_classes": csv_text(storage.get("storage_classes", [])),
        "root_storage_class": storage.get("root_storage_class", ""),
        "postgres_storage_class": storage.get("postgres_storage_class", ""),
        "summary_file": str((node_dir / "hardware_summary.json").relative_to(out_dir)),
        "raw_file": str((node_dir / "hardware_raw.json").relative_to(out_dir)),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def main() -> int:
    args = parse_args()
    env_values = {**load_shell_env(args.env_file), **os.environ}
    key_value = env_values.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    key_file = Path(key_value).expanduser() if key_value else None
    if key_file is not None and not key_file.exists():
        raise FileNotFoundError(f"SSH private key not found: {key_file}")

    groups = [item.strip() for item in args.groups.split(",") if item.strip()]
    targets = load_target_hosts(args.inventory, groups)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot_id = f"{timestamp}-{args.label}"
    out_dir = (args.out_root / snapshot_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_event(
        "HW",
        (
            f"start snapshot_id={snapshot_id} hosts={len(targets)} "
            f"groups={','.join(groups)}"
        ),
    )
    log_event("HW", f"artifacts -> {short_path(str(out_dir))}")

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    local_artifacts: dict[str, str] = {}
    sorted_targets = sorted(targets.items())
    for node_index, (node_name, host_info) in enumerate(sorted_targets, start=1):
        node_started_at = time.monotonic()
        host = str(host_info["ansible_host"])
        node_dir = out_dir / "nodes" / node_name
        node_dir.mkdir(parents=True, exist_ok=True)
        log_event(
            "HW",
            f"host {node_index}/{len(sorted_targets)} start node={node_name} host={host}",
        )
        result = ssh_run(
            host,
            args.ssh_user,
            key_file,
            f"python3 - <<'PY'\n{REMOTE_COLLECTOR}\nPY",
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            (node_dir / "collector.stdout.log").write_text(result.stdout, encoding="utf-8")
            (node_dir / "collector.stderr.log").write_text(result.stderr, encoding="utf-8")
            errors.append({"node_name": node_name, "error": str(error)})
            log_event(
                "HW",
                (
                    f"host {node_index}/{len(sorted_targets)} failed "
                    f"node={node_name} in {format_duration(node_started_at)}"
                ),
            )
            continue
        if result.stderr.strip():
            (node_dir / "collector.stderr.log").write_text(result.stderr, encoding="utf-8")
        write_json(node_dir / "hardware_raw.json", payload)
        write_json(node_dir / "hardware_summary.json", payload.get("summary", {}))
        local_artifacts[node_name] = str(node_dir.relative_to(out_dir))
        rows.append(
            node_csv_row(
                snapshot_id=snapshot_id,
                out_dir=out_dir,
                node_name=node_name,
                host_info=host_info,
                node_dir=node_dir,
                payload=payload,
            )
        )
        log_event(
            "HW",
            (
                f"host {node_index}/{len(sorted_targets)} done "
                f"node={node_name} in {format_duration(node_started_at)}"
            ),
        )

    fieldnames = [
        "snapshot_id",
        "node_name",
        "groups",
        "ansible_host",
        "hostname",
        "kernel",
        "cpu_model",
        "logical_cpus",
        "physical_cores",
        "sockets",
        "cores_per_socket",
        "threads_per_core",
        "cpu_mhz",
        "cpu_max_mhz",
        "hypervisor_vendor",
        "ram_total_bytes",
        "ram_available_bytes",
        "ram_speed_values_mt_s",
        "ram_speed_source",
        "disk_count",
        "disk_total_bytes",
        "storage_classes",
        "root_storage_class",
        "postgres_storage_class",
        "summary_file",
        "raw_file",
    ]
    write_csv(out_dir / "hardware_nodes.csv", rows, fieldnames)
    write_json(
        out_dir / "hardware_snapshot_manifest.json",
        {
            "snapshot_id": snapshot_id,
            "created_at_utc": timestamp,
            "label": args.label,
            "inventory": str(args.inventory.resolve()),
            "groups": groups,
            "local_artifacts": local_artifacts,
            "collection_contract": {
                "scope": args.scope,
                "frequency": {
                    "database_sweep_global": (
                        "once before dataset/runtime/query loops"
                    ),
                    "corpus_attempt_global": (
                        "once before corpus group/database-sweep loops"
                    ),
                    "pressure_batch_global": (
                        "once before pressure batch segment loops"
                    ),
                }[args.scope],
                "feature_role": "global_hardware_context",
                "per_query_signal": False,
                "commands": [
                    "lscpu --json",
                    "lsblk --json --bytes",
                    "/proc/meminfo",
                    "df/findmnt",
                    "dmidecode when available",
                    "lshw when available",
                ],
            },
            "errors": errors,
        },
    )
    print(str(out_dir), flush=True)
    log_event(
        "HW",
        (
            f"{'completed_with_errors' if errors else 'completed'} "
            f"hosts_ok={len(rows)} hosts_failed={len(errors)} "
            f"artifact -> {short_path(str(out_dir))}"
        ),
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
