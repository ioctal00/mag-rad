with regional_rollups as (
  select
    'eu'::text as source_region,
    e.tenant_id,
    date_trunc('day', e.created_at) as event_day,
    count(*) as events_count,
    sum(e.value) as total_value,
    avg(e.value) as avg_value
  from fdw_eu.events e
  where e.created_at >= now() - make_interval(days => 30::int)
    and e.value >= 0::double precision
  group by e.tenant_id, date_trunc('day', e.created_at)
  union all
  select
    'us'::text as source_region,
    e.tenant_id,
    date_trunc('day', e.created_at) as event_day,
    count(*) as events_count,
    sum(e.value) as total_value,
    avg(e.value) as avg_value
  from fdw_us.events e
  where e.created_at >= now() - make_interval(days => 30::int)
    and e.value >= 0::double precision
  group by e.tenant_id, date_trunc('day', e.created_at)
)
select
  event_day,
  tenant_id,
  count(distinct source_region) as regions_touched,
  sum(events_count) as events_count,
  sum(total_value) as total_value,
  sum(total_value) / nullif(sum(events_count), 0) as avg_value
from regional_rollups
group by event_day, tenant_id
order by event_day desc, total_value desc, tenant_id
limit 25;
