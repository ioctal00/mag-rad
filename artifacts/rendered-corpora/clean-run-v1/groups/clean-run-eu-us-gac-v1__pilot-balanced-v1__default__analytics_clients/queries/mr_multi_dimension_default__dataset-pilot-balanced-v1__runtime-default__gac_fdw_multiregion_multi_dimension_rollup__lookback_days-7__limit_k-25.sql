with regional_multi_dimension as (
  select
    'eu'::text as source_region,
    t.tenant_tier,
    u.user_segment,
    date_trunc('day', e.created_at) as event_day,
    count(*) as events_count,
    sum(e.value) as total_value
  from fdw_eu.events e
  join fdw_eu.tenants t
    on t.tenant_id = e.tenant_id
  join fdw_eu.users u
    on u.tenant_id = e.tenant_id
   and u.user_id = e.user_id
  where e.created_at >= now() - make_interval(days => 7::int)
  group by t.tenant_tier, u.user_segment, date_trunc('day', e.created_at)
  union all
  select
    'us'::text as source_region,
    t.tenant_tier,
    u.user_segment,
    date_trunc('day', e.created_at) as event_day,
    count(*) as events_count,
    sum(e.value) as total_value
  from fdw_us.events e
  join fdw_us.tenants t
    on t.tenant_id = e.tenant_id
  join fdw_us.users u
    on u.tenant_id = e.tenant_id
   and u.user_id = e.user_id
  where e.created_at >= now() - make_interval(days => 7::int)
  group by t.tenant_tier, u.user_segment, date_trunc('day', e.created_at)
)
select
  tenant_tier,
  user_segment,
  event_day,
  count(distinct source_region) as regions_touched,
  sum(events_count) as events_count,
  sum(total_value) as total_value
from regional_multi_dimension
group by tenant_tier, user_segment, event_day
order by event_day desc, total_value desc, tenant_tier, user_segment
limit 25;
