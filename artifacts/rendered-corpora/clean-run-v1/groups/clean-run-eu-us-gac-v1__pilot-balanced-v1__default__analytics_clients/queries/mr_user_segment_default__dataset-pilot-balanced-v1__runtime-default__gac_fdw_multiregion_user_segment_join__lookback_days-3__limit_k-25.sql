with regional_segment_rollup as (
  select
    'eu'::text as source_region,
    u.user_segment,
    u.user_status,
    count(*) as events_count,
    count(distinct e.tenant_id) as tenant_count,
    sum(e.value) as total_value
  from fdw_eu.events e
  join fdw_eu.users u
    on u.tenant_id = e.tenant_id
   and u.user_id = e.user_id
  where e.created_at >= now() - make_interval(days => 3::int)
  group by u.user_segment, u.user_status
  union all
  select
    'us'::text as source_region,
    u.user_segment,
    u.user_status,
    count(*) as events_count,
    count(distinct e.tenant_id) as tenant_count,
    sum(e.value) as total_value
  from fdw_us.events e
  join fdw_us.users u
    on u.tenant_id = e.tenant_id
   and u.user_id = e.user_id
  where e.created_at >= now() - make_interval(days => 3::int)
  group by u.user_segment, u.user_status
)
select
  user_segment,
  user_status,
  count(distinct source_region) as regions_touched,
  sum(events_count) as events_count,
  sum(tenant_count) as tenant_count,
  sum(total_value) as total_value
from regional_segment_rollup
group by user_segment, user_status
order by total_value desc, user_segment, user_status
limit 25;
