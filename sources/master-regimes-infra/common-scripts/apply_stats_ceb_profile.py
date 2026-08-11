#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
from datetime import UTC, datetime
from pathlib import Path

from stats_ceb_support import (
    DEFAULT_ENV_FILE,
    DEFAULT_INVENTORY,
    ensure_dump,
    ensure_remote_file,
    file_digest,
    load_group_host,
    load_shell_env,
    load_yaml,
    private_key,
    scp_file,
    ssh_run,
    write_json,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
REMOTE_CACHE = "/var/tmp/master-regimes-stats-ceb"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load the pinned STATS-CEB snapshot into one Citus region."
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--region", choices=("eu", "us"), required=True)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "generated" / "runs" / "dataset-loads",
    )
    return parser.parse_args()


def resolve_from_profile(profile_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path.resolve() if path.is_absolute() else (profile_path.parent / path).resolve()


def regional_load_script(
    *,
    dump_path: str,
    ddl_path: str,
    regional_database: str,
    regional_schema: str,
    staging_database: str,
) -> str:
    schema = shlex.quote(regional_schema)
    stage = shlex.quote(staging_database)
    return f"""
set -euo pipefail
cleanup_stage() {{
  sudo -u postgres dropdb --if-exists {stage} >/dev/null 2>&1 || true
}}
trap cleanup_stage EXIT
sudo -u postgres dropdb --if-exists {stage}
sudo -u postgres createdb {stage}
sudo -u postgres pg_restore --exit-on-error --no-owner --no-privileges \
  --schema=public --dbname={stage} {shlex.quote(dump_path)} \
  >/tmp/stats-ceb-restore.stdout 2>/tmp/stats-ceb-restore.stderr
sudo -u postgres psql -X -v ON_ERROR_STOP=1 \
  -d {stage} <<'STATS_STAGE_SQL'
DROP SCHEMA IF EXISTS {regional_schema} CASCADE;
CREATE SCHEMA {regional_schema};
DO $$
DECLARE table_row record;
BEGIN
  FOR table_row IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename IN (
        'users', 'badges', 'posts', 'tags', 'postlinks',
        'posthistory', 'comments', 'votes'
      )
  LOOP
    EXECUTE format(
      'ALTER TABLE public.%I SET SCHEMA {regional_schema}',
      table_row.tablename
    );
  END LOOP;
END
$$;
DO $$
BEGIN
  IF (
    SELECT count(*)
    FROM pg_tables
    WHERE schemaname = '{regional_schema}'
  ) <> 8 THEN
    RAISE EXCEPTION 'Expected eight STATS tables after restore';
  END IF;
END
$$;
STATS_STAGE_SQL
sudo -u postgres psql -X -v ON_ERROR_STOP=1 \
  -d {shlex.quote(regional_database)} \
  -c 'DROP SCHEMA IF EXISTS {regional_schema} CASCADE'
sudo -u postgres pg_dump --no-owner --no-privileges --schema={schema} \
  {stage} \
  | sudo -u postgres psql -X -v ON_ERROR_STOP=1 \
      -d {shlex.quote(regional_database)}
sudo -u postgres psql -X -v ON_ERROR_STOP=1 \
  -d {shlex.quote(regional_database)} -f {shlex.quote(ddl_path)}
metadata_count="$(sudo -u postgres psql -X -A -t -v ON_ERROR_STOP=1 \
  -d {shlex.quote(regional_database)} <<'STATS_AUDIT_SQL'
SELECT count(*)
FROM pg_dist_partition
WHERE logicalrelid::regclass::text LIKE '{regional_schema}.%';
STATS_AUDIT_SQL
)"
if [ "$metadata_count" -ne 8 ]; then
  echo "Expected eight STATS Citus metadata rows, found $metadata_count" >&2
  exit 1
fi
printf '%s\n' "$metadata_count"
""".strip()


def baseline_load_script(
    *,
    dump_path: str,
    baseline_database: str,
    baseline_schema: str,
    staging_database: str,
) -> str:
    schema = shlex.quote(baseline_schema)
    stage = shlex.quote(staging_database)
    return f"""
set -euo pipefail
cleanup_stage() {{
  sudo -u postgres dropdb --if-exists {stage} >/dev/null 2>&1 || true
}}
trap cleanup_stage EXIT
sudo -u postgres dropdb --if-exists {stage}
sudo -u postgres createdb {stage}
sudo -u postgres pg_restore --exit-on-error --no-owner --no-privileges \
  --schema=public --dbname={stage} {shlex.quote(dump_path)} \
  >/tmp/stats-ceb-baseline-restore.stdout 2>/tmp/stats-ceb-baseline-restore.stderr
sudo -u postgres psql -X -v ON_ERROR_STOP=1 \
  -d {stage} <<'STATS_BASELINE_STAGE_SQL'
DROP SCHEMA IF EXISTS {baseline_schema} CASCADE;
CREATE SCHEMA {baseline_schema};
DO $$
DECLARE table_row record;
BEGIN
  FOR table_row IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename IN (
        'users', 'badges', 'posts', 'tags', 'postlinks',
        'posthistory', 'comments', 'votes'
      )
  LOOP
    EXECUTE format(
      'ALTER TABLE public.%I SET SCHEMA {baseline_schema}',
      table_row.tablename
    );
  END LOOP;
END
$$;
DO $$
BEGIN
  IF (
    SELECT count(*)
    FROM pg_tables
    WHERE schemaname = '{baseline_schema}'
  ) <> 8 THEN
    RAISE EXCEPTION 'Expected eight STATS baseline tables after restore';
  END IF;
END
$$;
STATS_BASELINE_STAGE_SQL
sudo -u postgres psql -X -v ON_ERROR_STOP=1 \
  -d {shlex.quote(baseline_database)} \
  -c 'DROP SCHEMA IF EXISTS {baseline_schema} CASCADE'
sudo -u postgres pg_dump --no-owner --no-privileges --schema={schema} \
  {stage} \
  | sudo -u postgres psql -X -v ON_ERROR_STOP=1 \
      -d {shlex.quote(baseline_database)}
sudo -u postgres psql -X -v ON_ERROR_STOP=1 \
  -d {shlex.quote(baseline_database)} -c 'ANALYZE'
""".strip()


def main() -> int:
    args = parse_args()
    profile_path = args.profile.resolve()
    profile = load_yaml(profile_path)
    adapter = profile.get("execution_adapter") or {}
    if adapter.get("id") != "stats_ceb":
        raise ValueError("Dataset profile does not declare execution_adapter.id=stats_ceb")
    source_lock_path = resolve_from_profile(profile_path, str(profile["source_lock"]))
    cache_raw = Path(str(adapter.get("source_cache_dir", "tmp/stats-ceb")))
    cache_dir = (
        cache_raw.resolve()
        if cache_raw.is_absolute()
        else (WORKSPACE_ROOT / "master-regimes" / cache_raw).resolve()
    )
    dump_path, source_audit = ensure_dump(source_lock_path, cache_dir)
    expected_md5 = source_audit["dump_md5"]
    ddl_path = resolve_from_profile(profile_path, str(adapter["citus_ddl"]))
    env_values = load_shell_env(args.env_file)
    key_file = private_key(env_values)

    coordinator_name, coordinator = load_group_host(
        args.inventory,
        group="coordinators",
        region=args.region,
    )
    coordinator_host = str(coordinator["ansible_host"])
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{profile['dataset_id']}-{args.region}"
    out_dir = (args.out_root / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[STATS-CEB] upload/verify dump on {coordinator_name} ({coordinator_host})",
        flush=True,
    )
    remote_dump = ensure_remote_file(
        local_path=dump_path,
        expected_md5=expected_md5,
        host=coordinator_host,
        user=args.ssh_user,
        key_file=key_file,
        remote_dir=REMOTE_CACHE,
    )
    remote_ddl = f"{REMOTE_CACHE}/{ddl_path.name}"
    scp_file(
        source=ddl_path,
        host=coordinator_host,
        user=args.ssh_user,
        key_file=key_file,
        destination=remote_ddl,
    )
    print(f"[STATS-CEB] rebuild region={args.region} schema=stats", flush=True)
    regional_result = ssh_run(
        host=coordinator_host,
        user=args.ssh_user,
        key_file=key_file,
        remote_script=regional_load_script(
            dump_path=remote_dump,
            ddl_path=remote_ddl,
            regional_database=str(adapter["regional_database"]),
            regional_schema=str(adapter["regional_schema"]),
            staging_database=f"stats_ceb_stage_{args.region}",
        ),
    )

    baseline_prepared = False
    baseline_host_name = ""
    if args.region == str(adapter.get("baseline_prepare_region", "eu")):
        baseline_host_name, baseline_host_info = load_group_host(
            args.inventory,
            group="analytics_clients",
        )
        baseline_host = str(baseline_host_info["ansible_host"])
        print(
            f"[STATS-CEB] rebuild canonical baseline on {baseline_host_name}",
            flush=True,
        )
        baseline_dump = ensure_remote_file(
            local_path=dump_path,
            expected_md5=expected_md5,
            host=baseline_host,
            user=args.ssh_user,
            key_file=key_file,
            remote_dir=REMOTE_CACHE,
        )
        ssh_run(
            host=baseline_host,
            user=args.ssh_user,
            key_file=key_file,
            remote_script=baseline_load_script(
                dump_path=baseline_dump,
                baseline_database=str(adapter["baseline_database"]),
                baseline_schema=str(adapter["baseline_schema"]),
                staging_database="stats_ceb_baseline_stage",
            ),
        )
        baseline_prepared = True

    distribution_counts = [
        line.strip()
        for line in regional_result.stdout.splitlines()
        if line.strip().isdigit()
    ]
    manifest = {
        "load_id": run_id,
        "run_id": run_id,
        "created_at_utc": timestamp,
        "dataset_id": profile["dataset_id"],
        "profile": str(profile_path),
        "profile_sha256": file_digest(profile_path, "sha256"),
        "region": args.region,
        "coordinator": coordinator_name,
        "regional_database": adapter["regional_database"],
        "regional_schema": adapter["regional_schema"],
        "physical_design": profile["physical_design"],
        "source": source_audit,
        "baseline_prepared": baseline_prepared,
        "baseline_host": baseline_host_name,
        "baseline_database": adapter["baseline_database"],
        "baseline_schema": adapter["baseline_schema"],
        "regional_distribution_table_count": (
            int(distribution_counts[-1]) if distribution_counts else None
        ),
        "status": "completed",
    }
    write_json(out_dir / "stats_ceb_dataset_manifest.json", manifest)
    write_json(out_dir / "dataset_load_manifest.json", manifest)
    write_json(
        out_dir / "capability_audit.json",
        {
            "status": "not_applicable_external_relational",
            "dataset_id": profile["dataset_id"],
            "region": args.region,
            "declared_distribution": profile["physical_design"],
            "declared_capabilities": profile["capabilities"],
            "measured_capabilities": {},
            "table_counts": {},
            "warnings": [],
        },
    )
    print(str(out_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
