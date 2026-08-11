with regional_tenants as (
  select
    'eu'::text as source_region,
    e.tenant_id,
    count(*) as events_count,
    sum(e.value) as total_value,
    max(e.created_at) as last_event_at
  from fdw_eu.events e
  where e.created_at >= now() - make_interval(days => 3::int)
  group by e.tenant_id
  union all
  select
    'us'::text as source_region,
    e.tenant_id,
    count(*) as events_count,
    sum(e.value) as total_value,
    max(e.created_at) as last_event_at
  from fdw_us.events e
  where e.created_at >= now() - make_interval(days => 3::int)
  group by e.tenant_id
)
select
  tenant_id,
  count(distinct source_region) as regions_touched,
  sum(events_count) as events_count,
  sum(total_value) as total_value,
  max(last_event_at) as last_event_at
from regional_tenants
group by tenant_id
order by total_value desc, tenant_id
limit 10;
