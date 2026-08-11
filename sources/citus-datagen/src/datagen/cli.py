from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import random
import shutil
import subprocess

from .settings import DatagenSettings

DROP_DATASET_TABLES_SQL = (
    "drop table if exists events; "
    "drop table if exists users; "
    "drop table if exists global_users; "
    "drop table if exists tenants;"
)


def _build_psql_env(settings: DatagenSettings) -> dict[str, str]:
    env = {"PGPASSWORD": settings.postgres_password}
    if settings.postgres_ssl_mode:
        env["PGSSLMODE"] = settings.postgres_ssl_mode
    if settings.postgres_ssl_root_cert:
        env["PGSSLROOTCERT"] = settings.postgres_ssl_root_cert
    return env


def _run_psql(
    settings: DatagenSettings,
    *extra_args: str,
    sql: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _build_psql_env(settings)
    merged_env = {**os.environ, **env}
    command = [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        settings.postgres_host,
        "-p",
        str(settings.postgres_port),
        "-U",
        settings.postgres_user,
        "-d",
        settings.postgres_db,
        *extra_args,
    ]
    if sql is not None:
        command.extend(["-c", sql])
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
        env=merged_env,
    )


def _build_psql_command(settings: DatagenSettings, *extra_args: str) -> list[str]:
    return [
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        settings.postgres_host,
        "-p",
        str(settings.postgres_port),
        "-U",
        settings.postgres_user,
        "-d",
        settings.postgres_db,
        *extra_args,
    ]


def _psql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _table_exists(settings: DatagenSettings, table_name: str) -> bool:
    result = _run_psql(
        settings,
        "-tA",
        sql=(
            "select count(*) "
            "from information_schema.tables "
            f"where table_schema = 'public' and table_name = '{table_name}';"
        ),
    )
    return result.stdout.strip() == "1"


def _table_count(settings: DatagenSettings, table_name: str) -> int:
    if not _table_exists(settings, table_name):
        return 0
    result = _run_psql(settings, "-tA", sql=f"select count(*) from {table_name};")
    return int(result.stdout.strip())


def _dataset_tables_nonempty(settings: DatagenSettings) -> bool:
    return any(
        _table_count(settings, table_name) > 0
        for table_name in ("tenants", "users", "global_users", "events")
    )


def _ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _base_time(settings: DatagenSettings) -> datetime:
    if settings.datagen_base_time_unix > 0:
        return datetime.fromtimestamp(settings.datagen_base_time_unix, UTC)
    return datetime.now(UTC)


def _tenant_tier(tenant_id: int) -> str:
    if tenant_id % 20 == 0:
        return "enterprise"
    if tenant_id % 5 == 0:
        return "pro"
    return "standard"


def _tenant_status(tenant_id: int) -> str:
    if tenant_id % 97 == 0:
        return "suspended"
    if tenant_id % 31 == 0:
        return "inactive"
    return "active"


def _user_segment(user_id: int) -> str:
    segments = ("consumer", "professional", "power", "trial")
    return segments[(user_id - 1) % len(segments)]


def _user_status(user_id: int) -> str:
    if user_id % 53 == 0:
        return "suspended"
    if user_id % 17 == 0:
        return "inactive"
    return "active"


def _generate_tenants(settings: DatagenSettings) -> int:
    count = 0
    total = settings.datagen_tenant_end - settings.datagen_tenant_start + 1
    updated_at = _base_time(settings).isoformat()
    with settings.tenants_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "tenant_id",
                "region",
                "tenant_tier",
                "tenant_status",
                "updated_at",
                "dimension_version",
            ]
        )
        for tenant_id in range(settings.datagen_tenant_start, settings.datagen_tenant_end + 1):
            writer.writerow(
                [
                    tenant_id,
                    settings.datagen_region,
                    _tenant_tier(tenant_id),
                    _tenant_status(tenant_id),
                    updated_at,
                    1,
                ]
            )
            count += 1
            if count % settings.datagen_progress_every_tenants == 0:
                print(
                    "Generated tenants",
                    f"{count}/{total}",
                    f"path={settings.tenants_csv_path}",
                    flush=True,
                )
    return count


def _generate_users(settings: DatagenSettings) -> int:
    count = 0
    tenant_count = settings.datagen_tenant_end - settings.datagen_tenant_start + 1
    total = tenant_count * settings.datagen_users_per_tenant
    base_time = _base_time(settings)
    with settings.users_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "tenant_id",
                "user_id",
                "user_segment",
                "user_status",
                "signup_at",
                "updated_at",
            ]
        )
        for tenant_index, tenant_id in enumerate(
            range(settings.datagen_tenant_start, settings.datagen_tenant_end + 1)
        ):
            for user_id in range(1, settings.datagen_users_per_tenant + 1):
                signup_age_days = (
                    tenant_id * 17 + user_id * 31 + settings.datagen_random_seed
                ) % max(1, settings.datagen_lookback_days * 12 + 1)
                signup_at = base_time - timedelta(days=signup_age_days)
                writer.writerow(
                    [
                        tenant_id,
                        user_id,
                        _user_segment(user_id),
                        _user_status(user_id),
                        signup_at.isoformat(),
                        base_time.isoformat(),
                    ]
                )
                count += 1
            completed_tenants = tenant_index + 1
            if completed_tenants % settings.datagen_progress_every_tenants == 0:
                print(
                    "Generated users",
                    f"tenants={completed_tenants}/{tenant_count}",
                    f"users={count}/{total}",
                    f"path={settings.users_csv_path}",
                    flush=True,
                )
    return count


def _generate_global_users(settings: DatagenSettings) -> int:
    count = 0
    tenant_count = settings.datagen_tenant_end - settings.datagen_tenant_start + 1
    total = tenant_count * settings.datagen_global_users_per_tenant
    base_time = _base_time(settings)
    with settings.global_users_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "tenant_id",
                "user_id",
                "user_segment",
                "user_status",
                "home_region",
                "signup_at",
                "updated_at",
            ]
        )
        for tenant_index, tenant_id in enumerate(
            range(settings.datagen_tenant_start, settings.datagen_tenant_end + 1)
        ):
            for user_id in range(1, settings.datagen_global_users_per_tenant + 1):
                signup_age_days = (
                    tenant_id * 17 + user_id * 31 + settings.datagen_random_seed
                ) % max(1, settings.datagen_lookback_days * 12 + 1)
                signup_at = base_time - timedelta(days=signup_age_days)
                writer.writerow(
                    [
                        tenant_id,
                        user_id,
                        _user_segment(user_id),
                        _user_status(user_id),
                        settings.datagen_region,
                        signup_at.isoformat(),
                        base_time.isoformat(),
                    ]
                )
                count += 1
            completed_tenants = tenant_index + 1
            if completed_tenants % settings.datagen_progress_every_tenants == 0:
                print(
                    "Generated global_users",
                    f"tenants={completed_tenants}/{tenant_count}",
                    f"global_users={count}/{total}",
                    f"path={settings.global_users_csv_path}",
                    flush=True,
                )
    return count


def _generate_events(settings: DatagenSettings) -> int:
    count = 0
    tenant_count = settings.datagen_tenant_end - settings.datagen_tenant_start + 1
    total = tenant_count * settings.datagen_events_per_tenant
    base_time = _base_time(settings)
    with settings.events_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["event_id", "tenant_id", "user_id", "value", "created_at"])
        for tenant_index, tenant_id in enumerate(
            range(settings.datagen_tenant_start, settings.datagen_tenant_end + 1)
        ):
            tenant_rng = random.Random(settings.datagen_random_seed + tenant_id)
            for _ in range(settings.datagen_events_per_tenant):
                count += 1
                user_id = tenant_rng.randint(1, settings.datagen_users_per_tenant)
                value = round(tenant_rng.uniform(1.0, 1000.0), 2)
                age_days = tenant_rng.randint(0, settings.datagen_lookback_days)
                age_seconds = tenant_rng.randint(0, 86399)
                created_at = base_time - timedelta(days=age_days, seconds=age_seconds)
                writer.writerow(
                    [
                        count,
                        tenant_id,
                        user_id,
                        f"{value:.2f}",
                        created_at.isoformat(),
                    ]
                )
            completed_tenants = tenant_index + 1
            if completed_tenants % settings.datagen_progress_every_tenants == 0:
                print(
                    "Generated events",
                    f"tenants={completed_tenants}/{tenant_count}",
                    f"events={count}/{total}",
                    f"path={settings.events_csv_path}",
                    flush=True,
                )
    return count


def generate(settings: DatagenSettings) -> None:
    _ensure_output_dir(settings.output_dir)
    tenant_count = settings.tenant_count
    total_events = tenant_count * settings.datagen_events_per_tenant
    global_users_total: int | str = "disabled"
    if settings.datagen_enable_global_users:
        global_users_total = tenant_count * settings.datagen_global_users_per_tenant
    print(
        "Generating dataset",
        f"region={settings.datagen_region}",
        f"tenants={tenant_count}",
        f"users={tenant_count * settings.datagen_users_per_tenant}",
        f"global_users={global_users_total}",
        f"events={total_events}",
        f"output_dir={settings.output_dir}",
        flush=True,
    )
    tenants_count = _generate_tenants(settings)
    users_count = _generate_users(settings)
    global_users_count = (
        _generate_global_users(settings) if settings.datagen_enable_global_users else 0
    )
    events_count = _generate_events(settings)
    print(
        "Generated dataset",
        f"region={settings.datagen_region}",
        f"tenants={tenants_count}",
        f"users={users_count}",
        f"global_users={global_users_count}",
        f"events={events_count}",
        f"output_dir={settings.output_dir}",
        flush=True,
    )


def init_schema(settings: DatagenSettings) -> None:
    _run_psql(
        settings,
        "-v",
        f"datagen_shard_count={settings.datagen_shard_count}",
        "-f",
        str(settings.schema_path),
    )
    print(f"Schema initialized from {settings.schema_path}", flush=True)


def _load_csv(settings: DatagenSettings, table: str, columns: str, csv_path: Path) -> None:
    _run_psql(
        settings,
        sql=f"\\copy {table} {columns} from '{csv_path}' csv header",
    )
    print(f"Loaded {csv_path} into {table}", flush=True)


def _insert_tenants_sql(settings: DatagenSettings) -> None:
    _run_psql(
        settings,
        sql=(
            "insert into tenants "
            "(tenant_id, region, tenant_tier, tenant_status, updated_at, dimension_version) "
            "select "
            "tenant_id, "
            f"{_psql_literal(settings.datagen_region)}, "
            "case when tenant_id % 20 = 0 then 'enterprise' "
            "when tenant_id % 5 = 0 then 'pro' "
            "else 'standard' end, "
            "case when tenant_id % 97 = 0 then 'suspended' "
            "when tenant_id % 31 = 0 then 'inactive' "
            "else 'active' end, "
            "statement_timestamp(), "
            "1 "
            "from generate_series("
            f"{settings.datagen_tenant_start}, {settings.datagen_tenant_end}"
            ") as tenant_id;"
        ),
    )
    tenant_count = settings.datagen_tenant_end - settings.datagen_tenant_start + 1
    print(f"Inserted tenants via SQL rows={tenant_count}", flush=True)


def _insert_users_sql(settings: DatagenSettings) -> None:
    tenant_count = settings.datagen_tenant_end - settings.datagen_tenant_start + 1
    total_users = tenant_count * settings.datagen_users_per_tenant
    batch_size = max(1, settings.datagen_sql_batch_tenants)
    inserted_users = 0

    for batch_start in range(
        settings.datagen_tenant_start,
        settings.datagen_tenant_end + 1,
        batch_size,
    ):
        batch_end = min(batch_start + batch_size - 1, settings.datagen_tenant_end)
        batch_tenants = batch_end - batch_start + 1
        batch_users = batch_tenants * settings.datagen_users_per_tenant
        _run_psql(
            settings,
            sql=f"""
insert into users (tenant_id, user_id, user_segment, user_status, signup_at, updated_at)
select
  tenant_id,
  user_id,
  case ((user_id - 1) % 4)
    when 0 then 'consumer'
    when 1 then 'professional'
    when 2 then 'power'
    else 'trial'
  end as user_segment,
  case
    when user_id % 53 = 0 then 'suspended'
    when user_id % 17 = 0 then 'inactive'
    else 'active'
  end as user_status,
  statement_timestamp()
    - make_interval(
        days => (
          abs(
            tenant_id * 17::bigint
            + user_id * 31::bigint
            + {settings.datagen_random_seed}
          ) % greatest(1, {settings.datagen_lookback_days * 12 + 1})
        )::int
      ) as signup_at,
  statement_timestamp() as updated_at
from generate_series({batch_start}, {batch_end}) as tenant_id
cross join generate_series(1, {settings.datagen_users_per_tenant}) as user_id;
""",
        )
        inserted_users += batch_users
        print(
            "Inserted users via SQL",
            f"tenants={batch_end - settings.datagen_tenant_start + 1}/{tenant_count}",
            f"users={inserted_users}/{total_users}",
            flush=True,
        )


def _insert_global_users_sql(settings: DatagenSettings) -> None:
    tenant_count = settings.datagen_tenant_end - settings.datagen_tenant_start + 1
    total_users = tenant_count * settings.datagen_global_users_per_tenant
    batch_size = max(1, settings.datagen_sql_batch_tenants)
    inserted_users = 0

    for batch_start in range(
        settings.datagen_tenant_start,
        settings.datagen_tenant_end + 1,
        batch_size,
    ):
        batch_end = min(batch_start + batch_size - 1, settings.datagen_tenant_end)
        batch_tenants = batch_end - batch_start + 1
        batch_users = batch_tenants * settings.datagen_global_users_per_tenant
        _run_psql(
            settings,
            sql=f"""
insert into global_users
  (tenant_id, user_id, user_segment, user_status, home_region, signup_at, updated_at)
select
  tenant_id,
  user_id,
  case ((user_id - 1) % 4)
    when 0 then 'consumer'
    when 1 then 'professional'
    when 2 then 'power'
    else 'trial'
  end as user_segment,
  case
    when user_id % 53 = 0 then 'suspended'
    when user_id % 17 = 0 then 'inactive'
    else 'active'
  end as user_status,
  {_psql_literal(settings.datagen_region)} as home_region,
  statement_timestamp()
    - make_interval(
        days => (
          abs(
            tenant_id * 17::bigint
            + user_id * 31::bigint
            + {settings.datagen_random_seed}
          ) % greatest(1, {settings.datagen_lookback_days * 12 + 1})
        )::int
      ) as signup_at,
  statement_timestamp() as updated_at
from generate_series({batch_start}, {batch_end}) as tenant_id
cross join generate_series(1, {settings.datagen_global_users_per_tenant}) as user_id;
""",
        )
        inserted_users += batch_users
        print(
            "Inserted global_users via SQL",
            f"tenants={batch_end - settings.datagen_tenant_start + 1}/{tenant_count}",
            f"global_users={inserted_users}/{total_users}",
            flush=True,
        )


def _insert_events_sql(settings: DatagenSettings) -> None:
    tenant_count = settings.datagen_tenant_end - settings.datagen_tenant_start + 1
    total_events = tenant_count * settings.datagen_events_per_tenant
    batch_size = max(1, settings.datagen_sql_batch_tenants)
    inserted_events = 0

    for batch_start in range(
        settings.datagen_tenant_start,
        settings.datagen_tenant_end + 1,
        batch_size,
    ):
        batch_end = min(batch_start + batch_size - 1, settings.datagen_tenant_end)
        batch_tenants = batch_end - batch_start + 1
        batch_events = batch_tenants * settings.datagen_events_per_tenant
        event_id_expression = (
            "tenant_id * 1000000::bigint + event_offset"
            if settings.datagen_event_id_mode == "tenant_global"
            else (
                f"((tenant_id - {settings.datagen_tenant_start}) * "
                f"{settings.datagen_events_per_tenant}) + event_offset"
            )
        )
        _run_psql(
            settings,
            sql=f"""
insert into events (event_id, tenant_id, user_id, value, created_at)
select
  {event_id_expression} as event_id,
  tenant_id,
  (
    abs(
      tenant_id * 1103515245::bigint
      + event_offset * 12345::bigint
      + {settings.datagen_random_seed}
    ) % {settings.datagen_users_per_tenant}
  ) + 1 as user_id,
  (
    (
      abs(
        tenant_id * 214013::bigint
        + event_offset * 2531011::bigint
        + {settings.datagen_random_seed}
      ) % 99900
    ) + 100
  ) / 100.0::double precision as value,
  statement_timestamp()
    - make_interval(
        days => (
          abs(
            tenant_id * 48271::bigint
            + event_offset * 69621::bigint
            + {settings.datagen_random_seed}
          ) % ({settings.datagen_lookback_days} + 1)
        )::int,
        secs => (
          abs(
            tenant_id * 16807::bigint
            + event_offset * 950706376::bigint
            + {settings.datagen_random_seed}
          ) % 86400
        )::int
      ) as created_at
from generate_series({batch_start}, {batch_end}) as tenant_id
cross join generate_series(1, {settings.datagen_events_per_tenant}) as event_offset;
""",
        )
        inserted_events += batch_events
        print(
            "Inserted events via SQL",
            f"tenants={batch_end - settings.datagen_tenant_start + 1}/{tenant_count}",
            f"events={inserted_events}/{total_events}",
            flush=True,
        )


def _ensure_copy_generator(settings: DatagenSettings) -> None:
    generator_path = settings.copy_generator_path
    if generator_path.exists() and os.access(generator_path, os.X_OK):
        return

    makefile_path = generator_path.parent / "Makefile"
    if not makefile_path.exists():
        raise RuntimeError(
            f"COPY generator is missing at {generator_path}. Build it with: make -C tools/cpp"
        )
    if shutil.which("make") is None or shutil.which("g++") is None:
        raise RuntimeError(
            "COPY generator needs build tools. On Ubuntu 24.04 install: "
            "sudo apt install -y build-essential make postgresql-client"
        )

    subprocess.run(["make", "-C", str(generator_path.parent)], check=True)
    if not generator_path.exists() or not os.access(generator_path, os.X_OK):
        raise RuntimeError(f"COPY generator build did not create executable: {generator_path}")


def _copy_generator_base_command(settings: DatagenSettings, table: str) -> list[str]:
    users_per_tenant = (
        settings.datagen_global_users_per_tenant
        if table == "global_users"
        else settings.datagen_users_per_tenant
    )
    command = [
        str(settings.copy_generator_path),
        "--table",
        table,
        "--region",
        settings.datagen_region,
        "--tenant-start",
        str(settings.datagen_tenant_start),
        "--tenant-end",
        str(settings.datagen_tenant_end),
        "--event-id-mode",
        settings.datagen_event_id_mode,
        "--events-per-tenant",
        str(settings.datagen_events_per_tenant),
        "--users-per-tenant",
        str(users_per_tenant),
        "--lookback-days",
        str(settings.datagen_lookback_days),
        "--seed",
        str(settings.datagen_random_seed),
        "--progress-every-tenants",
        str(settings.datagen_progress_every_tenants),
        "--distribution",
        settings.datagen_distribution,
        "--hot-tenant-pct",
        str(settings.datagen_hot_tenant_pct),
        "--hot-event-pct",
        str(settings.datagen_hot_event_pct),
    ]
    if settings.datagen_tenant_ranges.strip():
        command.extend(["--tenant-ranges", settings.datagen_tenant_ranges])
    if settings.datagen_base_time_unix > 0:
        command.extend(["--base-time-unix", str(settings.datagen_base_time_unix)])
    return command


def _copy_pipe_table(settings: DatagenSettings, table: str, columns: str) -> None:
    generator_command = _copy_generator_base_command(settings, table)
    psql_command = _build_psql_command(
        settings,
        "-c",
        f"\\copy {table} {columns} from stdin csv",
    )
    merged_env = {**os.environ, **_build_psql_env(settings)}

    generator = subprocess.Popen(generator_command, stdout=subprocess.PIPE)
    assert generator.stdout is not None
    psql = subprocess.Popen(psql_command, stdin=generator.stdout, env=merged_env)
    generator.stdout.close()

    psql_returncode = psql.wait()
    generator_returncode = generator.wait()

    if psql_returncode != 0:
        raise RuntimeError(f"psql COPY failed for {table} with exit code {psql_returncode}")
    if generator_returncode != 0:
        raise RuntimeError(
            f"COPY generator failed for {table} with exit code {generator_returncode}"
        )
    print(f"Loaded {table} via copy_pipe", flush=True)


def load_copy_pipe(settings: DatagenSettings) -> None:
    if _dataset_tables_nonempty(settings):
        raise RuntimeError(
            "Refusing to load into non-empty tables. Use reset-and-load for an explicit rebuild."
        )
    _ensure_copy_generator(settings)
    init_schema(settings)
    _copy_pipe_table(
        settings,
        "tenants",
        "(tenant_id, region, tenant_tier, tenant_status, updated_at, dimension_version)",
    )
    _copy_pipe_table(
        settings,
        "users",
        "(tenant_id, user_id, user_segment, user_status, signup_at, updated_at)",
    )
    if settings.datagen_enable_global_users:
        _copy_pipe_table(
            settings,
            "global_users",
            "(tenant_id, user_id, user_segment, user_status, home_region, signup_at, updated_at)",
        )
    _copy_pipe_table(settings, "events", "(event_id, tenant_id, user_id, value, created_at)")
    print("COPY pipe load complete.", flush=True)


def load_sql(settings: DatagenSettings) -> None:
    if _dataset_tables_nonempty(settings):
        raise RuntimeError(
            "Refusing to load into non-empty tables. Use reset-and-load for an explicit rebuild."
        )
    init_schema(settings)
    _insert_tenants_sql(settings)
    _insert_users_sql(settings)
    if settings.datagen_enable_global_users:
        _insert_global_users_sql(settings)
    _insert_events_sql(settings)
    print("SQL load complete.", flush=True)


def load(settings: DatagenSettings) -> None:
    if settings.datagen_load_method == "sql":
        load_sql(settings)
        return
    if settings.datagen_load_method == "copy_pipe":
        load_copy_pipe(settings)
        return
    if settings.datagen_load_method != "csv":
        raise ValueError(f"Unsupported DATAGEN_LOAD_METHOD: {settings.datagen_load_method}")

    if _dataset_tables_nonempty(settings):
        raise RuntimeError(
            "Refusing to load into non-empty tables. Use reset-and-load for an explicit rebuild."
        )
    generate(settings)
    init_schema(settings)
    _load_csv(
        settings,
        "tenants",
        "(tenant_id, region, tenant_tier, tenant_status, updated_at, dimension_version)",
        settings.tenants_csv_path,
    )
    _load_csv(
        settings,
        "users",
        "(tenant_id, user_id, user_segment, user_status, signup_at, updated_at)",
        settings.users_csv_path,
    )
    if settings.datagen_enable_global_users:
        _load_csv(
            settings,
            "global_users",
            "(tenant_id, user_id, user_segment, user_status, home_region, signup_at, updated_at)",
            settings.global_users_csv_path,
        )
    _load_csv(
        settings,
        "events",
        "(event_id, tenant_id, user_id, value, created_at)",
        settings.events_csv_path,
    )
    print("Load complete.", flush=True)


def reset_and_load(settings: DatagenSettings) -> None:
    if settings.datagen_load_method == "sql":
        _run_psql(
            settings,
            sql=DROP_DATASET_TABLES_SQL,
        )
        print("Existing dataset tables dropped.", flush=True)
        init_schema(settings)
        _insert_tenants_sql(settings)
        _insert_users_sql(settings)
        if settings.datagen_enable_global_users:
            _insert_global_users_sql(settings)
        _insert_events_sql(settings)
        print("SQL reset and load complete.", flush=True)
        return
    if settings.datagen_load_method == "copy_pipe":
        _ensure_copy_generator(settings)
        _run_psql(
            settings,
            sql=DROP_DATASET_TABLES_SQL,
        )
        print("Existing dataset tables dropped.", flush=True)
        init_schema(settings)
        _copy_pipe_table(
            settings,
            "tenants",
            "(tenant_id, region, tenant_tier, tenant_status, updated_at, dimension_version)",
        )
        _copy_pipe_table(
            settings,
            "users",
            "(tenant_id, user_id, user_segment, user_status, signup_at, updated_at)",
        )
        if settings.datagen_enable_global_users:
            _copy_pipe_table(
                settings,
                "global_users",
                "("
                "tenant_id, user_id, user_segment, user_status, "
                "home_region, signup_at, updated_at"
                ")",
            )
        _copy_pipe_table(settings, "events", "(event_id, tenant_id, user_id, value, created_at)")
        print("COPY pipe reset and load complete.", flush=True)
        return
    if settings.datagen_load_method != "csv":
        raise ValueError(f"Unsupported DATAGEN_LOAD_METHOD: {settings.datagen_load_method}")

    generate(settings)
    _run_psql(
        settings,
        sql=DROP_DATASET_TABLES_SQL,
    )
    print("Existing dataset tables dropped.", flush=True)
    init_schema(settings)
    _load_csv(
        settings,
        "tenants",
        "(tenant_id, region, tenant_tier, tenant_status, updated_at, dimension_version)",
        settings.tenants_csv_path,
    )
    _load_csv(
        settings,
        "users",
        "(tenant_id, user_id, user_segment, user_status, signup_at, updated_at)",
        settings.users_csv_path,
    )
    if settings.datagen_enable_global_users:
        _load_csv(
            settings,
            "global_users",
            "(tenant_id, user_id, user_segment, user_status, home_region, signup_at, updated_at)",
            settings.global_users_csv_path,
        )
    _load_csv(
        settings,
        "events",
        "(event_id, tenant_id, user_id, value, created_at)",
        settings.events_csv_path,
    )
    print("Reset and load complete.", flush=True)


def run_cli(command: str) -> int:
    settings = DatagenSettings.from_env()

    if command == "generate":
        generate(settings)
        return 0
    if command == "load":
        load(settings)
        return 0
    if command == "reset-and-load":
        reset_and_load(settings)
        return 0
    raise ValueError(f"Unsupported command: {command}")
