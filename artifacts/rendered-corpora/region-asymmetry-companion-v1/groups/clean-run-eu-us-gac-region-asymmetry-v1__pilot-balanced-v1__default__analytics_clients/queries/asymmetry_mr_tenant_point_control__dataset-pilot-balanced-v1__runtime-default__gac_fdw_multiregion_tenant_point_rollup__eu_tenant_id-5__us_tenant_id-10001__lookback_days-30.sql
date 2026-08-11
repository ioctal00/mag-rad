with regional_tenant as (
  select
    'eu'::text as source_region,
    e.tenant_id,
    count(*) as events_count,
    sum(e.value) as total_value,
    avg(e.value) as avg_value
  from fdw_eu.events e
  where e.tenant_id = 5::bigint
    and e.created_at >= now() - make_interval(days => 30::int)
  group by e.tenant_id
  union all
  select
    'us'::text as source_region,
    e.tenant_id,
    count(*) as events_count,
    sum(e.value) as total_value,
    avg(e.value) as avg_value
  from fdw_us.events e
  where e.tenant_id = 10001::bigint
    and e.created_at >= now() - make_interval(days => 30::int)
  group by e.tenant_id
)
select
  source_region,
  tenant_id,
  events_count,
  total_value,
  avg_value
from regional_tenant
order by source_region, tenant_id;
