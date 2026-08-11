with regional_groups as (
  select
    'eu'::text as source_region,
    e.tenant_id,
    e.user_id,
    count(*) as events_count,
    round(sum(e.value::numeric), 6) as total_value
  from fdw_eu.events e
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and mod(e.tenant_id, 8::bigint) = 0
  group by e.tenant_id, e.user_id
  union all
  select
    'us'::text as source_region,
    e.tenant_id,
    e.user_id,
    count(*) as events_count,
    round(sum(e.value::numeric), 6) as total_value
  from fdw_us.events e
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and mod(e.tenant_id, 8::bigint) = 0
  group by e.tenant_id, e.user_id
)
select
  source_region,
  tenant_id,
  user_id,
  events_count,
  total_value
from regional_groups
order by total_value desc, source_region, tenant_id, user_id
limit 100;
