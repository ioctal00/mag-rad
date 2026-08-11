#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "ansible" / "inventory" / "generated.json"
ANSIBLE_WRAPPER = REPO_ROOT / "common-scripts" / "run_ansible.sh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe effective runtime context on the live analytics/GAC node "
            "without changing database or network state."
        )
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--target-host", default="")
    parser.add_argument("--database", default="analytics")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "runtime-context-probes",
    )
    return parser.parse_args()


def utc_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def load_analytics_host(path: Path, target_host: str) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    hosts = data["all"]["children"].get("analytics_clients", {}).get("hosts", {})
    if not hosts:
        raise RuntimeError("No analytics_clients hosts found in generated inventory.")
    if target_host:
        if target_host not in hosts:
            raise RuntimeError(f"Analytics host not found: {target_host}")
        return target_host
    return sorted(hosts)[0]


def ansible_shell(host_name: str, command: str) -> str:
    result = subprocess.run(
        [
            str(ANSIBLE_WRAPPER),
            "ansible",
            host_name,
            "-m",
            "ansible.builtin.shell",
            "-a",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def parse_ansible_stdout(stdout: str) -> list[str]:
    lines: list[str] = []
    capture = False
    for raw in stdout.splitlines():
        line = raw.rstrip("\n")
        if ">>" in line:
            capture = True
            after = line.split(">>", 1)[1].strip()
            if after:
                lines.append(after)
            continue
        if capture:
            if line.startswith("PLAY RECAP") or line.startswith("TASK "):
                break
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return lines


def psql_command(database: str, sql: str) -> str:
    escaped_sql = sql.replace("'", "'\"'\"'")
    return (
        f"sudo -u postgres psql -X -A -t -F '|' -d {database} "
        f"-c '{escaped_sql}'"
    )


def parse_server_options(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        if "|" not in line:
            continue
        server, raw_options = line.split("|", 1)
        options: dict[str, str] = {}
        for option in raw_options.split(","):
            if "=" not in option:
                continue
            key, value = option.split("=", 1)
            if "password" in key.lower():
                continue
            options[key] = value
        rows.append({"server": server, "options": options})
    return rows


def main() -> int:
    args = parse_args()
    host_name = load_analytics_host(args.inventory, args.target_host)
    run_id = utc_id()
    out_dir = (args.out_root / f"{run_id}-live-runtime-context").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    work_mem_stdout = ansible_shell(
        host_name,
        psql_command(args.database, "select current_setting('work_mem');"),
    )
    fdw_stdout = ansible_shell(
        host_name,
        psql_command(
            args.database,
            (
                "select srvname, coalesce(array_to_string(srvoptions, ','), '') "
                "from pg_foreign_server order by srvname;"
            ),
        ),
    )
    tc_stdout = ansible_shell(host_name, "tc qdisc show || true")

    work_mem_lines = parse_ansible_stdout(work_mem_stdout)
    fdw_lines = parse_ansible_stdout(fdw_stdout)
    tc_lines = parse_ansible_stdout(tc_stdout)

    payload = {
        "run_id": run_id,
        "created_at_utc": run_id,
        "target_host": host_name,
        "database": args.database,
        "effective_work_mem": work_mem_lines[0] if work_mem_lines else "",
        "fdw_servers": parse_server_options(fdw_lines),
        "tc_qdisc": tc_lines,
        "notes": [
            "This probe is read-only and does not apply runtime interventions.",
            "FDW user mappings are intentionally not queried because they can contain secrets.",
        ],
    }
    (out_dir / "runtime_context_probe.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
