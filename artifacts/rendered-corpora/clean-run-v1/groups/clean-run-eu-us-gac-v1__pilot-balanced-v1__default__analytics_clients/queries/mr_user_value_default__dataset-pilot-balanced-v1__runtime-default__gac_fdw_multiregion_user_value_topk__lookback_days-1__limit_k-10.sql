with regional_users as (
  select
    'eu'::text as source_region,
    e.tenant_id,
    e.user_id,
    count(*) as events_count,
    sum(e.value) as total_value
  from fdw_eu.events e
  where e.created_at >= now() - make_interval(days => 1::int)
  group by e.tenant_id, e.user_id
  union all
  select
    'us'::text as source_region,
    e.tenant_id,
    e.user_id,
    count(*) as events_count,
    sum(e.value) as total_value
  from fdw_us.events e
  where e.created_at >= now() - make_interval(days => 1::int)
  group by e.tenant_id, e.user_id
)
select
  tenant_id,
  user_id,
  count(distinct source_region) as regions_touched,
  sum(events_count) as events_count,
  sum(total_value) as total_value
from regional_users
group by tenant_id, user_id
order by total_value desc, tenant_id, user_id
limit 10;
