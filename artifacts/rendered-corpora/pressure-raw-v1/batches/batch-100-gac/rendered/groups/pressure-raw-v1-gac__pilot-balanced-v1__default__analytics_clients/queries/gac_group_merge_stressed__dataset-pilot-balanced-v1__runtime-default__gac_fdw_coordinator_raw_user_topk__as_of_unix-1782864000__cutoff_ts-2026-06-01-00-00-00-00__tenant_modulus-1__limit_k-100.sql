with events_all as materialized (
  select
    'eu'::text as source_region,
    e.tenant_id,
    e.user_id,
    e.value
  from fdw_eu.events e
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and mod(e.tenant_id, 1::bigint) = 0
  union all
  select
    'us'::text as source_region,
    e.tenant_id,
    e.user_id,
    e.value
  from fdw_us.events e
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and mod(e.tenant_id, 1::bigint) = 0
)
select
  source_region,
  tenant_id,
  user_id,
  count(*) as events_count,
  round(sum(value::numeric), 6) as total_value
from events_all
group by source_region, tenant_id, user_id
order by total_value desc, source_region, tenant_id, user_id
limit 100;
