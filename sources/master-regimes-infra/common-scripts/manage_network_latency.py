#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
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
        description="Apply/reset targeted tc netem latency from analytics to region coordinators."
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


def load_inventory(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON inventory object in {path}")
    return value


def child_hosts(inventory: dict[str, Any], group: str) -> dict[str, dict[str, Any]]:
    children = inventory.get("all", {}).get("children", {})
    group_value = children.get(group, {}) if isinstance(children, dict) else {}
    hosts = group_value.get("hosts", {}) if isinstance(group_value, dict) else {}
    return hosts if isinstance(hosts, dict) else {}


def analytics_host(
    inventory: dict[str, Any],
    *,
    target_host: str,
) -> tuple[str, dict[str, Any]]:
    analytics = child_hosts(inventory, "analytics_clients")
    if target_host:
        if target_host not in analytics:
            available = ", ".join(sorted(analytics))
            raise RuntimeError(
                f"Analytics target {target_host!r} not found. Available: {available}"
            )
        host = analytics[target_host]
        return target_host, host if isinstance(host, dict) else {}
    if not analytics:
        raise RuntimeError("No analytics_clients host found in generated inventory.")
    name = sorted(analytics)[0]
    host = analytics[name]
    return name, host if isinstance(host, dict) else {}


def coordinator_targets(
    inventory: dict[str, Any],
    *,
    target_region_ids: list[str],
) -> list[dict[str, str]]:
    coordinators = child_hosts(inventory, "coordinators")
    targets: list[dict[str, str]] = []
    for name, host in sorted(coordinators.items()):
        if not isinstance(host, dict):
            continue
        logical_region = str(host.get("logical_region", ""))
        if target_region_ids and logical_region not in target_region_ids:
            continue
        private_ip = str(host.get("private_ip", ""))
        if not private_ip:
            continue
        targets.append(
            {
                "node_name": name,
                "logical_region": logical_region,
                "private_ip": private_ip,
                "ansible_host": str(host.get("ansible_host", "")),
            }
        )
    if not targets:
        raise RuntimeError(
            "No coordinator private IP targets found for regions: "
            + ",".join(target_region_ids)
        )
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
    ]
    if key_file is not None:
        command.extend(["-i", str(key_file), "-o", "IdentitiesOnly=yes"])
    command.append(f"{user}@{host}")
    return command


def ssh_run_json(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    remote_script: str,
) -> dict[str, Any]:
    completed = subprocess.run(
        [*ssh_base(host, user, key_file), f"python3 - <<'PY'\n{remote_script}\nPY"],
        text=True,
        capture_output=True,
        check=False,
    )
    payload: dict[str, Any]
    try:
        payload = json.loads(completed.stdout.strip() or "{}")
        if not isinstance(payload, dict):
            payload = {"raw_stdout": completed.stdout}
    except json.JSONDecodeError:
        payload = {"raw_stdout": completed.stdout}
    payload["ssh_returncode"] = completed.returncode
    payload["ssh_stderr"] = completed.stderr
    if completed.returncode != 0 and "status" not in payload:
        payload["status"] = "failed"
    return payload


def remote_python_script(
    *,
    action: str,
    profile: dict[str, Any],
    targets: list[dict[str, str]],
) -> str:
    delay_ms = int(profile.get("configured_delay_ms", 0) or 0)
    jitter_ms = int(profile.get("configured_jitter_ms", 0) or 0)
    loss_percent = float(profile.get("configured_loss_percent", 0) or 0)
    return f"""
import json
import re
import subprocess
from datetime import datetime, timezone

ACTION = {action!r}
PROFILE = {json.dumps(profile, sort_keys=True)!r}
TARGETS = {json.dumps(targets, sort_keys=True)!r}
DELAY_MS = {delay_ms!r}
JITTER_MS = {jitter_ms!r}
LOSS_PERCENT = {loss_percent!r}

profile = json.loads(PROFILE)
targets = json.loads(TARGETS)

def run(cmd, check=False):
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError("command failed: " + " ".join(cmd) + "\\n" + completed.stderr)
    return {{
        "cmd": cmd,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }}

def route_dev(ip):
    result = run(["ip", "route", "get", ip])
    match = re.search(r"\\bdev\\s+(\\S+)", result["stdout"])
    return match.group(1) if match else ""

def ping_summary(ip):
    result = run(["ping", "-c", "3", "-W", "2", ip])
    summary = {{"returncode": result["returncode"], "stdout": result["stdout"], "stderr": result["stderr"]}}
    match = re.search(r"rtt min/avg/max/mdev = ([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)", result["stdout"])
    if match:
        summary.update({{
            "rtt_min_ms": float(match.group(1)),
            "rtt_avg_ms": float(match.group(2)),
            "rtt_max_ms": float(match.group(3)),
            "rtt_mdev_ms": float(match.group(4)),
        }})
    return summary

route_rows = []
devices = {{}}
for target in targets:
    ip = target["private_ip"]
    dev = route_dev(ip)
    route_rows.append({{**target, "device": dev, "ip_route_get": run(["ip", "route", "get", ip])}})
    if dev:
        devices.setdefault(dev, []).append(target)

before = {{}}
for dev in sorted(devices):
    before[dev] = run(["tc", "-s", "qdisc", "show", "dev", dev])

ping_before = {{target["private_ip"]: ping_summary(target["private_ip"]) for target in targets}}
actions = []
status = "ok"
error = ""
try:
    if ACTION in ("apply", "reset"):
        for dev, dev_targets in sorted(devices.items()):
            del_result = run(["tc", "qdisc", "del", "dev", dev, "root"])
            actions.append({{"device": dev, "action": "delete_root", **del_result}})
            should_apply_delay = ACTION == "apply" and (DELAY_MS > 0 or JITTER_MS > 0 or LOSS_PERCENT > 0)
            if should_apply_delay:
                add_prio = run(["tc", "qdisc", "add", "dev", dev, "root", "handle", "1:", "prio", "bands", "4"], check=True)
                actions.append({{"device": dev, "action": "add_prio", **add_prio}})
                netem_args = ["tc", "qdisc", "add", "dev", dev, "parent", "1:3", "handle", "30:", "netem"]
                if DELAY_MS > 0 or JITTER_MS > 0:
                    netem_args.extend(["delay", f"{{DELAY_MS}}ms"])
                    if JITTER_MS > 0:
                        netem_args.append(f"{{JITTER_MS}}ms")
                if LOSS_PERCENT > 0:
                    netem_args.extend(["loss", f"{{LOSS_PERCENT}}%"])
                add_netem = run(netem_args, check=True)
                actions.append({{"device": dev, "action": "add_netem", **add_netem}})
                for target in dev_targets:
                    add_filter = run([
                        "tc", "filter", "add", "dev", dev,
                        "protocol", "ip", "parent", "1:0", "prio", "3",
                        "u32", "match", "ip", "dst", target["private_ip"] + "/32",
                        "flowid", "1:3",
                    ], check=True)
                    actions.append({{"device": dev, "target": target, "action": "add_filter", **add_filter}})
except Exception as exc:
    status = "failed"
    error = str(exc)

after = {{}}
for dev in sorted(devices):
    after[dev] = run(["tc", "-s", "qdisc", "show", "dev", dev])

ping_after = {{target["private_ip"]: ping_summary(target["private_ip"]) for target in targets}}

print(json.dumps({{
    "status": status,
    "error": error,
    "action": ACTION,
    "created_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    "profile": profile,
    "targets": targets,
    "routes": route_rows,
    "devices": sorted(devices),
    "qdisc_before": before,
    "qdisc_after": after,
    "ping_before": ping_before,
    "ping_after": ping_after,
    "actions": actions,
}}, indent=2, sort_keys=True))
"""


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    profile = json.loads(args.profile_json or "{}")
    if not isinstance(profile, dict):
        raise ValueError("--profile-json must decode to a JSON object")
    profile_id = str(profile.get("id", "network-profile"))
    enabled = bool(profile.get("enabled", False))
    timestamp = utc_timestamp()
    label = args.label or f"{profile_id}-{args.action}"
    out_dir = (args.out_dir / f"{timestamp}-{label}").resolve()
    env = load_shell_env(args.env_file)
    key_file_text = env.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE") or os.environ.get(
        "MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", ""
    )
    key_file = Path(key_file_text).expanduser() if key_file_text else None
    inventory = load_inventory(args.inventory)
    analytics_name, analytics = analytics_host(inventory, target_host=args.target_host)
    target_regions = [str(item) for item in profile.get("target_region_ids", [])]
    targets = coordinator_targets(inventory, target_region_ids=target_regions)

    manifest: dict[str, Any] = {
        "network_intervention_id": out_dir.name,
        "created_at_utc": timestamp,
        "action": args.action,
        "status": "skipped" if not enabled else "running",
        "network_profile_id": profile_id,
        "network_profile": profile,
        "analytics_node": analytics_name,
        "analytics_public_host": str(analytics.get("ansible_host", "")),
        "target_region_ids": target_regions,
        "target_coordinators": targets,
        "configured_delay_ms": profile.get("configured_delay_ms", ""),
        "configured_jitter_ms": profile.get("configured_jitter_ms", ""),
        "configured_loss_percent": profile.get("configured_loss_percent", ""),
        "scope": profile.get("scope", ""),
    }
    if not enabled and args.action == "apply":
        write_json(out_dir / "network_intervention_manifest.json", manifest)
        print(str(out_dir), flush=True)
        return 0

    remote_result = ssh_run_json(
        host=str(analytics["ansible_host"]),
        user=args.ssh_user,
        key_file=key_file,
        remote_script=remote_python_script(
            action=args.action,
            profile=profile,
            targets=targets,
        ),
    )
    manifest["status"] = str(remote_result.get("status", "failed"))
    manifest["remote_result"] = remote_result
    write_json(out_dir / "network_intervention_manifest.json", manifest)
    print(str(out_dir), flush=True)
    return 0 if manifest["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
