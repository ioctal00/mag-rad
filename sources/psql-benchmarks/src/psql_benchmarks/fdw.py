from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from .psql import run_psql
from .run_dir import create_run_dir
from .settings import Settings

DEFAULT_FDW_TABLES = ("events", "tenants", "users", "global_users")
ALLOWED_SERVER_OPTIONS = {
    "fetch_size",
    "use_remote_estimate",
    "fdw_startup_cost",
    "fdw_tuple_cost",
    "options",
}


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _env_required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _parse_key_value_options(values: list[str] | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"FDW options must use KEY=VALUE format: {value}")
        key, option_value = value.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_SERVER_OPTIONS:
            allowed = ", ".join(sorted(ALLOWED_SERVER_OPTIONS))
            raise ValueError(f"Unsupported postgres_fdw server option {key}. Allowed: {allowed}")
        parsed[key] = option_value
    return parsed


def _remote_region_config(region: str) -> dict[str, str]:
    prefix = f"REGION_{region.upper()}_POSTGRES_"
    return {
        "region": region,
        "host": _env_required(prefix + "HOST"),
        "port": os.getenv(prefix + "PORT", "5432"),
        "db": _env_required(prefix + "DB"),
        "user": _env_required(prefix + "USER"),
        "password": _env_required(prefix + "PASSWORD"),
        "sslmode": os.getenv(prefix + "SSLMODE", "verify-ca"),
        "sslrootcert": _env_required(prefix + "SSLROOTCERT"),
        "readonly_user": os.getenv(prefix + "READONLY_USER", ""),
        "readonly_password": os.getenv(prefix + "READONLY_PASSWORD", ""),
    }


def _bootstrap_sql(
    *,
    region_config: dict[str, str],
    schema: str,
    server_name: str,
    tables: list[str],
    server_options_override: dict[str, str],
) -> str:
    server_options = {
        "host": region_config["host"],
        "port": region_config["port"],
        "dbname": region_config["db"],
        "sslmode": region_config["sslmode"],
        "sslrootcert": region_config["sslrootcert"],
    }
    server_options.update(server_options_override)
    option_sql = ", ".join(
        f"{_quote_ident(key)} {_quote_literal(value)}"
        for key, value in server_options.items()
    )
    table_list = ", ".join(_quote_ident(table) for table in tables)
    readonly_mapping_sql = ""
    readonly_grant_sql = ""
    if region_config["readonly_user"] and region_config["readonly_password"]:
        readonly_user = region_config["readonly_user"]
        readonly_mapping_sql = f"""
CREATE USER MAPPING IF NOT EXISTS FOR {_quote_ident(readonly_user)}
  SERVER {_quote_ident(server_name)}
  OPTIONS (
    user {_quote_literal(region_config["readonly_user"])},
    password {_quote_literal(region_config["readonly_password"])},
    password_required 'false'
  );
GRANT USAGE ON FOREIGN SERVER {_quote_ident(server_name)}
  TO {_quote_ident(readonly_user)};
""".strip()
        readonly_grant_sql = f"""
GRANT USAGE ON SCHEMA {_quote_ident(schema)}
  TO {_quote_ident(readonly_user)};
GRANT SELECT ON ALL TABLES IN SCHEMA {_quote_ident(schema)}
  TO {_quote_ident(readonly_user)};
""".strip()
    return f"""
CREATE EXTENSION IF NOT EXISTS postgres_fdw;
DROP SERVER IF EXISTS {_quote_ident(server_name)} CASCADE;
DROP SCHEMA IF EXISTS {_quote_ident(schema)} CASCADE;
CREATE SCHEMA {_quote_ident(schema)};
CREATE SERVER {_quote_ident(server_name)}
  FOREIGN DATA WRAPPER postgres_fdw
  OPTIONS ({option_sql});
CREATE USER MAPPING FOR CURRENT_USER
  SERVER {_quote_ident(server_name)}
  OPTIONS (
    user {_quote_literal(region_config["user"])},
    password {_quote_literal(region_config["password"])}
  );
{readonly_mapping_sql}
IMPORT FOREIGN SCHEMA public
  LIMIT TO ({table_list})
  FROM SERVER {_quote_ident(server_name)}
  INTO {_quote_ident(schema)};
{readonly_grant_sql}
ANALYZE {_quote_ident(schema)}.{_quote_ident("tenants")};
SELECT 1 AS fdw_connectivity_probe
FROM {_quote_ident(schema)}.{_quote_ident("tenants")}
LIMIT 1;
""".strip()


def _redact_bootstrap_sql(sql: str, region_config: dict[str, str]) -> str:
    redacted = sql
    for password in (region_config["password"], region_config["readonly_password"]):
        if not password:
            continue
        pattern = re.compile(rf"(password\s+){re.escape(_quote_literal(password))}")
        redacted = pattern.sub(
            lambda match: match.group(1) + _quote_literal("<redacted>"),
            redacted,
        )
    return redacted


def fdw_bootstrap(
    settings: Settings,
    *,
    label: str,
    region: str,
    schema: str | None = None,
    server_name: str | None = None,
    tables: list[str] | None = None,
    server_options: list[str] | None = None,
) -> Path:
    normalized_region = region.lower()
    schema_name = schema or f"fdw_{normalized_region}"
    server = server_name or f"{normalized_region}_citus"
    table_names = tables or list(DEFAULT_FDW_TABLES)
    region_config = _remote_region_config(normalized_region)
    server_options_override = _parse_key_value_options(server_options)
    run_dir = create_run_dir(settings, mode="fdw-bootstrap", label=label)
    sql = _bootstrap_sql(
        region_config=region_config,
        schema=schema_name,
        server_name=server,
        tables=table_names,
        server_options_override=server_options_override,
    )
    sql_file = run_dir / "queries" / f"fdw-bootstrap-{normalized_region}.sql"
    sql_file.write_text(_redact_bootstrap_sql(sql, region_config) + "\n", encoding="utf-8")

    safe_region_config = {
        **region_config,
        "password": "<redacted>",
        "readonly_password": "<redacted>" if region_config["readonly_password"] else "",
    }
    fdw_options: dict[str, Any] = {
        "server_options": server_options_override,
        "allowed_server_options": sorted(ALLOWED_SERVER_OPTIONS),
    }
    (run_dir / "fdw_bootstrap_manifest.json").write_text(
        json.dumps(
            {
                "region": normalized_region,
                "schema": schema_name,
                "server_name": server,
                "tables": table_names,
                "fdw_options": fdw_options,
                "remote": safe_region_config,
                "local_database": settings.pg_database,
                "local_user": settings.pg_user,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_psql(settings, sql=sql)
    (run_dir / "results" / "fdw_bootstrap.stdout.log").write_text(
        result.stdout, encoding="utf-8"
    )
    (run_dir / "logs" / "fdw_bootstrap.stderr.log").write_text(
        result.stderr, encoding="utf-8"
    )
    (run_dir / "results" / "fdw_bootstrap_timing.json").write_text(
        json.dumps(
            {
                "elapsed_seconds": result.elapsed_seconds,
                "started_at_unix": result.started_at_unix,
                "finished_at_unix": result.finished_at_unix,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir
