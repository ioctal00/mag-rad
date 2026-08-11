#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect one static psql-benchmarks snapshot per DB node."
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "static-snapshots",
    )
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--remote-bench-dir", default="/opt/psql-benchmarks")
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


def load_inventory(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    children = data["all"]["children"]
    db_nodes = children["db_nodes"]["hosts"]
    coordinators = children["coordinators"]["hosts"]
    if not db_nodes:
        raise RuntimeError("No db_nodes found in generated Ansible inventory.")
    if not coordinators:
        raise RuntimeError("No coordinator found in generated Ansible inventory.")
    return db_nodes, sorted(coordinators)[0]


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


def ssh_run(
    host: str,
    user: str,
    key_file: Path | None,
    remote_script: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*ssh_base(host, user, key_file), f"bash -lc {shlex.quote(remote_script)}"],
        text=True,
        capture_output=True,
        check=True,
    )


def parse_run_dir(output: str) -> str:
    for line in reversed(output.splitlines()):
        if line.startswith("Run directory: "):
            return line.split(": ", 1)[1].strip()
        if line.startswith("/"):
            return line.strip()
    raise RuntimeError(f"Unable to parse run directory from output:\n{output}")


def fetch_remote_dir(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    remote_dir: str,
    local_dir: Path,
) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    command = (
        f"tar -C {shlex.quote(str(Path(remote_dir).parent))} "
        f"-czf - {shlex.quote(Path(remote_dir).name)}"
    )
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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    env_values = {**load_shell_env(args.env_file), **os.environ}
    key_value = env_values.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    key_file = Path(key_value).expanduser() if key_value else None
    if key_file is not None and not key_file.exists():
        raise FileNotFoundError(f"SSH private key not found: {key_file}")

    db_nodes, coordinator_name = load_inventory(args.inventory)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot_id = f"{timestamp}-{args.label}"
    out_dir = (args.out_root / snapshot_id).resolve()
    remote_dirs: dict[str, str] = {}

    for host_name, host_info in sorted(db_nodes.items()):
        host = host_info["ansible_host"]
        print(f"Collecting static snapshot on {host_name} ({host})...", flush=True)
        result = ssh_run(
            host,
            args.ssh_user,
            key_file,
            (
                f"cd {shlex.quote(args.remote_bench_dir)} && "
                f"./bin/snapshot-metadata --label {shlex.quote(snapshot_id)}"
            ),
        )
        remote_dirs[host_name] = parse_run_dir(result.stdout)

    for host_name, remote_dir in remote_dirs.items():
        host = db_nodes[host_name]["ansible_host"]
        print(f"Fetching static snapshot from {host_name}...", flush=True)
        fetch_remote_dir(
            host=host,
            user=args.ssh_user,
            key_file=key_file,
            remote_dir=remote_dir,
            local_dir=out_dir / "nodes" / host_name,
        )

    manifest = {
        "snapshot_id": snapshot_id,
        "created_at_utc": timestamp,
        "label": args.label,
        "coordinator": coordinator_name,
        "node_run_dirs": remote_dirs,
        "local_artifacts": {
            host_name: str(
                (out_dir / "nodes" / host_name / Path(remote_dir).name).relative_to(out_dir)
            )
            for host_name, remote_dir in remote_dirs.items()
        },
        "collection_contract": {
            "static_database_metadata_per_sweep": True,
            "per_query_duplicate_static_metadata": False,
        },
    }
    write_json(out_dir / "sweep_static_manifest.json", manifest)
    print(str(out_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
