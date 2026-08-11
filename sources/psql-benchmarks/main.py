from __future__ import annotations

import argparse
import sys

from src.psql_benchmarks.cli import run_cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="psql-benchmarks",
        description="Benchmark harness for the thesis PostgreSQL/Citus setup.",
    )
    parser.add_argument(
        "command",
        choices=[
            "measure-baseline",
            "snapshot-metadata",
            "profile-baseline",
            "capture-window",
            "capture-start",
            "capture-stop",
            "capture-agent",
            "query-capture-start",
            "query-capture-stop",
            "explain-sql",
            "result-signature",
            "result-snapshot",
            "measure-sql",
            "fdw-bootstrap",
            "gac-etl-bootstrap",
        ],
        help="Program flow to execute.",
    )
    parser.add_argument(
        "--label",
        default="baseline",
        help="Human-readable run label included in the run directory name.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Capture duration in seconds for capture-window.",
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stop-file",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--query-started-at-unix",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--query-finished-at-unix",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--sql-file",
        default=None,
        help="SQL file to execute for measure-sql.",
    )
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        help="psql variable in KEY=VALUE format. May be repeated.",
    )
    parser.add_argument(
        "--pg-option",
        action="append",
        default=[],
        help="Session PostgreSQL option for explain-sql as NAME=VALUE. May be repeated.",
    )
    parser.add_argument(
        "--pre-sleep",
        type=float,
        default=0,
        help="Seconds to keep samplers running before measure-sql executes the query.",
    )
    parser.add_argument(
        "--post-sleep",
        type=float,
        default=0,
        help="Seconds to keep samplers running after measure-sql finishes the query.",
    )
    parser.add_argument(
        "--no-os-sampler",
        action="store_true",
        help=(
            "Compatibility flag. OS sampling is disabled by default for "
            "measure-sql/query-capture-start."
        ),
    )
    parser.add_argument(
        "--os-sampler",
        action="store_true",
        help=(
            "Opt in to local OS/network/disk sampling for profiling runs. "
            "Not part of the core thesis collection contract."
        ),
    )
    parser.add_argument(
        "--no-citus-explain-all-tasks",
        action="store_true",
        help="Do not set citus.explain_all_tasks=on for explain-sql.",
    )
    parser.add_argument(
        "--no-db-snapshots",
        action="store_true",
        help=(
            "Compatibility flag. Per-query PostgreSQL/Citus snapshots are "
            "disabled by default for query-capture-start/stop."
        ),
    )
    parser.add_argument(
        "--db-snapshots",
        action="store_true",
        help=(
            "Opt in to before/after PostgreSQL/Citus snapshots for "
            "query-capture-start/stop profiling runs."
        ),
    )
    parser.add_argument(
        "--fdw-region",
        default="eu",
        help="Remote region key for fdw-bootstrap, e.g. eu or us.",
    )
    parser.add_argument(
        "--fdw-schema",
        default=None,
        help="Local schema to create for imported foreign tables.",
    )
    parser.add_argument(
        "--fdw-server-name",
        default=None,
        help="Local postgres_fdw server name.",
    )
    parser.add_argument(
        "--fdw-table",
        action="append",
        default=[],
        help="Remote public table to import. May be repeated.",
    )
    parser.add_argument(
        "--fdw-server-option",
        action="append",
        default=[],
        help=(
            "postgres_fdw server option as NAME=VALUE. Supported options include "
            "fetch_size, use_remote_estimate, fdw_startup_cost, fdw_tuple_cost "
            "and libpq options."
        ),
    )
    parser.add_argument(
        "--etl-region",
        default="eu",
        help="Remote region key already imported through FDW for gac-etl-bootstrap.",
    )
    parser.add_argument(
        "--etl-source-schema",
        default=None,
        help="FDW source schema for gac-etl-bootstrap, e.g. fdw_eu.",
    )
    parser.add_argument(
        "--etl-schema",
        default="etl",
        help="Local ETL schema for gac-etl-bootstrap.",
    )
    parser.add_argument(
        "--etl-lookback-days",
        type=int,
        default=30,
        help="Remote event lookback window used to materialize local ETL rollups.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_cli(
        args.command,
        label=args.label,
        duration_seconds=args.duration,
        run_dir=args.run_dir,
        stop_file=args.stop_file,
        sql_file=args.sql_file,
        variables=args.var,
        pre_sleep_seconds=args.pre_sleep,
        post_sleep_seconds=args.post_sleep,
        run_os_sampler=args.os_sampler and not args.no_os_sampler,
        citus_explain_all_tasks=not args.no_citus_explain_all_tasks,
        pg_options=args.pg_option,
        capture_db_snapshots=args.db_snapshots and not args.no_db_snapshots,
        capture_os_samples=args.os_sampler and not args.no_os_sampler,
        fdw_region=args.fdw_region,
        fdw_schema=args.fdw_schema,
        fdw_server_name=args.fdw_server_name,
        fdw_tables=args.fdw_table or None,
        fdw_server_options=args.fdw_server_option,
        etl_region=args.etl_region,
        etl_source_schema=args.etl_source_schema,
        etl_schema=args.etl_schema,
        etl_lookback_days=args.etl_lookback_days,
        query_started_at_unix=args.query_started_at_unix,
        query_finished_at_unix=args.query_finished_at_unix,
    )


if __name__ == "__main__":
    sys.exit(main())
