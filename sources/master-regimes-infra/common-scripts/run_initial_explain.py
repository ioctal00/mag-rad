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
DATAGEN_KEYS = (
    "DATAGEN_REGION",
    "DATAGEN_TENANT_START",
    "DATAGEN_TENANT_END",
    "DATAGEN_OUTPUT_DIR",
    "DATAGEN_RANDOM_SEED",
    "DATAGEN_EVENTS_PER_TENANT",
    "DATAGEN_USERS_PER_TENANT",
    "DATAGEN_GLOBAL_USERS_PER_TENANT",
    "DATAGEN_ENABLE_GLOBAL_USERS",
    "DATAGEN_LOOKBACK_DAYS",
    "DATAGEN_PROGRESS_EVERY_TENANTS",
    "DATAGEN_LOAD_METHOD",
    "DATAGEN_SQL_BATCH_TENANTS",
    "DATAGEN_DISTRIBUTION",
    "DATAGEN_HOT_TENANT_PCT",
    "DATAGEN_HOT_EVENT_PCT",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load a minimal remote citus-datagen dataset and collect EXPLAIN JSON."
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--sql-file", type=Path, required=True)
    parser.add_argument("--label", default="minimal-a1")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "initial-explain",
    )
    parser.add_argument("--db-name", default="app")
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--remote-datagen-dir", default="/opt/citus-datagen")
    parser.add_argument("--tenant-start", type=int, default=1)
    parser.add_argument("--tenant-end", type=int, default=20)
    parser.add_argument("--events-per-tenant", type=int, default=100)
    parser.add_argument("--users-per-tenant", type=int, default=20)
    parser.add_argument("--global-users-per-tenant", type=int, default=20)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--load-method", choices=("sql", "csv", "copy_pipe"), default="sql")
    parser.add_argument("--distribution", choices=("uniform", "hot_tenants"), default="uniform")
    parser.add_argument(
        "--no-citus-explain-all-tasks",
        action="store_true",
        help="Do not set citus.explain_all_tasks=on for EXPLAIN collection.",
    )
    parser.add_argument("--var", action="append", default=[], help="psql variable as name=value")
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
        if parts[0] == "export" and len(parts) >= 2:
            assignment = parts[1]
        else:
            assignment = parts[0]
        if "=" not in assignment:
            continue
        key, value = assignment.split("=", 1)
        values[key] = value
    return values


def resolve_sql_path(path: Path) -> Path:
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([REPO_ROOT / path, REPO_ROOT.parent / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"SQL file not found: {path}")


def coordinator_from_inventory(path: Path) -> tuple[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    hosts = data["all"]["children"]["coordinators"]["hosts"]
    if not hosts:
        raise RuntimeError("No coordinator host found in generated Ansible inventory.")
    name = sorted(hosts)[0]
    return name, hosts[name]


def run_command(
    command: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


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
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return run_command(
        [*ssh_base(host, user, key_file), f"bash -lc {shlex.quote(remote_script)}"],
        input_text=input_text,
    )


def psql_var_args(vars_raw: list[str]) -> list[str]:
    args: list[str] = []
    for item in vars_raw:
        if "=" not in item:
            raise ValueError(f"Invalid --var value, expected name=value: {item}")
        args.extend(["-v", item])
    return args


def build_explain_text_sql(query_sql: str) -> str:
    stripped = query_sql.strip().rstrip(";")
    return f"EXPLAIN (BUFFERS, VERBOSE)\n{stripped};\n"


def build_explain_analyze_json_sql(query_sql: str) -> str:
    stripped = query_sql.strip().rstrip(";")
    return f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)\n{stripped};\n"


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    sql_path = resolve_sql_path(args.sql_file)
    env_values = {**load_shell_env(args.env_file), **os.environ}
    key_value = env_values.get("MASTER_REGIMES_SSH_PRIVATE_KEY_FILE", "")
    key_file = Path(key_value).expanduser() if key_value else None
    if key_file is not None and not key_file.exists():
        raise FileNotFoundError(f"SSH private key not found: {key_file}")

    host_name, host_info = coordinator_from_inventory(args.inventory)
    host = host_info["ansible_host"]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = (args.out_root / f"{timestamp}-{args.label}").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    query_sql = sql_path.read_text(encoding="utf-8")
    explain_text_sql = build_explain_text_sql(query_sql)
    explain_analyze_json_sql = build_explain_analyze_json_sql(query_sql)
    explain_settings = {
        "citus.explain_all_tasks": not args.no_citus_explain_all_tasks,
        "text_explain": "EXPLAIN (BUFFERS, VERBOSE)",
        "json_plan": "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)",
    }
    (run_dir / "query.sql").write_text(query_sql, encoding="utf-8")
    (run_dir / "explain.text.sql").write_text(explain_text_sql, encoding="utf-8")
    (run_dir / "explain.analyze.json.sql").write_text(
        explain_analyze_json_sql,
        encoding="utf-8",
    )
    (run_dir / "explain.sql").write_text(explain_analyze_json_sql, encoding="utf-8")
    write_json(run_dir / "explain_settings.json", explain_settings)

    dataset_env = {
        "DATAGEN_REGION": "eu",
        "DATAGEN_TENANT_START": str(args.tenant_start),
        "DATAGEN_TENANT_END": str(args.tenant_end),
        "DATAGEN_OUTPUT_DIR": f"/var/lib/citus-datagen/generated/{args.label}",
        "DATAGEN_RANDOM_SEED": "42",
        "DATAGEN_EVENTS_PER_TENANT": str(args.events_per_tenant),
        "DATAGEN_USERS_PER_TENANT": str(args.users_per_tenant),
        "DATAGEN_GLOBAL_USERS_PER_TENANT": str(args.global_users_per_tenant),
        "DATAGEN_ENABLE_GLOBAL_USERS": "true",
        "DATAGEN_LOOKBACK_DAYS": str(args.lookback_days),
        "DATAGEN_PROGRESS_EVERY_TENANTS": "1000",
        "DATAGEN_LOAD_METHOD": args.load_method,
        "DATAGEN_SQL_BATCH_TENANTS": "1000",
        "DATAGEN_DISTRIBUTION": args.distribution,
        "DATAGEN_HOT_TENANT_PCT": "1",
        "DATAGEN_HOT_EVENT_PCT": "50",
    }
    write_json(run_dir / "dataset_config.json", dataset_env)

    overrides = "\n".join(f"{key}={value}" for key, value in dataset_env.items()) + "\n"
    key_regex = "^(" + "|".join(DATAGEN_KEYS) + ")="
    datagen_script = f"""
set -euo pipefail
cd {shlex.quote(args.remote_datagen_dir)}
backup="$(mktemp .env.initial-explain.XXXXXX)"
cp .env "$backup"
chmod 600 "$backup"
restore_env() {{ mv "$backup" .env; }}
trap restore_env EXIT
grep -Ev {shlex.quote(key_regex)} "$backup" > .env
cat >> .env <<'DATAGEN_OVERRIDES'
{overrides.rstrip()}
DATAGEN_OVERRIDES
chmod 600 .env
./bin/reset-and-load
""".strip()
    print(f"Loading minimal dataset on {host_name} ({host})...", flush=True)
    datagen_result = ssh_run(host, args.ssh_user, key_file, datagen_script)
    (run_dir / "datagen.stdout.log").write_text(datagen_result.stdout, encoding="utf-8")
    (run_dir / "datagen.stderr.log").write_text(datagen_result.stderr, encoding="utf-8")

    remote_explain_text = f"/tmp/master-regimes-explain-text-{timestamp}.sql"
    ssh_run(
        host,
        args.ssh_user,
        key_file,
        f"cat > {shlex.quote(remote_explain_text)}",
        input_text=explain_text_sql,
    )

    var_args = psql_var_args(args.var)
    pgoptions = (
        "PGOPTIONS=-c citus.explain_all_tasks=on"
        if explain_settings["citus.explain_all_tasks"]
        else "PGOPTIONS="
    )
    explain_text_command = [
        "sudo",
        "-u",
        "postgres",
        "env",
        pgoptions,
        "psql",
        "-Xq",
        "-v",
        "ON_ERROR_STOP=1",
        *var_args,
        "-d",
        args.db_name,
        "-f",
        remote_explain_text,
    ]
    explain_text_script = " ".join(shlex.quote(part) for part in explain_text_command)
    print(f"Collecting text EXPLAIN into {run_dir}...", flush=True)
    explain_text_result = ssh_run(host, args.ssh_user, key_file, explain_text_script)
    (run_dir / "explain.txt").write_text(explain_text_result.stdout, encoding="utf-8")
    (run_dir / "explain.text.stderr.log").write_text(
        explain_text_result.stderr,
        encoding="utf-8",
    )

    remote_explain_json = f"/tmp/master-regimes-explain-analyze-json-{timestamp}.sql"
    ssh_run(
        host,
        args.ssh_user,
        key_file,
        f"cat > {shlex.quote(remote_explain_json)}",
        input_text=explain_analyze_json_sql,
    )
    explain_command = [
        "sudo",
        "-u",
        "postgres",
        "env",
        pgoptions,
        "psql",
        "-XqAt",
        "-v",
        "ON_ERROR_STOP=1",
        *var_args,
        "-d",
        args.db_name,
        "-f",
        remote_explain_json,
    ]
    explain_script = " ".join(shlex.quote(part) for part in explain_command)
    print(f"Collecting EXPLAIN ANALYZE JSON into {run_dir}...", flush=True)
    explain_result = ssh_run(host, args.ssh_user, key_file, explain_script)
    (run_dir / "explain.stderr.log").write_text(explain_result.stderr, encoding="utf-8")
    raw_plan = explain_result.stdout.strip()
    try:
        write_json(run_dir / "plan.json", json.loads(raw_plan))
    except json.JSONDecodeError as error:
        (run_dir / "plan.raw.txt").write_text(raw_plan + "\n", encoding="utf-8")
        raise RuntimeError(
            f"EXPLAIN output was not valid JSON. See {run_dir / 'plan.raw.txt'}"
        ) from error

    counts_sql = """
with node_state as (
  select coalesce(jsonb_agg(jsonb_build_object(
    'nodename', nodename,
    'nodeport', nodeport,
    'isactive', isactive
  ) order by nodename, nodeport), '[]'::jsonb) as nodes
  from pg_dist_node
)
select jsonb_build_object(
  'tenants', (select count(*) from tenants),
  'users', (select count(*) from users),
  'global_users', (select count(*) from global_users),
  'events', (select count(*) from events),
  'min_created_at', (select min(created_at) from events),
  'max_created_at', (select max(created_at) from events),
  'pg_dist_node', (select nodes from node_state)
);
""".strip()
    remote_counts = f"/tmp/master-regimes-counts-{timestamp}.sql"
    ssh_run(
        host,
        args.ssh_user,
        key_file,
        f"cat > {shlex.quote(remote_counts)}",
        input_text=counts_sql,
    )
    counts_script = " ".join(
        shlex.quote(part)
        for part in [
            "sudo",
            "-u",
            "postgres",
            "psql",
            "-XqAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-d",
            args.db_name,
            "-f",
            remote_counts,
        ]
    )
    counts_result = ssh_run(host, args.ssh_user, key_file, counts_script)
    write_json(run_dir / "dataset_counts.json", json.loads(counts_result.stdout.strip()))

    cleanup = (
        f"rm -f {shlex.quote(remote_explain_text)} "
        f"{shlex.quote(remote_explain_json)} {shlex.quote(remote_counts)}"
    )
    ssh_run(host, args.ssh_user, key_file, cleanup)

    metadata = {
        "created_at": timestamp,
        "label": args.label,
        "coordinator": {"name": host_name, "host": host, **host_info},
        "sql_file": str(sql_path),
        "psql_vars": args.var,
        "explain_settings": explain_settings,
        "db_name": args.db_name,
        "artifacts": {
            "query_sql": "query.sql",
            "explain_text_sql": "explain.text.sql",
            "explain_text": "explain.txt",
            "explain_analyze_json_sql": "explain.analyze.json.sql",
            "explain_sql": "explain.sql",
            "explain_settings": "explain_settings.json",
            "plan_json": "plan.json",
            "dataset_config": "dataset_config.json",
            "dataset_counts": "dataset_counts.json",
        },
    }
    write_json(run_dir / "metadata.json", metadata)
    print(str(run_dir), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stdout or "")
        sys.stderr.write(exc.stderr or "")
        raise
