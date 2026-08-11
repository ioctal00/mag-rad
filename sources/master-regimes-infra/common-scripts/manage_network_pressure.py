#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply/reset targeted regional-to-GAC tc network pressure."
    )
    parser.add_argument("--action", choices=("apply", "reset", "status"), required=True)
    parser.add_argument("--profile-json", default="{}")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--target-host", default="")
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
        parts = shlex.split(line)
        assignment = parts[1] if parts[0] == "export" and len(parts) >= 2 else parts[0]
        if "=" in assignment:
            key, value = assignment.split("=", 1)
            values[key] = value
    return values


def load_inventory(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected inventory object in {path}")
    return value


def group_hosts(inventory: dict[str, Any], group: str) -> dict[str, dict[str, Any]]:
    value = (
        inventory.get("all", {})
        .get("children", {})
        .get(group, {})
        .get("hosts", {})
    )
    return value if isinstance(value, dict) else {}


def selected_analytics(
    inventory: dict[str, Any], target_host: str
) -> tuple[str, dict[str, Any]]:
    hosts = group_hosts(inventory, "analytics_clients")
    if target_host:
        if target_host not in hosts:
            raise RuntimeError(f"Unknown analytics host {target_host}")
        return target_host, hosts[target_host]
    if not hosts:
        raise RuntimeError("No analytics_clients host in inventory")
    name = sorted(hosts)[0]
    return name, hosts[name]


def ssh_base(host: str, user: str, key_file: Path | None) -> list[str]:
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


def remote_script(
    *,
    action: str,
    target_ip: str,
    delay_ms: int,
    jitter_ms: int,
    loss_percent: float,
    bandwidth_mbit: float,
) -> str:
    return f"""
import json
import re
import subprocess
from datetime import datetime, timezone

ACTION = {action!r}
TARGET_IP = {target_ip!r}
DELAY_MS = {delay_ms!r}
JITTER_MS = {jitter_ms!r}
LOSS_PERCENT = {loss_percent!r}
BANDWIDTH_MBIT = {bandwidth_mbit!r}

def run(command):
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    return {{
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }}

route = run(["ip", "route", "get", TARGET_IP])
match = re.search(r"\\bdev\\s+(\\S+)", route["stdout"])
device = match.group(1) if match else ""
before = run(["tc", "-s", "qdisc", "show", "dev", device]) if device else {{}}
ping_before = run(["ping", "-c", "3", "-W", "2", TARGET_IP])
actions = []
status = "ok"
error = ""
try:
    if not device:
        raise RuntimeError("Unable to resolve route device")
    if ACTION in ("apply", "reset"):
        actions.append(run(["tc", "qdisc", "del", "dev", device, "root"]))
    active = (
        ACTION == "apply"
        and (DELAY_MS > 0 or JITTER_MS > 0 or LOSS_PERCENT > 0 or BANDWIDTH_MBIT > 0)
    )
    if active:
        result = run(
            ["tc", "qdisc", "add", "dev", device, "root", "handle", "1:", "prio", "bands", "4"]
        )
        actions.append(result)
        if result["returncode"] != 0:
            raise RuntimeError(result["stderr"])
        netem = [
            "tc", "qdisc", "add", "dev", device,
            "parent", "1:3", "handle", "30:", "netem",
        ]
        if DELAY_MS > 0 or JITTER_MS > 0:
            netem.extend(["delay", f"{{DELAY_MS}}ms"])
            if JITTER_MS > 0:
                netem.append(f"{{JITTER_MS}}ms")
        if LOSS_PERCENT > 0:
            netem.extend(["loss", f"{{LOSS_PERCENT}}%"])
        if BANDWIDTH_MBIT > 0:
            netem.extend(["rate", f"{{BANDWIDTH_MBIT}}mbit"])
        result = run(netem)
        actions.append(result)
        if result["returncode"] != 0:
            raise RuntimeError(result["stderr"])
        result = run([
            "tc", "filter", "add", "dev", device,
            "protocol", "ip", "parent", "1:0", "prio", "3",
            "u32", "match", "ip", "dst", TARGET_IP + "/32",
            "flowid", "1:3",
        ])
        actions.append(result)
        if result["returncode"] != 0:
            raise RuntimeError(result["stderr"])
except Exception as exc:
    status = "failed"
    error = str(exc)

after = run(["tc", "-s", "qdisc", "show", "dev", device]) if device else {{}}
ping_after = run(["ping", "-c", "3", "-W", "2", TARGET_IP])
print(json.dumps({{
    "status": status,
    "error": error,
    "action": ACTION,
    "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    "target_ip": TARGET_IP,
    "device": device,
    "route": route,
    "qdisc_before": before,
    "qdisc_after": after,
    "ping_before": ping_before,
    "ping_after": ping_after,
    "actions": actions,
}}, indent=2, sort_keys=True))
"""


def run_remote(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    script: str,
    attempts: int = 3,
    retry_delay_seconds: float = 2.0,
) -> dict[str, Any]:
    command = [*ssh_base(host, user, key_file), f"python3 - <<'PY'\n{script}\nPY"]
    payload: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            payload = json.loads(result.stdout.strip() or "{}")
        except json.JSONDecodeError:
            payload = {"status": "failed", "raw_stdout": result.stdout}
        payload["ssh_returncode"] = result.returncode
        payload["ssh_stderr"] = result.stderr
        payload["ssh_attempt_count"] = attempt
        if result.returncode == 0:
            return payload
        payload["status"] = "failed"
        if result.returncode != 255 or attempt == attempts:
            return payload
        time.sleep(retry_delay_seconds * attempt)
    return payload


def main() -> int:
    args = parse_args()
    profile = json.loads(args.profile_json)
    if not isinstance(profile, dict):
        raise ValueError("--profile-json must decode to an object")
    if str(profile.get("scope", "")) != "region_egress_to_analytics":
        raise ValueError("manage_network_pressure requires scope=region_egress_to_analytics")

    inventory = load_inventory(args.inventory)
    analytics_name, analytics = selected_analytics(inventory, args.target_host)
    target_ip = str(analytics.get("private_ip", ""))
    if not target_ip:
        raise RuntimeError(f"Analytics host {analytics_name} has no private_ip")
    target_regions = {str(value) for value in profile.get("target_region_ids", [])}
    coordinators = group_hosts(inventory, "coordinators")
    sources = {
        name: host
        for name, host in coordinators.items()
        if not target_regions or str(host.get("logical_region", "")) in target_regions
    }
    if not sources:
        raise RuntimeError("No regional coordinator source hosts selected")

    env = load_shell_env(args.env_file)
    key_text = env.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE") or os.environ.get(
        "MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", ""
    )
    key_file = Path(key_text).expanduser() if key_text else None
    timestamp = utc_timestamp()
    profile_id = str(profile.get("id", "network-pressure"))
    out_dir = (
        args.out_dir / f"{timestamp}-{args.label or profile_id + '-' + args.action}"
    ).resolve()
    results: dict[str, Any] = {}
    for name, source in sorted(sources.items()):
        results[name] = run_remote(
            host=str(source["ansible_host"]),
            user=args.ssh_user,
            key_file=key_file,
            script=remote_script(
                action=args.action,
                target_ip=target_ip,
                delay_ms=int(profile.get("configured_delay_ms", 0) or 0),
                jitter_ms=int(profile.get("configured_jitter_ms", 0) or 0),
                loss_percent=float(profile.get("configured_loss_percent", 0) or 0),
                bandwidth_mbit=float(profile.get("configured_bandwidth_mbit", 0) or 0),
            ),
        )
    status = "ok" if all(row.get("status") == "ok" for row in results.values()) else "failed"
    manifest = {
        "network_intervention_id": out_dir.name,
        "created_at_utc": timestamp,
        "action": args.action,
        "status": status,
        "network_profile_id": profile_id,
        "network_profile": profile,
        "scope": profile.get("scope", ""),
        "analytics_node": analytics_name,
        "analytics_private_ip": target_ip,
        "source_coordinators": sorted(sources),
        "configured_delay_ms": profile.get("configured_delay_ms", 0),
        "configured_jitter_ms": profile.get("configured_jitter_ms", 0),
        "configured_loss_percent": profile.get("configured_loss_percent", 0),
        "configured_bandwidth_mbit": profile.get("configured_bandwidth_mbit", 0),
        "remote_results": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "network_intervention_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(out_dir, flush=True)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
