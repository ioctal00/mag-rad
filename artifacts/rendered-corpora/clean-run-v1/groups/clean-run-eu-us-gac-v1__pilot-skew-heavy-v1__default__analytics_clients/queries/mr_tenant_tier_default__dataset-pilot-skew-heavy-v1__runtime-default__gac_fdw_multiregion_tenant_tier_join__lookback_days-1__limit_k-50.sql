with regional_tier_rollup as (
  select
    'eu'::text as source_region,
    t.tenant_tier,
    date_trunc('day', e.created_at) as event_day,
    count(*) as events_count,
    count(distinct e.tenant_id) as tenant_count,
    sum(e.value) as total_value
  from fdw_eu.events e
  join fdw_eu.tenants t
    on t.tenant_id = e.tenant_id
  where e.created_at >= now() - make_interval(days => 1::int)
  group by t.tenant_tier, date_trunc('day', e.created_at)
  union all
  select
    'us'::text as source_region,
    t.tenant_tier,
    date_trunc('day', e.created_at) as event_day,
    count(*) as events_count,
    count(distinct e.tenant_id) as tenant_count,
    sum(e.value) as total_value
  from fdw_us.events e
  join fdw_us.tenants t
    on t.tenant_id = e.tenant_id
  where e.created_at >= now() - make_interval(days => 1::int)
  group by t.tenant_tier, date_trunc('day', e.created_at)
)
select
  tenant_tier,
  event_day,
  count(distinct source_region) as regions_touched,
  sum(events_count) as events_count,
  sum(tenant_count) as tenant_count,
  sum(total_value) as total_value
from regional_tier_rollup
group by tenant_tier, event_day
order by event_day desc, total_value desc, tenant_tier
limit 50;
