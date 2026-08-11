with regional_global_users as (
  select
    'eu'::text as source_region,
    gu.user_segment,
    gu.user_status,
    gu.home_region,
    count(*) as events_count,
    count(distinct e.tenant_id) as tenant_count,
    sum(e.value) as total_value
  from fdw_eu.events e
  join fdw_eu.global_users gu
    on gu.tenant_id = e.tenant_id
   and gu.user_id = e.user_id
  where e.created_at >= now() - make_interval(days => 14::int)
  group by gu.user_segment, gu.user_status, gu.home_region
  union all
  select
    'us'::text as source_region,
    gu.user_segment,
    gu.user_status,
    gu.home_region,
    count(*) as events_count,
    count(distinct e.tenant_id) as tenant_count,
    sum(e.value) as total_value
  from fdw_us.events e
  join fdw_us.global_users gu
    on gu.tenant_id = e.tenant_id
   and gu.user_id = e.user_id
  where e.created_at >= now() - make_interval(days => 14::int)
  group by gu.user_segment, gu.user_status, gu.home_region
)
select
  user_segment,
  user_status,
  home_region,
  count(distinct source_region) as regions_touched,
  sum(events_count) as events_count,
  sum(tenant_count) as tenant_count,
  sum(total_value) as total_value
from regional_global_users
group by user_segment, user_status, home_region
order by total_value desc, user_segment, user_status, home_region
limit 100;
