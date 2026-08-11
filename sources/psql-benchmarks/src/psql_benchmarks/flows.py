from __future__ import annotations

from contextlib import suppress
import csv
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time

from .os_sampler import OsSampler, collect_sample, summarize_samples
from .psql import result_signature as calculate_result_signature
from .psql import result_snapshot as calculate_result_snapshot
from .psql import run_psql
from .run_dir import create_run_dir
from .settings import ROOT_DIR, Settings
from .workloads import QueryTemplate, baseline_queries


def _safe_label(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value)


def _copy_query(run_dir: Path, query: QueryTemplate) -> None:
    shutil.copy2(query.path, run_dir / "queries" / query.path.name)


def _write_dataset_parameters(settings: Settings, run_dir: Path, phase: str) -> None:
    output_file = run_dir / "snapshots" / f"{phase}_dataset_parameters.json"
    output_file.write_text(
        json.dumps(settings.datagen_parameters, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_unavailable_csv(output_file: Path, error: str = "") -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["available", "error"])
        writer.writeheader()
        writer.writerow({"available": "false", "error": error})


def _relation_exists(settings: Settings, relation_name: str) -> bool:
    result = run_psql(
        settings,
        sql=f"select to_regclass('{relation_name}') is not null;",
        csv_output=True,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return len(lines) >= 2 and lines[-1] in {"t", "true"}


def _reset_statement_stats(settings: Settings) -> None:
    if _relation_exists(settings, "pg_stat_statements"):
        with suppress(subprocess.CalledProcessError):
            run_psql(settings, sql="select pg_stat_statements_reset();")

    if settings.bench_node_role == "coordinator" and _relation_exists(
        settings, "citus_stat_statements"
    ):
        with suppress(subprocess.CalledProcessError):
            run_psql(settings, sql="select citus_stat_statements_reset();")


def _write_pg_stat_io_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    run_psql(
        settings,
        sql="""
select backend_type,
       object,
       context,
       reads,
       read_bytes,
       read_time,
       writes,
       write_bytes,
       write_time,
       writebacks,
       writeback_time,
       extends,
       extend_bytes,
       extend_time,
       hits,
       evictions,
       reuses,
       fsyncs,
       fsync_time,
       stats_reset
from pg_stat_io
order by backend_type, object, context;
""",
        csv_output=True,
        output_file=run_dir / "snapshots" / f"{phase}_pg_stat_io.csv",
    )


def _write_pg_settings_relevant_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    run_psql(
        settings,
        sql="""
select name,
       setting,
       unit,
       vartype,
       context,
       source,
       sourcefile,
       sourceline,
       pending_restart,
       boot_val,
       reset_val,
       short_desc
from pg_settings
where name like 'citus.%'
   or name in (
       'application_name',
       'shared_preload_libraries',
       'server_version',
       'server_version_num',
       'cluster_name',
       'listen_addresses',
       'port',
       'max_connections',
       'superuser_reserved_connections',
       'work_mem',
       'maintenance_work_mem',
       'shared_buffers',
       'effective_cache_size',
       'temp_buffers',
       'hash_mem_multiplier',
       'max_parallel_workers',
       'max_parallel_workers_per_gather',
       'max_worker_processes',
       'parallel_setup_cost',
       'parallel_tuple_cost',
       'jit',
       'jit_above_cost',
       'random_page_cost',
       'seq_page_cost',
       'cpu_tuple_cost',
       'cpu_index_tuple_cost',
       'cpu_operator_cost',
       'effective_io_concurrency',
       'maintenance_io_concurrency',
       'track_activities',
       'track_counts',
       'track_io_timing',
       'track_wal_io_timing',
       'track_functions',
       'compute_query_id',
       'pg_stat_statements.track',
       'pg_stat_statements.track_planning',
       'pg_stat_statements.max',
       'wal_level',
       'fsync',
       'synchronous_commit',
       'full_page_writes',
       'checkpoint_timeout',
       'checkpoint_completion_target',
       'max_wal_size',
       'min_wal_size',
       'autovacuum',
       'autovacuum_max_workers',
       'autovacuum_naptime',
       'autovacuum_vacuum_scale_factor',
       'autovacuum_analyze_scale_factor',
       'default_statistics_target',
       'shared_memory_type',
       'huge_pages',
       'max_files_per_process',
       'temp_file_limit'
   )
order by case when name like 'citus.%' then 0 else 1 end, name;
""",
        csv_output=True,
        output_file=run_dir / "snapshots" / f"{phase}_pg_settings_relevant.csv",
    )


def _write_pg_stat_database_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    run_psql(
        settings,
        sql="""
select datname,
       blks_read,
       blks_hit,
       temp_files,
       temp_bytes,
       blk_read_time,
       blk_write_time,
       stats_reset
from pg_stat_database
where datname = current_database();
""",
        csv_output=True,
        output_file=run_dir / "snapshots" / f"{phase}_pg_stat_database.csv",
    )


def _write_pg_statio_user_tables_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    run_psql(
        settings,
        sql="""
select relid::regclass as table_name,
       heap_blks_read,
       heap_blks_hit,
       idx_blks_read,
       idx_blks_hit,
       toast_blks_read,
       toast_blks_hit,
       tidx_blks_read,
       tidx_blks_hit
from pg_statio_user_tables
where relname in ('events', 'tenants', 'users', 'global_users')
order by relname;
""",
        csv_output=True,
        output_file=run_dir / "snapshots" / f"{phase}_pg_statio_user_tables.csv",
    )


def _write_pg_stat_user_tables_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    run_psql(
        settings,
        sql="""
select relid::regclass as table_name,
       seq_scan,
       seq_tup_read,
       idx_scan,
       idx_tup_fetch,
       n_tup_ins,
       n_tup_upd,
       n_tup_del,
       n_tup_hot_upd,
       n_live_tup,
       n_dead_tup,
       n_mod_since_analyze,
       vacuum_count,
       autovacuum_count,
       analyze_count,
       autoanalyze_count
from pg_stat_user_tables
where relname in ('events', 'tenants', 'users', 'global_users')
order by relname;
""",
        csv_output=True,
        output_file=run_dir / "snapshots" / f"{phase}_pg_stat_user_tables.csv",
    )


def _write_pg_statio_user_indexes_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    run_psql(
        settings,
        sql="""
select relid::regclass as table_name,
       indexrelid::regclass as index_name,
       idx_blks_read,
       idx_blks_hit
from pg_statio_user_indexes
where relname in ('events', 'tenants', 'users', 'global_users')
order by relname, indexrelname;
""",
        csv_output=True,
        output_file=run_dir / "snapshots" / f"{phase}_pg_statio_user_indexes.csv",
    )


def _write_pg_stat_user_indexes_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    run_psql(
        settings,
        sql="""
select relid::regclass as table_name,
       indexrelid::regclass as index_name,
       idx_scan,
       idx_tup_read,
       idx_tup_fetch
from pg_stat_user_indexes
where relname in ('events', 'tenants', 'users', 'global_users')
order by relname, indexrelname;
""",
        csv_output=True,
        output_file=run_dir / "snapshots" / f"{phase}_pg_stat_user_indexes.csv",
    )


def _write_pg_stat_statements_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    output_file = run_dir / "snapshots" / f"{phase}_pg_stat_statements.csv"
    if not _relation_exists(settings, "pg_stat_statements"):
        _write_unavailable_csv(output_file)
        return

    try:
        run_psql(
            settings,
            sql="""
select true as available,
       queryid,
       calls,
       total_plan_time,
       mean_plan_time,
       total_exec_time,
       mean_exec_time,
       rows,
       shared_blks_hit,
       shared_blks_read,
       shared_blks_dirtied,
       shared_blks_written,
       temp_blks_read,
       temp_blks_written,
       shared_blk_read_time,
       shared_blk_write_time,
       temp_blk_read_time,
       temp_blk_write_time,
       wal_records,
       wal_fpi,
       wal_bytes
from pg_stat_statements
where dbid = (select oid from pg_database where datname = current_database())
order by total_exec_time desc, queryid;
""",
            csv_output=True,
            output_file=output_file,
        )
    except subprocess.CalledProcessError as error:
        _write_unavailable_csv(output_file, error.stderr.strip())


def _write_citus_stat_statements_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    output_file = run_dir / "snapshots" / f"{phase}_citus_stat_statements.csv"
    if not _relation_exists(settings, "citus_stat_statements"):
        _write_unavailable_csv(output_file)
        return

    try:
        run_psql(
            settings,
            sql="""
select true as available,
       queryid,
       userid::regrole as user_name,
       dbid,
       executor,
       calls
from citus_stat_statements
where dbid = (select oid from pg_database where datname = current_database())
order by calls desc, queryid;
""",
            csv_output=True,
            output_file=output_file,
        )
    except subprocess.CalledProcessError as error:
        _write_unavailable_csv(output_file, error.stderr.strip())


def _write_citus_stat_counters_csv(settings: Settings, run_dir: Path, phase: str) -> None:
    output_file = run_dir / "snapshots" / f"{phase}_citus_stat_counters.csv"
    if not _relation_exists(settings, "citus_stat_counters"):
        _write_unavailable_csv(output_file)
        return

    try:
        run_psql(
            settings,
            sql="""
select true as available,
       oid as database_oid,
       name,
       connection_establishment_succeeded,
       connection_establishment_failed,
       connection_reused,
       query_execution_single_shard,
       query_execution_multi_shard,
       stats_reset
from citus_stat_counters
where name = current_database()
order by name;
""",
            csv_output=True,
            output_file=output_file,
        )
    except subprocess.CalledProcessError as error:
        _write_unavailable_csv(output_file, error.stderr.strip())


def _write_postgres_structured_snapshots(settings: Settings, run_dir: Path, phase: str) -> None:
    _write_pg_settings_relevant_csv(settings, run_dir, phase)
    _write_pg_stat_io_csv(settings, run_dir, phase)
    _write_pg_stat_database_csv(settings, run_dir, phase)
    _write_pg_stat_user_tables_csv(settings, run_dir, phase)
    _write_pg_stat_user_indexes_csv(settings, run_dir, phase)
    _write_pg_statio_user_tables_csv(settings, run_dir, phase)
    _write_pg_statio_user_indexes_csv(settings, run_dir, phase)
    _write_pg_stat_statements_csv(settings, run_dir, phase)
    if settings.bench_node_role == "coordinator":
        _write_citus_stat_counters_csv(settings, run_dir, phase)
        _write_citus_stat_statements_csv(settings, run_dir, phase)


def _snapshot_metadata(settings: Settings, run_dir: Path, phase: str) -> None:
    snapshots = run_dir / "snapshots"
    _write_dataset_parameters(settings, run_dir, phase)
    _write_postgres_structured_snapshots(settings, run_dir, phase)
    run_psql(
        settings,
        sql="select version(); select citus_version();",
        output_file=snapshots / f"{phase}_versions.txt",
    )
    run_psql(
        settings,
        sql_file=ROOT_DIR / "sql" / "metadata" / "citus_snapshot.sql",
        output_file=snapshots / f"{phase}_citus_snapshot.txt",
    )
    run_psql(
        settings,
        sql_file=ROOT_DIR / "sql" / "metadata" / "postgres_snapshot.sql",
        output_file=snapshots / f"{phase}_postgres_snapshot.txt",
    )


def _snapshot_postgres_only(settings: Settings, run_dir: Path, phase: str) -> None:
    snapshots = run_dir / "snapshots"
    _write_dataset_parameters(settings, run_dir, phase)
    _write_postgres_structured_snapshots(settings, run_dir, phase)
    run_psql(
        settings,
        sql="select version();",
        output_file=snapshots / f"{phase}_versions.txt",
    )
    run_psql(
        settings,
        sql_file=ROOT_DIR / "sql" / "metadata" / "postgres_snapshot.sql",
        output_file=snapshots / f"{phase}_postgres_snapshot.txt",
    )


def _snapshot_capture_metadata(settings: Settings, run_dir: Path, phase: str) -> None:
    if settings.bench_node_role == "coordinator":
        _snapshot_metadata(settings, run_dir, phase)
        return
    _snapshot_postgres_only(settings, run_dir, phase)


def _snapshot_query_metrics(settings: Settings, run_dir: Path, phase: str) -> None:
    _write_pg_stat_io_csv(settings, run_dir, phase)
    _write_pg_stat_database_csv(settings, run_dir, phase)
    _write_pg_stat_user_tables_csv(settings, run_dir, phase)
    _write_pg_stat_user_indexes_csv(settings, run_dir, phase)
    _write_pg_statio_user_tables_csv(settings, run_dir, phase)
    _write_pg_statio_user_indexes_csv(settings, run_dir, phase)
    _write_pg_stat_statements_csv(settings, run_dir, phase)
    if settings.bench_node_role == "coordinator":
        _write_citus_stat_counters_csv(settings, run_dir, phase)
        _write_citus_stat_statements_csv(settings, run_dir, phase)


def _build_explain_text_sql(sql_file: Path) -> str:
    sql = sql_file.read_text(encoding="utf-8").strip().rstrip(";")
    return f"EXPLAIN (BUFFERS, VERBOSE)\n{sql};\n"


def _build_explain_analyze_json_sql(sql_file: Path) -> str:
    sql = sql_file.read_text(encoding="utf-8").strip().rstrip(";")
    return f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)\n{sql};\n"


def _build_explain_text_sql_for_query(sql: str) -> str:
    return f"EXPLAIN (BUFFERS, VERBOSE)\n{sql.strip().rstrip(';')};\n"


def _build_explain_analyze_json_sql_for_query(sql: str) -> str:
    return f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)\n{sql.strip().rstrip(';')};\n"


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _walk_json_objects(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_objects(child)


def _region_from_fdw_schema(schema: str) -> str:
    if not schema.startswith("fdw_"):
        return ""
    return schema.removeprefix("fdw_").lower()


def _default_fdw_remote_plan_region() -> str:
    return os.getenv("BENCH_FDW_REMOTE_PLAN_DEFAULT_REGION", "").strip().lower()


def _fdw_schemas_in_plan(plan_json: object) -> list[str]:
    schemas = {
        str(node.get("Schema") or "")
        for node in _walk_json_objects(plan_json)
        if str(node.get("Schema") or "").startswith("fdw_")
    }
    return sorted(schemas)


def _fallback_relation_name(remote_sql: str) -> str:
    relations = sorted(set(re.findall(r"\bpublic\.([A-Za-z_][A-Za-z0-9_]*)\b", remote_sql)))
    return relations[0] if len(relations) == 1 else ""


def _extract_fdw_remote_sql(plan_json: object) -> list[dict[str, str]]:
    remote_queries: list[dict[str, str]] = []
    fallback_schemas = _fdw_schemas_in_plan(plan_json)
    fallback_schema = fallback_schemas[0] if len(fallback_schemas) == 1 else ""
    for node in _walk_json_objects(plan_json):
        remote_sql = str(node.get("Remote SQL") or "").strip()
        if not remote_sql:
            continue

        schema = str(node.get("Schema") or "") or fallback_schema
        region = _region_from_fdw_schema(schema) or _default_fdw_remote_plan_region()
        relation_name = str(node.get("Relation Name") or "") or _fallback_relation_name(remote_sql)
        remote_queries.append(
            {
                "remote_sql_id": f"remote_{len(remote_queries) + 1:03d}",
                "node_type": str(node.get("Node Type") or ""),
                "schema": schema,
                "region": region,
                "relation_name": relation_name,
                "alias": str(node.get("Alias") or ""),
                "remote_sql": remote_sql,
            }
        )
    return remote_queries


def _remote_region_settings(settings: Settings, region: str) -> Settings:
    prefix = f"REGION_{region.upper()}_POSTGRES_"
    host = os.getenv(prefix + "HOST", "")
    database = os.getenv(prefix + "DB", "")
    user = os.getenv(prefix + "USER", "")
    missing = [
        name
        for name, value in {
            prefix + "HOST": host,
            prefix + "DB": database,
            prefix + "USER": user,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Missing remote PostgreSQL env variables: {', '.join(missing)}")

    return replace(
        settings,
        pg_host=host,
        pg_port=int(os.getenv(prefix + "PORT", "5432")),
        pg_database=database,
        pg_user=user,
        pg_password=os.getenv(prefix + "PASSWORD", ""),
        pg_sslmode=os.getenv(prefix + "SSLMODE", "verify-ca"),
        pg_sslrootcert=os.getenv(prefix + "SSLROOTCERT", ""),
    )


def _relative_path(path: Path, base_dir: Path) -> str:
    return str(path.relative_to(base_dir))


def _collect_fdw_remote_plan_probes(
    settings: Settings,
    *,
    run_dir: Path,
    query_name: str,
    plan_json: object,
) -> dict[str, object]:
    enabled = _env_bool("BENCH_FDW_REMOTE_PLAN_PROBE", default=True)
    remote_queries = _extract_fdw_remote_sql(plan_json)
    manifest: dict[str, object] = {
        "enabled": enabled,
        "remote_sql_count": len(remote_queries),
        "status": "pending",
        "probes": [],
    }
    if not enabled:
        manifest["status"] = "disabled"
        return manifest
    if not remote_queries:
        manifest["status"] = "skipped"
        return manifest

    remote_dir = run_dir / "plans" / "remote"
    remote_dir.mkdir(parents=True, exist_ok=True)
    remote_pgoptions = os.getenv(
        "BENCH_FDW_REMOTE_PLAN_PGOPTIONS",
        "-c citus.explain_all_tasks=on",
    )
    remote_extra_env = {"PGOPTIONS": remote_pgoptions} if remote_pgoptions else {}
    manifest["pgoptions"] = remote_pgoptions
    probes: list[dict[str, object]] = []

    for remote_query in remote_queries:
        remote_sql_id = remote_query["remote_sql_id"]
        remote_sql = remote_query["remote_sql"]
        region = remote_query["region"]
        probe_manifest: dict[str, object] = {
            key: value for key, value in remote_query.items() if key != "remote_sql"
        }
        probe_manifest["status"] = "pending"

        remote_sql_file = remote_dir / f"{query_name}.{remote_sql_id}.remote.sql"
        text_sql_file = remote_dir / f"{query_name}.{remote_sql_id}.explain.text.sql"
        text_plan_file = remote_dir / f"{query_name}.{remote_sql_id}.explain.txt"
        analyze_sql_file = remote_dir / f"{query_name}.{remote_sql_id}.explain.analyze.json.sql"
        json_plan_file = remote_dir / f"{query_name}.{remote_sql_id}.explain.json"

        remote_sql_file.write_text(remote_sql.rstrip(";") + ";\n", encoding="utf-8")
        text_sql = _build_explain_text_sql_for_query(remote_sql)
        analyze_sql = _build_explain_analyze_json_sql_for_query(remote_sql)
        text_sql_file.write_text(text_sql, encoding="utf-8")
        analyze_sql_file.write_text(analyze_sql, encoding="utf-8")

        probe_manifest.update(
            {
                "remote_sql_file": _relative_path(remote_sql_file, run_dir),
                "explain_text_sql_file": _relative_path(text_sql_file, run_dir),
                "explain_text_file": _relative_path(text_plan_file, run_dir),
                "explain_analyze_json_sql_file": _relative_path(analyze_sql_file, run_dir),
                "plan_file": _relative_path(json_plan_file, run_dir),
            }
        )

        if not region:
            probe_manifest["status"] = "skipped"
            probe_manifest["error"] = (
                "Cannot infer region from FDW schema name and "
                "BENCH_FDW_REMOTE_PLAN_DEFAULT_REGION is not set."
            )
            probes.append(probe_manifest)
            continue

        try:
            remote_settings = _remote_region_settings(settings, region)
            text_result = run_psql(
                remote_settings,
                sql=text_sql,
                extra_env=remote_extra_env,
                no_psqlrc=True,
            )
            text_plan_file.write_text(text_result.stdout, encoding="utf-8")
            if text_result.stderr.strip():
                stderr_file = remote_dir / f"{query_name}.{remote_sql_id}.explain.text.stderr.log"
                stderr_file.write_text(text_result.stderr, encoding="utf-8")
                probe_manifest["explain_text_stderr_file"] = _relative_path(stderr_file, run_dir)

            analyze_result = run_psql(
                remote_settings,
                sql=analyze_sql,
                extra_env=remote_extra_env,
                no_psqlrc=True,
                quiet=True,
                tuples_only=True,
                unaligned=True,
            )
            remote_plan_json = json.loads(analyze_result.stdout.strip())
            json_plan_file.write_text(
                json.dumps(remote_plan_json, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if analyze_result.stderr.strip():
                stderr_file = remote_dir / f"{query_name}.{remote_sql_id}.explain.stderr.log"
                stderr_file.write_text(analyze_result.stderr, encoding="utf-8")
                probe_manifest["explain_stderr_file"] = _relative_path(stderr_file, run_dir)

            probe_manifest["status"] = "ok"
            probe_manifest["diagnostic_timing"] = {
                "explain_text_elapsed_seconds": f"{text_result.elapsed_seconds:.6f}",
                "explain_analyze_elapsed_seconds": f"{analyze_result.elapsed_seconds:.6f}",
            }
        except (ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
            probe_manifest["status"] = "failed"
            probe_manifest["error"] = str(error)
            if isinstance(error, subprocess.CalledProcessError):
                stdout_file = remote_dir / f"{query_name}.{remote_sql_id}.failed.stdout.log"
                stderr_file = remote_dir / f"{query_name}.{remote_sql_id}.failed.stderr.log"
                stdout_file.write_text(error.stdout or "", encoding="utf-8")
                stderr_file.write_text(error.stderr or "", encoding="utf-8")
                probe_manifest["failed_stdout_file"] = _relative_path(stdout_file, run_dir)
                probe_manifest["failed_stderr_file"] = _relative_path(stderr_file, run_dir)

        probes.append(probe_manifest)

    manifest["probes"] = probes
    probe_statuses = {str(probe.get("status", "")) for probe in probes}
    if probe_statuses == {"ok"}:
        manifest["status"] = "ok"
    elif "failed" in probe_statuses:
        manifest["status"] = "failed" if probe_statuses == {"failed"} else "partial"
    elif "skipped" in probe_statuses:
        manifest["status"] = "skipped" if probe_statuses == {"skipped"} else "partial"
    else:
        manifest["status"] = "unknown"
    return manifest


def _write_query_timing(run_dir: Path, row: dict[str, str]) -> None:
    fieldnames = [
        "query_name",
        "iteration_type",
        "iteration",
        "elapsed_seconds",
        "query_started_at_unix",
        "query_finished_at_unix",
        "result_file",
    ]
    timings_file = run_dir / "results" / "query_timings.csv"
    with timings_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)

    timing_file = run_dir / "results" / "query_timing.csv"
    with timing_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "query_name",
                "elapsed_seconds",
                "query_started_at_unix",
                "query_finished_at_unix",
                "result_file",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "query_name": row["query_name"],
                "elapsed_seconds": row["elapsed_seconds"],
                "query_started_at_unix": row["query_started_at_unix"],
                "query_finished_at_unix": row["query_finished_at_unix"],
                "result_file": row["result_file"],
            }
        )
    _write_timing_summary([row], run_dir / "results" / "query_summary.csv")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _write_timing_summary(rows: list[dict[str, str]], output_file: Path) -> None:
    summary_rows = [row for row in rows if row["iteration_type"] == "measurement"]
    if not summary_rows:
        summary_rows = rows

    by_query: dict[str, list[float]] = {}
    for row in summary_rows:
        by_query.setdefault(row["query_name"], []).append(float(row["elapsed_seconds"]))

    with output_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "query_name",
                "n",
                "mean_seconds",
                "median_seconds",
                "stddev_seconds",
                "min_seconds",
                "max_seconds",
                "p95_seconds",
                "p99_seconds",
                "coefficient_of_variation",
            ],
        )
        writer.writeheader()
        for query_name, values in sorted(by_query.items()):
            mean_value = statistics.fmean(values)
            stddev_value = statistics.stdev(values) if len(values) > 1 else 0.0
            writer.writerow(
                {
                    "query_name": query_name,
                    "n": len(values),
                    "mean_seconds": f"{mean_value:.6f}",
                    "median_seconds": f"{statistics.median(values):.6f}",
                    "stddev_seconds": f"{stddev_value:.6f}",
                    "min_seconds": f"{min(values):.6f}",
                    "max_seconds": f"{max(values):.6f}",
                    "p95_seconds": f"{_percentile(values, 0.95):.6f}",
                    "p99_seconds": f"{_percentile(values, 0.99):.6f}",
                    "coefficient_of_variation": (
                        "0.000000" if mean_value == 0 else f"{stddev_value / mean_value:.6f}"
                    ),
                }
            )


def _iteration_result_file(
    run_dir: Path,
    query_name: str,
    iteration_type: str,
    iteration: int,
) -> Path:
    if iteration_type == "measurement" and iteration == 1:
        return run_dir / "results" / f"{query_name}.result.csv"
    return Path(os.devnull)


def _result_file_label(output_file: Path) -> str:
    if output_file == Path(os.devnull):
        return ""
    return output_file.name


def snapshot_metadata(settings: Settings, *, label: str) -> str:
    run_dir = create_run_dir(settings, mode="snapshot-metadata", label=label)
    _snapshot_metadata(settings, run_dir, "single")
    return str(run_dir)


def capture_window(settings: Settings, *, label: str, duration_seconds: float | None) -> str:
    duration = duration_seconds or settings.bench_capture_duration_seconds
    if duration <= 0:
        raise ValueError("capture-window duration must be greater than 0.")

    run_dir = create_run_dir(settings, mode="capture-window", label=label)
    _reset_statement_stats(settings)
    _snapshot_capture_metadata(settings, run_dir, "before")

    sampler = OsSampler(
        output_file=run_dir / "metrics" / "os_samples.jsonl",
        interval_seconds=settings.bench_sample_interval_seconds,
    )
    sampler.start()
    try:
        time.sleep(duration)
    finally:
        sampler.stop()

    os_summary = summarize_samples(run_dir / "metrics" / "os_samples.jsonl")
    (run_dir / "metrics" / "os_summary.json").write_text(
        json.dumps(os_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _snapshot_capture_metadata(settings, run_dir, "after")
    return str(run_dir)


def _active_session_file(settings: Settings, label: str) -> Path:
    return settings.run_root / ".active" / f"{_safe_label(label)}.json"


def capture_agent(settings: Settings, *, run_dir: Path, stop_file: Path) -> str:
    output_file = run_dir / "metrics" / "os_samples.jsonl"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("a", encoding="utf-8") as handle:
        first_sample = True
        while not stop_file.exists():
            handle.write(
                json.dumps(
                    collect_sample(include_qdisc=first_sample),
                    sort_keys=True,
                )
                + "\n"
            )
            handle.flush()
            first_sample = False
            time.sleep(settings.bench_sample_interval_seconds)
        handle.write(
            json.dumps(
                collect_sample(include_qdisc=True),
                sort_keys=True,
            )
            + "\n"
        )
        handle.flush()
    return str(run_dir)


def query_capture_start(
    settings: Settings,
    *,
    label: str,
    capture_db_snapshots: bool = False,
    capture_os_samples: bool = False,
) -> str:
    session_file = _active_session_file(settings, label)
    if session_file.exists():
        raise RuntimeError(f"Capture session already exists for label: {label}")

    run_dir = create_run_dir(settings, mode="query-capture", label=label)
    control_dir = run_dir / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    stop_file = control_dir / "stop"
    agent_log = run_dir / "logs" / "capture-agent.log"

    if capture_db_snapshots:
        _reset_statement_stats(settings)
        _snapshot_query_metrics(settings, run_dir, "before")

    process: subprocess.Popen[bytes] | None = None
    if capture_os_samples:
        command = [
            sys.executable,
            str(ROOT_DIR / "main.py"),
            "capture-agent",
            "--run-dir",
            str(run_dir),
            "--stop-file",
            str(stop_file),
        ]
        with agent_log.open("ab") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=ROOT_DIR,
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
            )

    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(
        json.dumps(
            {
                "kind": "query-capture",
                "label": label,
                "run_dir": str(run_dir),
                "stop_file": str(stop_file) if capture_os_samples else None,
                "pid": process.pid if process is not None else None,
                "started_at_unix": time.time(),
                "capture_db_snapshots": capture_db_snapshots,
                "capture_os_samples": capture_os_samples,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return str(run_dir)


def query_capture_stop(
    settings: Settings,
    *,
    label: str,
    query_started_at_unix: float | None = None,
    query_finished_at_unix: float | None = None,
) -> str:
    session_file = _active_session_file(settings, label)
    if not session_file.exists():
        raise RuntimeError(f"No active query capture session exists for label: {label}")

    session = json.loads(session_file.read_text(encoding="utf-8"))
    run_dir = Path(session["run_dir"])
    stop_file = Path(session["stop_file"]) if session.get("stop_file") else None
    capture_db_snapshots = bool(session.get("capture_db_snapshots", True))
    capture_os_samples = bool(session.get("capture_os_samples", True))

    if capture_os_samples and stop_file is not None:
        stop_file.touch()
        time.sleep(max(0.25, settings.bench_sample_interval_seconds * 1.5))

        os_summary = summarize_samples(run_dir / "metrics" / "os_samples.jsonl")
        (run_dir / "metrics" / "os_summary.json").write_text(
            json.dumps(os_summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if (
            query_started_at_unix is not None
            and query_finished_at_unix is not None
        ):
            query_summary = summarize_samples(
                run_dir / "metrics" / "os_samples.jsonl",
                window_started_at_unix=query_started_at_unix,
                window_finished_at_unix=query_finished_at_unix,
            )
            (run_dir / "metrics" / "os_query_summary.json").write_text(
                json.dumps(query_summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    if capture_db_snapshots:
        _snapshot_query_metrics(settings, run_dir, "after")
    session_file.unlink()
    return str(run_dir)


def _active_query_run_dir(settings: Settings, label: str) -> Path | None:
    session_file = _active_session_file(settings, label)
    if not session_file.exists():
        return None
    session = json.loads(session_file.read_text(encoding="utf-8"))
    return Path(session["run_dir"])


def explain_sql(
    settings: Settings,
    *,
    label: str,
    sql_file: Path,
    variables: dict[str, str],
    run_dir: Path | None = None,
    citus_explain_all_tasks: bool = True,
    pg_options: list[str] | None = None,
) -> str:
    effective_run_dir = run_dir or _active_query_run_dir(settings, label)
    if effective_run_dir is None:
        effective_run_dir = create_run_dir(settings, mode="explain-sql", label=label)

    effective_run_dir.mkdir(parents=True, exist_ok=True)
    for child in ("queries", "results", "plans", "metrics", "logs", "snapshots"):
        (effective_run_dir / child).mkdir(parents=True, exist_ok=True)

    query_name = sql_file.stem
    query_copy = effective_run_dir / "queries" / sql_file.name
    shutil.copy2(sql_file, query_copy)

    explain_text_sql = _build_explain_text_sql(sql_file)
    explain_text_sql_file = effective_run_dir / "plans" / f"{query_name}.explain.text.sql"
    explain_text_sql_file.write_text(explain_text_sql, encoding="utf-8")

    explain_analyze_json_sql = _build_explain_analyze_json_sql(sql_file)
    explain_analyze_json_sql_file = (
        effective_run_dir / "plans" / f"{query_name}.explain.analyze.json.sql"
    )
    explain_analyze_json_sql_file.write_text(explain_analyze_json_sql, encoding="utf-8")

    text_plan_file = effective_run_dir / "plans" / f"{query_name}.explain.txt"
    plan_file = effective_run_dir / "plans" / f"{query_name}.explain.json"
    effective_pg_options = list(pg_options or [])
    if citus_explain_all_tasks:
        effective_pg_options.append("citus.explain_all_tasks=on")
    pgoptions = " ".join(f"-c {option}" for option in effective_pg_options)

    text_result = run_psql(
        settings,
        sql=explain_text_sql,
        variables=variables,
        extra_env={"PGOPTIONS": pgoptions},
        no_psqlrc=True,
    )
    text_plan_file.write_text(text_result.stdout, encoding="utf-8")
    if text_result.stderr.strip():
        (effective_run_dir / "logs" / f"{query_name}.explain.text.stderr.log").write_text(
            text_result.stderr,
            encoding="utf-8",
        )

    result = run_psql(
        settings,
        sql=explain_analyze_json_sql,
        variables=variables,
        extra_env={"PGOPTIONS": pgoptions},
        no_psqlrc=True,
        quiet=True,
        tuples_only=True,
        unaligned=True,
    )
    raw_plan = result.stdout.strip()
    try:
        plan_json = json.loads(raw_plan)
    except json.JSONDecodeError as error:
        raw_file = effective_run_dir / "plans" / f"{query_name}.explain.raw.txt"
        raw_file.write_text(raw_plan + "\n", encoding="utf-8")
        raise RuntimeError(f"EXPLAIN output is not valid JSON: {raw_file}") from error
    plan_file.write_text(json.dumps(plan_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fdw_remote_plan_probe = _collect_fdw_remote_plan_probes(
        settings,
        run_dir=effective_run_dir,
        query_name=query_name,
        plan_json=plan_json,
    )

    timing_row = {
        "query_name": query_name,
        "iteration_type": "explain_analyze",
        "iteration": "1",
        "elapsed_seconds": f"{result.elapsed_seconds:.6f}",
        "query_started_at_unix": f"{result.started_at_unix:.6f}",
        "query_finished_at_unix": f"{result.finished_at_unix:.6f}",
        "result_file": plan_file.name,
    }
    _write_query_timing(effective_run_dir, timing_row)

    execution_manifest = {
        "label": label,
        "query_name": query_name,
        "sql_file": str(sql_file),
        "query_copy": str(query_copy.relative_to(effective_run_dir)),
        "explain_text_sql_file": str(explain_text_sql_file.relative_to(effective_run_dir)),
        "explain_text_file": str(text_plan_file.relative_to(effective_run_dir)),
        "explain_analyze_json_sql_file": str(
            explain_analyze_json_sql_file.relative_to(effective_run_dir)
        ),
        "explain_sql_file": str(
            explain_analyze_json_sql_file.relative_to(effective_run_dir)
        ),
        "plan_file": str(plan_file.relative_to(effective_run_dir)),
        "variables": variables,
        "explain_settings": {
            "citus.explain_all_tasks": citus_explain_all_tasks,
            "pg_options": effective_pg_options,
        },
        "fdw_remote_plan_probe": fdw_remote_plan_probe,
        "timing": timing_row,
    }
    (effective_run_dir / "execution_manifest.json").write_text(
        json.dumps(execution_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if result.stderr.strip():
        (effective_run_dir / "logs" / f"{query_name}.explain.stderr.log").write_text(
            result.stderr,
            encoding="utf-8",
        )
    return str(effective_run_dir)


def result_signature_sql(
    settings: Settings,
    *,
    label: str,
    sql_file: Path,
    variables: dict[str, str],
    run_dir: Path | None = None,
    pg_options: list[str] | None = None,
) -> str:
    effective_run_dir = run_dir or _active_query_run_dir(settings, label)
    if effective_run_dir is None:
        effective_run_dir = create_run_dir(settings, mode="result-signature", label=label)
    results_dir = effective_run_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    pgoptions = " ".join(f"-c {option}" for option in (pg_options or []))
    signature = calculate_result_signature(
        settings,
        sql_file=sql_file,
        variables=variables,
        extra_env={"PGOPTIONS": pgoptions},
    )
    payload = {
        "contract_version": "result-signature-v1",
        "canonicalization": "psql_csv_rows_order_independent_multiset",
        "database_result_rows_stored": False,
        "row_count": signature.row_count,
        "output_byte_count": signature.output_byte_count,
        "multiset_sha256": signature.multiset_sha256,
        "ordered_sha256": signature.ordered_sha256,
        "elapsed_seconds": signature.elapsed_seconds,
        "query_started_at_unix": signature.started_at_unix,
        "query_finished_at_unix": signature.finished_at_unix,
        "variables": variables,
        "pg_options": list(pg_options or []),
    }
    (results_dir / f"{sql_file.stem}.result-signature.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if signature.stderr.strip():
        (effective_run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (effective_run_dir / "logs" / f"{sql_file.stem}.result-signature.stderr.log").write_text(
            signature.stderr,
            encoding="utf-8",
        )
    return str(effective_run_dir)


def result_snapshot_sql(
    settings: Settings,
    *,
    label: str,
    sql_file: Path,
    variables: dict[str, str],
    run_dir: Path | None = None,
    pg_options: list[str] | None = None,
) -> str:
    effective_run_dir = run_dir or create_run_dir(
        settings,
        mode="result-snapshot",
        label=label,
    )
    results_dir = effective_run_dir / "results"
    pgoptions = " ".join(f"-c {option}" for option in (pg_options or []))
    snapshot = calculate_result_snapshot(
        settings,
        sql_file=sql_file,
        output_dir=results_dir,
        variables=variables,
        extra_env={"PGOPTIONS": pgoptions},
    )
    payload = {
        "contract_version": "result-snapshot-v1",
        "purpose": "bounded_correctness_recovery_only",
        "canonicalization": "psql_csv_typed_rows_order_independent_multiset",
        "database_result_rows_stored": True,
        "result_rows_file": str(snapshot.rows_file.relative_to(effective_run_dir)),
        "columns": [
            {"ordinal": index, "name": name, "postgres_type": postgres_type}
            for index, (name, postgres_type) in enumerate(snapshot.columns, start=1)
        ],
        "row_count": snapshot.row_count,
        "output_byte_count": snapshot.output_byte_count,
        "multiset_sha256": snapshot.multiset_sha256,
        "ordered_sha256": snapshot.ordered_sha256,
        "elapsed_seconds": snapshot.elapsed_seconds,
        "query_started_at_unix": snapshot.started_at_unix,
        "query_finished_at_unix": snapshot.finished_at_unix,
        "variables": variables,
        "pg_options": list(pg_options or []),
    }
    (results_dir / "result_snapshot.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if snapshot.stderr.strip():
        (effective_run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (effective_run_dir / "logs" / "result-snapshot.stderr.log").write_text(
            snapshot.stderr,
            encoding="utf-8",
        )
    return str(effective_run_dir)


def capture_start(settings: Settings, *, label: str) -> str:
    session_file = _active_session_file(settings, label)
    if session_file.exists():
        raise RuntimeError(f"Capture session already exists for label: {label}")

    run_dir = create_run_dir(settings, mode="capture-session", label=label)
    control_dir = run_dir / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    stop_file = control_dir / "stop"
    agent_log = run_dir / "logs" / "capture-agent.log"

    _reset_statement_stats(settings)
    _snapshot_capture_metadata(settings, run_dir, "before")

    command = [
        sys.executable,
        str(ROOT_DIR / "main.py"),
        "capture-agent",
        "--run-dir",
        str(run_dir),
        "--stop-file",
        str(stop_file),
    ]
    with agent_log.open("ab") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=ROOT_DIR,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )

    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(
        json.dumps(
            {
                "label": label,
                "run_dir": str(run_dir),
                "stop_file": str(stop_file),
                "pid": process.pid,
                "started_at_unix": time.time(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return str(run_dir)


def capture_stop(settings: Settings, *, label: str) -> str:
    session_file = _active_session_file(settings, label)
    if not session_file.exists():
        raise RuntimeError(f"No active capture session exists for label: {label}")

    session = json.loads(session_file.read_text(encoding="utf-8"))
    run_dir = Path(session["run_dir"])
    stop_file = Path(session["stop_file"])
    stop_file.touch()

    # Give the detached sampler one interval to notice the stop marker and write
    # the final sample. This keeps cross-node signaling simple and bounded.
    time.sleep(max(0.25, settings.bench_sample_interval_seconds * 1.5))

    os_summary = summarize_samples(run_dir / "metrics" / "os_samples.jsonl")
    (run_dir / "metrics" / "os_summary.json").write_text(
        json.dumps(os_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _snapshot_capture_metadata(settings, run_dir, "after")
    session_file.unlink()
    return str(run_dir)


def measure_sql(
    settings: Settings,
    *,
    label: str,
    sql_file: Path,
    variables: dict[str, str],
    pre_sleep_seconds: float,
    post_sleep_seconds: float,
    run_os_sampler: bool = False,
) -> str:
    run_dir = create_run_dir(settings, mode="measure-sql", label=label)
    shutil.copy2(sql_file, run_dir / "queries" / sql_file.name)
    _snapshot_metadata(settings, run_dir, "before")
    timing_rows: list[dict[str, str]] = []

    sampler = None
    if run_os_sampler:
        sampler = OsSampler(
            output_file=run_dir / "metrics" / "os_samples.jsonl",
            interval_seconds=settings.bench_sample_interval_seconds,
        )
        sampler.start()
    try:
        if pre_sleep_seconds > 0:
            time.sleep(pre_sleep_seconds)
        for iteration in range(1, settings.bench_warmup_iterations + 1):
            result_file = _iteration_result_file(run_dir, sql_file.stem, "warmup", iteration)
            result = run_psql(
                settings,
                sql_file=sql_file,
                variables=variables,
                csv_output=True,
                output_file=result_file,
            )
            timing_rows.append(
                {
                    "query_name": sql_file.stem,
                    "iteration_type": "warmup",
                    "iteration": str(iteration),
                    "elapsed_seconds": f"{result.elapsed_seconds:.6f}",
                    "query_started_at_unix": f"{result.started_at_unix:.6f}",
                    "query_finished_at_unix": f"{result.finished_at_unix:.6f}",
                    "result_file": _result_file_label(result_file),
                }
            )
            time.sleep(0.05)

        for iteration in range(1, settings.bench_measurement_iterations + 1):
            result_file = _iteration_result_file(
                run_dir, sql_file.stem, "measurement", iteration
            )
            result = run_psql(
                settings,
                sql_file=sql_file,
                variables=variables,
                csv_output=True,
                output_file=result_file,
            )
            timing_rows.append(
                {
                    "query_name": sql_file.stem,
                    "iteration_type": "measurement",
                    "iteration": str(iteration),
                    "elapsed_seconds": f"{result.elapsed_seconds:.6f}",
                    "query_started_at_unix": f"{result.started_at_unix:.6f}",
                    "query_finished_at_unix": f"{result.finished_at_unix:.6f}",
                    "result_file": _result_file_label(result_file),
                }
            )
            time.sleep(0.05)
        if post_sleep_seconds > 0:
            time.sleep(post_sleep_seconds)
    finally:
        if sampler is not None:
            sampler.stop()

    fieldnames = [
        "query_name",
        "iteration_type",
        "iteration",
        "elapsed_seconds",
        "query_started_at_unix",
        "query_finished_at_unix",
        "result_file",
    ]
    timings_file = run_dir / "results" / "query_timings.csv"
    with timings_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(timing_rows)

    timing_file = run_dir / "results" / "query_timing.csv"
    measurement_rows = [row for row in timing_rows if row["iteration_type"] == "measurement"]
    with timing_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "query_name",
                "elapsed_seconds",
                "query_started_at_unix",
                "query_finished_at_unix",
                "result_file",
            ],
        )
        writer.writeheader()
        if measurement_rows:
            first_measurement = measurement_rows[0]
            writer.writerow(
                {
                    "query_name": first_measurement["query_name"],
                    "elapsed_seconds": first_measurement["elapsed_seconds"],
                    "query_started_at_unix": first_measurement["query_started_at_unix"],
                    "query_finished_at_unix": first_measurement["query_finished_at_unix"],
                    "result_file": first_measurement["result_file"],
                }
            )
    _write_timing_summary(timing_rows, run_dir / "results" / "query_summary.csv")

    if run_os_sampler:
        os_summary = summarize_samples(run_dir / "metrics" / "os_samples.jsonl")
        (run_dir / "metrics" / "os_summary.json").write_text(
            json.dumps(os_summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    _snapshot_metadata(settings, run_dir, "after")
    return str(run_dir)


def measure_baseline(settings: Settings, *, label: str) -> str:
    run_dir = create_run_dir(settings, mode="measure-baseline", label=label)
    queries = baseline_queries()
    for query in queries:
        _copy_query(run_dir, query)

    _reset_statement_stats(settings)
    _snapshot_metadata(settings, run_dir, "before")
    sampler = OsSampler(
        output_file=run_dir / "metrics" / "os_samples.jsonl",
        interval_seconds=settings.bench_sample_interval_seconds,
    )

    timings_path = run_dir / "results" / "query_timings.csv"
    timing_rows: list[dict[str, str]] = []
    with timings_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "query_name",
                "iteration_type",
                "iteration",
                "elapsed_seconds",
                "query_started_at_unix",
                "query_finished_at_unix",
                "result_file",
            ],
        )
        writer.writeheader()

        sampler.start()
        try:
            for query in queries:
                for iteration in range(1, settings.bench_warmup_iterations + 1):
                    result_file = _iteration_result_file(
                        run_dir, query.name, "warmup", iteration
                    )
                    result = run_psql(
                        settings,
                        sql_file=query.path,
                        variables=query.variables,
                        csv_output=True,
                        output_file=result_file,
                    )
                    row = {
                        "query_name": query.name,
                        "iteration_type": "warmup",
                        "iteration": str(iteration),
                        "elapsed_seconds": f"{result.elapsed_seconds:.6f}",
                        "query_started_at_unix": f"{result.started_at_unix:.6f}",
                        "query_finished_at_unix": f"{result.finished_at_unix:.6f}",
                        "result_file": _result_file_label(result_file),
                    }
                    writer.writerow(row)
                    timing_rows.append(row)

                for iteration in range(1, settings.bench_measurement_iterations + 1):
                    result_file = _iteration_result_file(
                        run_dir, query.name, "measurement", iteration
                    )
                    result = run_psql(
                        settings,
                        sql_file=query.path,
                        variables=query.variables,
                        csv_output=True,
                        output_file=result_file,
                    )
                    row = {
                        "query_name": query.name,
                        "iteration_type": "measurement",
                        "iteration": str(iteration),
                        "elapsed_seconds": f"{result.elapsed_seconds:.6f}",
                        "query_started_at_unix": f"{result.started_at_unix:.6f}",
                        "query_finished_at_unix": f"{result.finished_at_unix:.6f}",
                        "result_file": _result_file_label(result_file),
                    }
                    writer.writerow(row)
                    timing_rows.append(row)
                    handle.flush()
                    time.sleep(0.05)
        finally:
            sampler.stop()

    _write_timing_summary(timing_rows, run_dir / "results" / "query_summary.csv")
    os_summary = summarize_samples(run_dir / "metrics" / "os_samples.jsonl")
    (run_dir / "metrics" / "os_summary.json").write_text(
        json.dumps(os_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _snapshot_metadata(settings, run_dir, "after")
    return str(run_dir)


def profile_baseline(settings: Settings, *, label: str) -> str:
    run_dir = create_run_dir(settings, mode="profile-baseline", label=label)
    for query in baseline_queries():
        _copy_query(run_dir, query)
        sql = query.path.read_text(encoding="utf-8").strip().rstrip(";")
        explain_sql = f"explain (analyze, buffers, verbose, format text)\n{sql};"
        run_psql(
            settings,
            sql=explain_sql,
            variables=query.variables,
            output_file=run_dir / "plans" / f"{query.name}.explain.txt",
        )
        explain_json_sql = f"explain (analyze, buffers, verbose, format json)\n{sql};"
        run_psql(
            settings,
            sql=explain_json_sql,
            variables=query.variables,
            output_file=run_dir / "plans" / f"{query.name}.explain.json",
        )
    _snapshot_metadata(settings, run_dir, "single")
    return str(run_dir)
