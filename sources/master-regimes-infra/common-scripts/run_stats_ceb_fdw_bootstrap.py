#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path

from stats_ceb_support import (
    DEFAULT_ENV_FILE,
    DEFAULT_INVENTORY,
    file_digest,
    load_group_host,
    load_shell_env,
    load_yaml,
    private_key,
    ssh_run,
    write_json,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
SAFE_OPTION = re.compile(r"^[a-z_][a-z0-9_]*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import one regional STATS schema through existing GAC FDW servers."
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--region", choices=("eu", "us"), required=True)
    parser.add_argument("--label", default="stats-ceb-fdw")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--target-host", default="")
    parser.add_argument("--fdw-server-option", action="append", default=[])
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "fdw-bootstrap",
    )
    return parser.parse_args()


def key_value_map(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, option_value = value.partition("=")
        if not separator or not SAFE_OPTION.fullmatch(key):
            raise ValueError(f"Invalid FDW server option: {value}")
        result[key] = option_value
    return result


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def fdw_sql(
    *,
    database: str,
    source_schema: str,
    target_schema: str,
    server_name: str,
    options: dict[str, str],
) -> str:
    for identifier in (source_schema, target_schema, server_name):
        if not SAFE_IDENTIFIER.fullmatch(identifier):
            raise ValueError(f"Unsafe PostgreSQL identifier: {identifier}")
    option_blocks: list[str] = []
    for key, value in sorted(options.items()):
        option_blocks.append(
            f"""
DO $option$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_foreign_server
    CROSS JOIN LATERAL unnest(COALESCE(srvoptions, ARRAY[]::text[])) AS option_value
    WHERE srvname = {sql_literal(server_name)}
      AND option_value LIKE {sql_literal(key + '=%')}
  ) THEN
    EXECUTE 'ALTER SERVER {server_name} OPTIONS (SET {key} '
      || quote_literal({sql_literal(value)}) || ')';
  ELSE
    EXECUTE 'ALTER SERVER {server_name} OPTIONS (ADD {key} '
      || quote_literal({sql_literal(value)}) || ')';
  END IF;
END
$option$;
""".strip()
        )
    options_sql = "\n".join(option_blocks)
    return f"""
DROP SCHEMA IF EXISTS {target_schema} CASCADE;
CREATE SCHEMA {target_schema};
{options_sql}
IMPORT FOREIGN SCHEMA {source_schema}
  FROM SERVER {server_name}
  INTO {target_schema};
DO $audit$
BEGIN
  IF (
    SELECT count(*)
    FROM information_schema.foreign_tables
    WHERE foreign_table_schema = {sql_literal(target_schema)}
  ) <> 8 THEN
    RAISE EXCEPTION 'Expected eight STATS foreign tables in {target_schema}';
  END IF;
END
$audit$;
""".strip()


def main() -> int:
    args = parse_args()
    profile_path = args.profile.resolve()
    profile = load_yaml(profile_path)
    adapter = profile.get("execution_adapter") or {}
    if adapter.get("id") != "stats_ceb":
        raise ValueError("Dataset profile does not declare execution_adapter.id=stats_ceb")
    fdw_schemas = adapter.get("fdw_schemas") or {}
    fdw_servers = adapter.get("fdw_servers") or {}
    target_schema = str(fdw_schemas[args.region])
    server_name = str(fdw_servers[args.region])
    options = key_value_map(args.fdw_server_option)

    env_values = load_shell_env(args.env_file)
    key_file = private_key(env_values)
    host_name, host_info = load_group_host(
        args.inventory,
        group="analytics_clients",
        target_host=args.target_host,
    )
    host = str(host_info["ansible_host"])
    sql = fdw_sql(
        database=str(adapter["baseline_database"]),
        source_schema=str(adapter["regional_schema"]),
        target_schema=target_schema,
        server_name=server_name,
        options=options,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{args.label}-{args.region}"
    out_dir = (args.out_root / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    sql_path = out_dir / "fdw_bootstrap.sql"
    sql_path.write_text(sql + "\n", encoding="utf-8")

    print(
        f"[STATS-CEB] import region={args.region} into {target_schema} on {host_name}",
        flush=True,
    )
    result = ssh_run(
        host=host,
        user=args.ssh_user,
        key_file=key_file,
        remote_script=(
            "sudo -u postgres psql -X -v ON_ERROR_STOP=1 "
            f"-d {shlex.quote(str(adapter['baseline_database']))}"
        ),
        input_text=sql,
    )
    write_json(
        out_dir / "fdw_bootstrap_manifest.json",
        {
            "run_id": run_id,
            "created_at_utc": timestamp,
            "dataset_id": profile["dataset_id"],
            "profile": str(profile_path),
            "profile_sha256": file_digest(profile_path, "sha256"),
            "target_host": host_name,
            "region": args.region,
            "source_schema": adapter["regional_schema"],
            "target_schema": target_schema,
            "fdw_server": server_name,
            "fdw_server_options": options,
            "database": adapter["baseline_database"],
            "status": "completed",
            "psql_stderr": result.stderr,
        },
    )
    print(str(out_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
