#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "master-regimes-infra" / "env"
ANSIBLE_WRAPPER = REPO_ROOT / "common-scripts" / "run_ansible.sh"
MAX_ARCHIVE_STEM_CHARS = 120
FDW_TABLES = (
    "events",
    "tenants",
    "users",
    "global_users",
    "mr_joined_events_colocated",
    "mr_joined_events_repartition",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run psql-benchmarks FDW bootstrap on GAC.")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--label", default="gac-fdw-bootstrap")
    parser.add_argument("--region", default="eu")
    parser.add_argument("--target-host", default="")
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--remote-bench-dir", default="/opt/psql-benchmarks")
    parser.add_argument(
        "--fdw-server-option",
        action="append",
        default=[],
        help="postgres_fdw server option as NAME=VALUE, e.g. fetch_size=100.",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "fdw-bootstrap",
    )
    return parser.parse_args()


def key_value_map(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, option_value = value.split("=", 1)
        result[key] = option_value
    return result


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


def load_regional_coordinator(
    path: Path,
    *,
    region: str,
) -> tuple[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    hosts = data["all"]["children"].get("coordinators", {}).get("hosts", {})
    matching = {
        host_name: host_info
        for host_name, host_info in hosts.items()
        if host_name.split("-", 1)[0].lower() == region.lower()
    }
    if not matching:
        raise RuntimeError(f"No coordinator found for logical region: {region}")
    host_name = sorted(matching)[0]
    return host_name, matching[host_name]


def regional_join_views_sql() -> str:
    return """
CREATE OR REPLACE VIEW public.mr_joined_events_colocated AS
SELECT
  e.event_id,
  e.tenant_id,
  e.user_id,
  e.value,
  e.created_at,
  u.user_segment,
  u.user_status
FROM public.events AS e
JOIN public.users AS u
  ON u.tenant_id = e.tenant_id
 AND u.user_id = e.user_id;

CREATE OR REPLACE VIEW public.mr_joined_events_repartition AS
SELECT
  e.event_id,
  e.tenant_id,
  e.user_id,
  e.value,
  e.created_at,
  gu.user_segment,
  gu.user_status
FROM public.events AS e
JOIN public.global_users AS gu
  ON gu.tenant_id = e.tenant_id
 AND gu.user_id = e.user_id;
""".strip()


def prepare_regional_join_views(
    *,
    inventory: Path,
    region: str,
) -> dict[str, Any]:
    host_name, host_info = load_regional_coordinator(inventory, region=region)
    result = run_ansible_shell(
        host_name,
        (
            "sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d app "
            f"-c {shlex.quote(regional_join_views_sql())}"
        ),
        attempts=3,
        retry_delay_seconds=5,
    )
    return {
        "host": host_name,
        "region": region,
        "status": "prepared",
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


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


def run_ansible_shell(
    host_name: str,
    remote_command: str,
    *,
    attempts: int = 1,
    retry_delay_seconds: float = 0,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(ANSIBLE_WRAPPER),
        "ansible",
        host_name,
        "-m",
        "ansible.builtin.shell",
        "-a",
        remote_command,
    ]
    for attempt in range(1, attempts + 1):
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return completed
        print(
            (
                f"Ansible shell failed on {host_name} "
                f"(attempt {attempt}/{attempts}, rc={completed.returncode})."
            ),
            file=sys.stderr,
            flush=True,
        )
        if completed.stdout:
            print(completed.stdout.rstrip(), file=sys.stderr, flush=True)
        if completed.stderr:
            print(completed.stderr.rstrip(), file=sys.stderr, flush=True)
        if attempt < attempts:
            time.sleep(retry_delay_seconds)
    raise subprocess.CalledProcessError(
        completed.returncode,
        command,
        output=completed.stdout,
        stderr=completed.stderr,
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
    raise RuntimeError(f"Unable to parse remote FDW bootstrap run dir from output:\n{output}")


def bounded_archive_stem(value: str) -> str:
    safe_value = "".join(
        character
        if character.isascii()
        and (character.isalnum() or character in {".", "_", "-"})
        else "-"
        for character in value
    ).strip(".-_")
    safe_value = safe_value or "fdw-bootstrap"
    if len(safe_value) <= MAX_ARCHIVE_STEM_CHARS:
        return safe_value

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    prefix_length = MAX_ARCHIVE_STEM_CHARS - len(digest) - 2
    return f"{safe_value[:prefix_length]}--{digest}"


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
    archive_stem = bounded_archive_stem(archive_name)
    remote_archive = f"/tmp/{archive_stem}.tar.gz"
    local_archive = local_dir / f"{archive_stem}.tar.gz"
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
    regional_join_views = prepare_regional_join_views(
        inventory=args.inventory,
        region=args.region,
    )
    remote_command = (
        f"cd {shlex.quote(args.remote_bench_dir)} && "
        f"./bin/fdw-bootstrap --label {shlex.quote(args.label)} "
        f"--fdw-region {shlex.quote(args.region)}"
        + "".join(
            f" --fdw-table {shlex.quote(table_name)}"
            for table_name in FDW_TABLES
        )
        + "".join(
            f" --fdw-server-option {shlex.quote(value)}"
            for value in args.fdw_server_option
        )
    )
    print(f"Running FDW bootstrap on {host_name} ({host})...", flush=True)
    result = run_ansible_shell(
        host_name,
        remote_command,
        attempts=3,
        retry_delay_seconds=5,
    )
    remote_run_dir = parse_run_dir(result.stdout)
    fetch_remote_dir(
        host_name=host_name,
        remote_dir=remote_run_dir,
        local_dir=out_dir / "nodes" / host_name,
        archive_name=run_id,
    )
    write_json(
        out_dir / "fdw_bootstrap_manifest.json",
        {
            "run_id": run_id,
            "created_at_utc": timestamp,
            "target_host": host_name,
            "region": args.region,
            "fdw_server_options": key_value_map(args.fdw_server_option),
            "regional_join_views": regional_join_views,
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
