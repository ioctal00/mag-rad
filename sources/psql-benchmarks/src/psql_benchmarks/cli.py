from __future__ import annotations

from pathlib import Path

from .etl import gac_etl_bootstrap
from .fdw import fdw_bootstrap
from .flows import (
    capture_agent,
    capture_start,
    capture_stop,
    capture_window,
    explain_sql,
    measure_baseline,
    measure_sql,
    profile_baseline,
    query_capture_start,
    query_capture_stop,
    result_signature_sql,
    result_snapshot_sql,
    snapshot_metadata,
)
from .settings import Settings


def _parse_variables(values: list[str]) -> dict[str, str]:
    variables: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Variables must use KEY=VALUE format: {value}")
        key, variable_value = value.split("=", 1)
        variables[key] = variable_value
    return variables


def run_cli(
    command: str,
    *,
    label: str,
    duration_seconds: float | None = None,
    run_dir: str | None = None,
    stop_file: str | None = None,
    sql_file: str | None = None,
    variables: list[str] | None = None,
    pre_sleep_seconds: float = 0,
    post_sleep_seconds: float = 0,
    run_os_sampler: bool = False,
    citus_explain_all_tasks: bool = True,
    pg_options: list[str] | None = None,
    capture_db_snapshots: bool = False,
    capture_os_samples: bool = False,
    fdw_region: str = "eu",
    fdw_schema: str | None = None,
    fdw_server_name: str | None = None,
    fdw_tables: list[str] | None = None,
    fdw_server_options: list[str] | None = None,
    etl_region: str = "eu",
    etl_source_schema: str | None = None,
    etl_schema: str = "etl",
    etl_lookback_days: int = 30,
    query_started_at_unix: float | None = None,
    query_finished_at_unix: float | None = None,
) -> int:
    settings = Settings.from_env()

    if command == "measure-baseline":
        run_dir = measure_baseline(settings, label=label)
    elif command == "snapshot-metadata":
        run_dir = snapshot_metadata(settings, label=label)
    elif command == "profile-baseline":
        run_dir = profile_baseline(settings, label=label)
    elif command == "capture-window":
        run_dir = capture_window(settings, label=label, duration_seconds=duration_seconds)
    elif command == "capture-start":
        run_dir = capture_start(settings, label=label)
    elif command == "capture-stop":
        run_dir = capture_stop(settings, label=label)
    elif command == "capture-agent":
        if run_dir is None or stop_file is None:
            raise ValueError("capture-agent requires --run-dir and --stop-file.")
        run_dir = capture_agent(settings, run_dir=Path(run_dir), stop_file=Path(stop_file))
    elif command == "query-capture-start":
        run_dir = query_capture_start(
            settings,
            label=label,
            capture_db_snapshots=capture_db_snapshots,
            capture_os_samples=capture_os_samples,
        )
    elif command == "query-capture-stop":
        run_dir = query_capture_stop(
            settings,
            label=label,
            query_started_at_unix=query_started_at_unix,
            query_finished_at_unix=query_finished_at_unix,
        )
    elif command == "explain-sql":
        if sql_file is None:
            raise ValueError("explain-sql requires --sql-file.")
        run_dir = explain_sql(
            settings,
            label=label,
            sql_file=Path(sql_file),
            variables=_parse_variables(variables or []),
            run_dir=Path(run_dir) if run_dir is not None else None,
            citus_explain_all_tasks=citus_explain_all_tasks,
            pg_options=pg_options or [],
        )
    elif command == "result-signature":
        if sql_file is None:
            raise ValueError("result-signature requires --sql-file.")
        run_dir = result_signature_sql(
            settings,
            label=label,
            sql_file=Path(sql_file),
            variables=_parse_variables(variables or []),
            run_dir=Path(run_dir) if run_dir is not None else None,
            pg_options=pg_options or [],
        )
    elif command == "result-snapshot":
        if sql_file is None:
            raise ValueError("result-snapshot requires --sql-file.")
        run_dir = result_snapshot_sql(
            settings,
            label=label,
            sql_file=Path(sql_file),
            variables=_parse_variables(variables or []),
            run_dir=Path(run_dir) if run_dir is not None else None,
            pg_options=pg_options or [],
        )
    elif command == "measure-sql":
        if sql_file is None:
            raise ValueError("measure-sql requires --sql-file.")
        run_dir = measure_sql(
            settings,
            label=label,
            sql_file=Path(sql_file),
            variables=_parse_variables(variables or []),
            pre_sleep_seconds=pre_sleep_seconds,
            post_sleep_seconds=post_sleep_seconds,
            run_os_sampler=run_os_sampler,
        )
    elif command == "fdw-bootstrap":
        run_dir = fdw_bootstrap(
            settings,
            label=label,
            region=fdw_region,
            schema=fdw_schema,
            server_name=fdw_server_name,
            tables=fdw_tables,
            server_options=fdw_server_options,
        )
    elif command == "gac-etl-bootstrap":
        run_dir = gac_etl_bootstrap(
            settings,
            label=label,
            region=etl_region,
            source_schema=etl_source_schema,
            etl_schema=etl_schema,
            lookback_days=etl_lookback_days,
        )
    else:
        raise ValueError(f"Unsupported command: {command}")

    print(f"Run directory: {run_dir}")
    return 0
