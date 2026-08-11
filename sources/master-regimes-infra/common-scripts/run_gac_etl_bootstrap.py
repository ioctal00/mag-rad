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
ANSIBLE_WRAPPER = REPO_ROOT / "common-scripts" / "run_ansible.sh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run psql-benchmarks GAC ETL bootstrap.")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--label", default="gac-etl-bootstrap")
    parser.add_argument("--region", default="eu")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--timeout-grace-seconds", type=int, default=30)
    parser.add_argument("--target-host", default="")
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--remote-bench-dir", default="/opt/psql-benchmarks")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "gac-etl-bootstrap",
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


def load_analytics_host(path: Path, target_host: str) -> tuple[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    hosts = data["all"]["children"].get("analytics_clients", {}).get("hosts", {})
    if not hosts:
        raise RuntimeError("No analytics_clients hosts found in generated inventory.")
    if target_host:
        if target_host not in hosts:
            raise RuntimeError(f"Analytics host not found: {target_host}")
        return target_host, hosts[target_host]
    host_name = sorted(hosts)[0]
    return host_name, hosts[host_name]


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


def run_ansible_shell(host_name: str, remote_command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(ANSIBLE_WRAPPER),
            "ansible",
            host_name,
            "-m",
            "ansible.builtin.shell",
            "-a",
            remote_command,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def run_ansible_fetch(host_name: str, *, remote_path: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(ANSIBLE_WRAPPER),
            "ansible",
            host_name,
            "-m",
            "ansible.builtin.fetch",
            "-a",
            f"src={remote_path} dest={local_path} flat=true",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def parse_run_dir(output: str) -> str:
    for line in reversed(output.splitlines()):
        if line.startswith("Run directory: "):
            return line.split(": ", 1)[1].strip()
        if line.startswith("/"):
            return line.strip()
    raise RuntimeError(f"Unable to parse remote GAC ETL bootstrap run dir from output:\n{output}")


def fetch_remote_dir(
    *,
    host_name: str,
    remote_dir: str,
    local_dir: Path,
    archive_name: str,
) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    remote_parent = shlex.quote(str(Path(remote_dir).parent))
    remote_name = shlex.quote(Path(remote_dir).name)
    remote_archive = f"/tmp/{archive_name}.tar.gz"
    local_archive = local_dir / f"{archive_name}.tar.gz"
    run_ansible_shell(
        host_name,
        f"tar -C {remote_parent} -czf {shlex.quote(remote_archive)} {remote_name}",
    )
    run_ansible_fetch(host_name, remote_path=remote_archive, local_path=local_archive)
    subprocess.run(
        ["tar", "-xzf", str(local_archive), "-C", str(local_dir)],
        check=True,
        capture_output=True,
    )
    run_ansible_shell(host_name, f"rm -f {shlex.quote(remote_archive)}")
    local_archive.unlink(missing_ok=True)


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

    host_name, host_info = load_analytics_host(args.inventory, args.target_host)
    host = host_info["ansible_host"]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{args.label}-{args.region}"
    out_dir = (args.out_root / run_id).resolve()
    bench_command = (
        f"cd {shlex.quote(args.remote_bench_dir)} && "
        f"./bin/gac-etl-bootstrap --label {shlex.quote(args.label)} "
        f"--etl-region {shlex.quote(args.region)} "
        f"--etl-lookback-days {args.lookback_days}"
    )
    if args.timeout_seconds > 0:
        remote_command = (
            f"timeout --kill-after={int(args.timeout_grace_seconds)}s "
            f"{int(args.timeout_seconds)}s sh -lc {shlex.quote(bench_command)}"
        )
    else:
        remote_command = bench_command
    print(f"Running GAC ETL bootstrap on {host_name} ({host})...", flush=True)
    result = run_ansible_shell(host_name, remote_command)
    remote_run_dir = parse_run_dir(result.stdout)
    fetch_remote_dir(
        host_name=host_name,
        remote_dir=remote_run_dir,
        local_dir=out_dir / "nodes" / host_name,
        archive_name=run_id,
    )
    write_json(
        out_dir / "gac_etl_bootstrap_manifest.json",
        {
            "run_id": run_id,
            "created_at_utc": timestamp,
            "target_host": host_name,
            "region": args.region,
            "lookback_days": args.lookback_days,
            "timeout_seconds": args.timeout_seconds,
            "timeout_grace_seconds": args.timeout_grace_seconds,
            "remote_run_dir": remote_run_dir,
            "local_artifacts": str((out_dir / "nodes" / host_name).relative_to(out_dir)),
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )
    print(str(out_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
