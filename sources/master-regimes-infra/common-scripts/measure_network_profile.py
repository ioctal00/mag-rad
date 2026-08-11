#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure route, RTT and achieved throughput for regional GAC ingress."
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--profile-json", default="{}")
    parser.add_argument("--target-host", default="")
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--iperf-seconds", type=int, default=5)
    return parser.parse_args()


def load_shell_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = shlex.split(line)
        assignment = parts[1] if parts[0] == "export" and len(parts) >= 2 else parts[0]
        if "=" in assignment:
            key, value = assignment.split("=", 1)
            values[key] = value
    return values


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
        "ServerAliveCountMax=2",
    ]
    if key_file is not None:
        command.extend(["-i", str(key_file), "-o", "IdentitiesOnly=yes"])
    command.append(f"{user}@{host}")
    return command


def ssh_run(
    host: str,
    user: str,
    key_file: Path | None,
    script: str,
    *,
    timeout_seconds: int = 90,
) -> subprocess.CompletedProcess[str]:
    command = [*ssh_base(host, user, key_file), f"bash -lc {shlex.quote(script)}"]
    try:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(
            command,
            124,
            stdout,
            f"{stderr}\nSSH measurement timed out after {timeout_seconds}s.\n",
        )


def group_hosts(inventory: dict[str, Any], group: str) -> dict[str, dict[str, Any]]:
    value = (
        inventory.get("all", {})
        .get("children", {})
        .get(group, {})
        .get("hosts", {})
    )
    return value if isinstance(value, dict) else {}


def parse_ping_context(value: str) -> dict[str, Any]:
    times = [
        float(item)
        for item in re.findall(r"time[=<]([0-9.]+)\s*ms", value)
    ]
    loss_match = re.search(r"([0-9.]+)%\s+packet loss", value)
    rtt_match = re.search(
        r"=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\s*ms",
        value,
    )
    return {
        "rtt_min_ms": float(rtt_match.group(1)) if rtt_match else "",
        "rtt_avg_ms": float(rtt_match.group(2)) if rtt_match else "",
        "rtt_max_ms": float(rtt_match.group(3)) if rtt_match else "",
        "rtt_mdev_ms": float(rtt_match.group(4)) if rtt_match else "",
        "rtt_median_ms": statistics.median(times) if times else "",
        "packet_loss_percent": float(loss_match.group(1)) if loss_match else "",
        "packets_received": len(times),
    }


def main() -> int:
    args = parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    profile = json.loads(args.profile_json)
    if not isinstance(profile, dict):
        raise ValueError("--profile-json must decode to an object")
    analytics_hosts = group_hosts(inventory, "analytics_clients")
    if args.target_host:
        analytics_name = args.target_host
    else:
        analytics_name = sorted(analytics_hosts)[0]
    analytics = analytics_hosts[analytics_name]
    analytics_ip = str(analytics.get("private_ip", ""))
    if not analytics_ip:
        raise RuntimeError(f"Analytics host {analytics_name} has no private_ip")

    regions = {str(value) for value in profile.get("target_region_ids", [])}
    coordinators = {
        name: host
        for name, host in group_hosts(inventory, "coordinators").items()
        if not regions or str(host.get("logical_region", "")) in regions
    }
    env = {**load_shell_env(args.env_file), **os.environ}
    key_text = env.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    key_file = Path(key_text).expanduser() if key_text else None
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (args.out_root / f"{timestamp}-{args.label}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    measurements: dict[str, Any] = {}
    for index, (name, source) in enumerate(sorted(coordinators.items())):
        port = 5210 + index
        pid_file = f"/tmp/master-regimes-iperf3-{port}.pid"
        server = ssh_run(
            str(analytics["ansible_host"]),
            args.ssh_user,
            key_file,
            (
                f"if test -s {shlex.quote(pid_file)}; then "
                f"kill \"$(cat {shlex.quote(pid_file)})\" 2>/dev/null || true; "
                "fi; "
                f"nohup iperf3 -s -1 -B {shlex.quote(analytics_ip)} -p {port} "
                f">/tmp/{args.label}-{port}.iperf-server.log 2>&1 "
                f"& echo $! > {shlex.quote(pid_file)}"
            ),
            timeout_seconds=20,
        )
        time.sleep(0.5)
        source_result = ssh_run(
            str(source["ansible_host"]),
            args.ssh_user,
            key_file,
            (
                "set -o pipefail; "
                f"ip route get {shlex.quote(analytics_ip)}; "
                "printf '\\n---PING---\\n'; "
                f"ping -c 10 -W 3 {shlex.quote(analytics_ip)}; "
                "printf '\\n---IPERF---\\n'; "
                f"iperf3 -c {shlex.quote(analytics_ip)} -p {port} "
                f"-t {max(1, args.iperf_seconds)} "
                "--connect-timeout 5000 -J"
            ),
            timeout_seconds=max(60, args.iperf_seconds + 45),
        )
        stdout = source_result.stdout
        route_and_ping_stdout = stdout.split("---IPERF---", 1)[0].strip()
        iperf_raw = stdout.split("---IPERF---", 1)[-1].strip()
        try:
            iperf = json.loads(iperf_raw)
        except json.JSONDecodeError:
            iperf = {}
        end = iperf.get("end", {}) if isinstance(iperf, dict) else {}
        sent = end.get("sum_sent", {}) if isinstance(end, dict) else {}
        received = end.get("sum_received", {}) if isinstance(end, dict) else {}
        measurements[name] = {
            "edge_id": f"{source.get('logical_region', '')}->{analytics_name}",
            "source_cluster_id": source.get("logical_region", ""),
            "logical_region": source.get("logical_region", ""),
            "source_host": source.get("ansible_host", ""),
            "source_private_ip": source.get("private_ip", ""),
            "destination_gac_id": analytics_name,
            "analytics_node": analytics_name,
            "analytics_private_ip": analytics_ip,
            "server_start_returncode": server.returncode,
            "client_returncode": source_result.returncode,
            "route_and_ping_stdout": route_and_ping_stdout,
            "rtt_context": parse_ping_context(route_and_ping_stdout),
            "stderr": source_result.stderr,
            "iperf_json": iperf,
            "achieved_sender_bits_per_second": sent.get("bits_per_second", ""),
            "achieved_receiver_bits_per_second": received.get("bits_per_second", ""),
            "retransmits": sent.get("retransmits", ""),
            "measurement_quality": "experimental_profile_calibration",
        }

    status = (
        "completed"
        if measurements
        and all(row["client_returncode"] == 0 for row in measurements.values())
        else "failed"
    )
    manifest = {
        "contract_version": "network-profile-measurement-v1",
        "created_at_utc": timestamp,
        "status": status,
        "profile": profile,
        "measurement_scope": "once_per_dataset_runtime_network_profile",
        "iperf_seconds": args.iperf_seconds,
        "measurements": measurements,
    }
    (out_dir / "network_profile_measurement.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(out_dir, flush=True)
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
