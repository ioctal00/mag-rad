#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare STATS baseline, EU FDW and US FDW scalar results."
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--target-host", default="")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--label", default="stats-ceb-correctness")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "result-validation",
    )
    return parser.parse_args()


def result_hash(value: str) -> str:
    return hashlib.sha256(f"{value.strip()}\n".encode()).hexdigest()


def schema_hash() -> str:
    return hashlib.sha256(b"result_count:int8\n").hexdigest()


def classify_psql_failure(stderr: str) -> str:
    normalized = stderr.lower()
    if "statement timeout" in normalized:
        return "timeout"
    infrastructure_markers = (
        "connection refused",
        "connection to server",
        "could not connect to server",
        "no such file or directory",
        "server closed the connection unexpectedly",
        "terminating connection",
        "ssl syscall error",
        "could not receive data from server",
        "out of memory",
        "cannot allocate memory",
        "could not resize shared memory",
    )
    if any(marker in normalized for marker in infrastructure_markers):
        return "infrastructure_failure"
    return "unsupported_sql"


def ensure_postgres_available(
    *,
    host: str,
    user: str,
    key_file: Path | None,
) -> None:
    result = ssh_run(
        host=host,
        user=user,
        key_file=key_file,
        remote_script="""
set -euo pipefail
if sudo -u postgres pg_isready -q -d app; then
  exit 0
fi
systemctl reset-failed postgresql@18-main.service || true
systemctl restart postgresql@18-main.service
for attempt in $(seq 1 30); do
  if sudo -u postgres pg_isready -q -d app; then
    exit 0
  fi
  sleep 1
done
echo "PostgreSQL did not become ready after recovery" >&2
exit 1
""".strip(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"PostgreSQL recovery failed on {host}: {result.stderr.strip()}"
        )


def execute_scalar(
    *,
    host: str,
    user: str,
    key_file: Path | None,
    database: str,
    schema: str,
    sql: str,
    timeout_seconds: int,
) -> tuple[str, str]:
    command = (
        "sudo -u postgres psql -X -q -A -t -v ON_ERROR_STOP=1 "
        f"-d {shlex.quote(database)}"
    )
    payload = (
        f"SET statement_timeout = '{timeout_seconds}s';\n"
        f"SET search_path TO {schema}, public;\n"
        f"{sql.strip()}\n"
    )
    result = ssh_run(
        host=host,
        user=user,
        key_file=key_file,
        remote_script=command,
        input_text=payload,
        check=False,
    )
    if result.returncode != 0:
        return classify_psql_failure(result.stderr), ""
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 1 or not lines[0].lstrip("-").isdigit():
        return "infrastructure_failure", ""
    return "passed", lines[0]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    profile_path = args.profile.resolve()
    selection_path = args.selection.resolve()
    profile = load_yaml(profile_path)
    selection = load_yaml(selection_path)
    adapter = profile.get("execution_adapter") or {}
    selected_dir = selection_path.parent / "selected-queries"
    env_values = load_shell_env(args.env_file)
    key_file = private_key(env_values)
    host_name, host_info = load_group_host(
        args.inventory,
        group="analytics_clients",
        target_host=args.target_host,
    )
    host = str(host_info["ansible_host"])
    recovery_hosts = {
        "baseline": host,
        "eu": str(
            load_group_host(args.inventory, group="coordinators", region="eu")[1][
                "ansible_host"
            ]
        ),
        "us": str(
            load_group_host(args.inventory, group="coordinators", region="us")[1][
                "ansible_host"
            ]
        ),
    }
    for recovery_host in dict.fromkeys(recovery_hosts.values()):
        ensure_postgres_available(
            host=recovery_host,
            user=args.ssh_user,
            key_file=key_file,
        )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{args.label}"
    out_dir = (args.out_root / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    schemas = {
        "baseline": str(adapter["baseline_schema"]),
        "eu": str((adapter.get("fdw_schemas") or {})["eu"]),
        "us": str((adapter.get("fdw_schemas") or {})["us"]),
    }
    rows: list[dict[str, Any]] = []
    for query_spec in selection.get("queries") or []:
        query_id = int(query_spec["query_id"])
        sql_path = selected_dir / f"q-{query_id}.sql"
        sql = sql_path.read_text(encoding="utf-8")
        observed: dict[str, tuple[str, str]] = {}
        for scope, schema in schemas.items():
            if args.dry_run:
                observed[scope] = ("dry_run", "")
            else:
                print(
                    f"[STATS-CEB] correctness q={query_id} scope={scope}",
                    flush=True,
                )
                observed[scope] = execute_scalar(
                    host=host,
                    user=args.ssh_user,
                    key_file=key_file,
                    database=str(adapter["baseline_database"]),
                    schema=schema,
                    sql=sql,
                    timeout_seconds=args.timeout_seconds,
                )
                if observed[scope][0] in {
                    "infrastructure_failure",
                    "timeout",
                }:
                    print(
                        (
                            f"[STATS-CEB] health/recovery check after "
                            f"q={query_id} scope={scope} "
                            f"status={observed[scope][0]}"
                        ),
                        flush=True,
                    )
                    ensure_postgres_available(
                        host=recovery_hosts[scope],
                        user=args.ssh_user,
                        key_file=key_file,
                    )

        baseline_status, baseline_value = observed["baseline"]
        eu_status, eu_value = observed["eu"]
        us_status, us_value = observed["us"]
        if args.dry_run:
            comparison_status = "dry_run"
        elif any(
            status != "passed"
            for status in (baseline_status, eu_status, us_status)
        ):
            comparison_status = next(
                status
                for status in (baseline_status, eu_status, us_status)
                if status != "passed"
            )
        elif not (
            baseline_value == eu_value == us_value == str(query_spec["expected_count"])
        ):
            comparison_status = "result_mismatch"
        else:
            comparison_status = "passed"

        rows.append(
            {
                "query_id": query_id,
                "expected_citus_strategy": query_spec["expected_citus_strategy"],
                "baseline_status": baseline_status,
                "eu_status": eu_status,
                "us_status": us_status,
                "baseline_result_hash": (
                    result_hash(baseline_value) if baseline_value else ""
                ),
                "eu_result_hash": result_hash(eu_value) if eu_value else "",
                "us_result_hash": result_hash(us_value) if us_value else "",
                "schema_hash": schema_hash(),
                "comparison_status": comparison_status,
                "tolerance_policy": "exact_integer",
                "database_result_rows_persisted": "false",
            }
        )

    write_csv(out_dir / "result_equivalence.csv", rows)
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row["comparison_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    overall_status = (
        "dry_run"
        if args.dry_run
        else "completed"
        if status_counts == {"passed": len(rows)}
        else "completed_with_query_failures"
    )
    write_json(
        out_dir / "result_validation_manifest.json",
        {
            "run_id": run_id,
            "created_at_utc": timestamp,
            "dataset_id": profile["dataset_id"],
            "profile": str(profile_path),
            "profile_sha256": file_digest(profile_path, "sha256"),
            "selection": str(selection_path),
            "selection_sha256": file_digest(selection_path, "sha256"),
            "target_host": host_name,
            "database": adapter["baseline_database"],
            "schemas": schemas,
            "query_count": len(rows),
            "status_counts": status_counts,
            "database_result_rows_persisted": False,
            "regional_counts_aggregated": False,
            "status": overall_status,
        },
    )
    print(str(out_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
