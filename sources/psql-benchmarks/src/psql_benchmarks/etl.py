from __future__ import annotations

import json
from pathlib import Path

from .psql import run_psql
from .run_dir import create_run_dir
from .settings import Settings


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _etl_sql(*, source_schema: str, etl_schema: str, lookback_days: int) -> str:
    source = _quote_ident(source_schema)
    target_schema = _quote_ident(etl_schema)
    daily_tenant = f"{target_schema}.{_quote_ident('daily_tenant_rollup')}"
    daily_tenant_tier = f"{target_schema}.{_quote_ident('daily_tenant_tier_rollup')}"
    user_segment = f"{target_schema}.{_quote_ident('user_segment_topk_rollup')}"
    global_user = f"{target_schema}.{_quote_ident('global_user_topk_rollup')}"
    multi_dimension = f"{target_schema}.{_quote_ident('multi_dimension_rollup')}"
    return f"""
CREATE SCHEMA IF NOT EXISTS {target_schema};
DROP TABLE IF EXISTS
  {multi_dimension},
  {global_user},
  {user_segment},
  {daily_tenant_tier},
  {daily_tenant};

CREATE TABLE {daily_tenant} AS
SELECT
  e.tenant_id,
  date_trunc('day', e.created_at)::date AS event_day,
  max(t.region) AS region,
  max(t.tenant_tier) AS tenant_tier,
  count(*) AS events_count,
  sum(e.value) AS total_value,
  avg(e.value) AS avg_value,
  min(e.created_at) AS first_event_at,
  max(e.created_at) AS last_event_at
FROM {source}.{_quote_ident('events')} e
LEFT JOIN {source}.{_quote_ident('tenants')} t
  ON t.tenant_id = e.tenant_id
WHERE e.created_at >= now() - make_interval(days => {lookback_days}::int)
GROUP BY e.tenant_id, date_trunc('day', e.created_at)::date;
CREATE INDEX daily_tenant_rollup_tenant_day_idx
  ON {daily_tenant} (tenant_id, event_day);
CREATE INDEX daily_tenant_rollup_day_tier_idx
  ON {daily_tenant} (event_day, tenant_tier);
ANALYZE {daily_tenant};

CREATE TABLE {daily_tenant_tier} AS
SELECT
  t.tenant_tier,
  date_trunc('day', e.created_at)::date AS event_day,
  count(*) AS events_count,
  count(DISTINCT e.tenant_id) AS tenant_count,
  sum(e.value) AS total_value,
  avg(e.value) AS avg_value
FROM {source}.{_quote_ident('events')} e
JOIN {source}.{_quote_ident('tenants')} t
  ON t.tenant_id = e.tenant_id
WHERE e.created_at >= now() - make_interval(days => {lookback_days}::int)
GROUP BY t.tenant_tier, date_trunc('day', e.created_at)::date;
CREATE INDEX daily_tenant_tier_rollup_day_tier_idx
  ON {daily_tenant_tier} (event_day, tenant_tier);
ANALYZE {daily_tenant_tier};

CREATE TABLE {user_segment} AS
SELECT
  date_trunc('day', e.created_at)::date AS event_day,
  u.user_segment,
  u.user_status,
  count(*) AS events_count,
  count(DISTINCT e.tenant_id) AS tenant_count,
  sum(e.value) AS total_value,
  avg(e.value) AS avg_value
FROM {source}.{_quote_ident('events')} e
JOIN {source}.{_quote_ident('users')} u
  ON u.tenant_id = e.tenant_id
 AND u.user_id = e.user_id
WHERE e.created_at >= now() - make_interval(days => {lookback_days}::int)
GROUP BY date_trunc('day', e.created_at)::date, u.user_segment, u.user_status;
CREATE INDEX user_segment_topk_rollup_day_value_idx
  ON {user_segment} (event_day, total_value DESC);
ANALYZE {user_segment};

CREATE TABLE {global_user} AS
SELECT
  date_trunc('day', e.created_at)::date AS event_day,
  gu.user_segment,
  gu.user_status,
  gu.home_region,
  count(*) AS events_count,
  count(DISTINCT e.tenant_id) AS tenant_count,
  sum(e.value) AS total_value,
  avg(e.value) AS avg_value
FROM {source}.{_quote_ident('events')} e
JOIN {source}.{_quote_ident('global_users')} gu
  ON gu.tenant_id = e.tenant_id
 AND gu.user_id = e.user_id
WHERE e.created_at >= now() - make_interval(days => {lookback_days}::int)
GROUP BY
  date_trunc('day', e.created_at)::date,
  gu.user_segment,
  gu.user_status,
  gu.home_region;
CREATE INDEX global_user_topk_rollup_day_value_idx
  ON {global_user} (event_day, total_value DESC);
ANALYZE {global_user};

CREATE TABLE {multi_dimension} AS
SELECT
  date_trunc('day', e.created_at)::date AS event_day,
  t.tenant_tier,
  u.user_segment,
  count(*) AS events_count,
  sum(e.value) AS total_value,
  avg(e.value) AS avg_value
FROM {source}.{_quote_ident('events')} e
JOIN {source}.{_quote_ident('tenants')} t
  ON t.tenant_id = e.tenant_id
JOIN {source}.{_quote_ident('users')} u
  ON u.tenant_id = e.tenant_id
 AND u.user_id = e.user_id
WHERE e.created_at >= now() - make_interval(days => {lookback_days}::int)
GROUP BY date_trunc('day', e.created_at)::date, t.tenant_tier, u.user_segment;
CREATE INDEX multi_dimension_rollup_day_value_idx
  ON {multi_dimension} (event_day, total_value DESC);
ANALYZE {multi_dimension};

SELECT count(*) AS etl_daily_tenant_rollup_rows
FROM {daily_tenant};
SELECT count(*) AS etl_daily_tenant_tier_rollup_rows
FROM {daily_tenant_tier};
SELECT count(*) AS etl_user_segment_topk_rollup_rows
FROM {user_segment};
SELECT count(*) AS etl_global_user_topk_rollup_rows
FROM {global_user};
SELECT count(*) AS etl_multi_dimension_rollup_rows
FROM {multi_dimension};
""".strip()


def gac_etl_bootstrap(
    settings: Settings,
    *,
    label: str,
    region: str,
    source_schema: str | None = None,
    etl_schema: str = "etl",
    lookback_days: int = 30,
) -> Path:
    normalized_region = region.lower()
    source = source_schema or f"fdw_{normalized_region}"
    run_dir = create_run_dir(settings, mode="gac-etl-bootstrap", label=label)
    sql = _etl_sql(
        source_schema=source,
        etl_schema=etl_schema,
        lookback_days=lookback_days,
    )
    sql_file = run_dir / "queries" / f"gac-etl-bootstrap-{normalized_region}.sql"
    sql_file.write_text(sql + "\n", encoding="utf-8")

    (run_dir / "gac_etl_bootstrap_manifest.json").write_text(
        json.dumps(
            {
                "region": normalized_region,
                "source_schema": source,
                "etl_schema": etl_schema,
                "lookback_days": lookback_days,
                "local_database": settings.pg_database,
                "local_user": settings.pg_user,
                "table": f"{etl_schema}.daily_tenant_rollup",
                "tables": [
                    f"{etl_schema}.daily_tenant_rollup",
                    f"{etl_schema}.daily_tenant_tier_rollup",
                    f"{etl_schema}.user_segment_topk_rollup",
                    f"{etl_schema}.global_user_topk_rollup",
                    f"{etl_schema}.multi_dimension_rollup",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_psql(settings, sql_file=sql_file)
    (run_dir / "results" / "gac_etl_bootstrap.stdout.log").write_text(
        result.stdout, encoding="utf-8"
    )
    (run_dir / "logs" / "gac_etl_bootstrap.stderr.log").write_text(
        result.stderr, encoding="utf-8"
    )
    (run_dir / "results" / "gac_etl_bootstrap_timing.json").write_text(
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
