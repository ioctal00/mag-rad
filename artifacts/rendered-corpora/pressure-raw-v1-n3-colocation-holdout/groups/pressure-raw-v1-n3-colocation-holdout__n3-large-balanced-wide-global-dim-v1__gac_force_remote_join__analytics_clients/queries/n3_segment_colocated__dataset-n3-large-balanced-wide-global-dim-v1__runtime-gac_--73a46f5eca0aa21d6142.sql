with regional_result as (
  select 'eu'::text as source_region, e.user_segment, e.user_status,
         count(*) as events_count, sum(e.value::numeric) as total_value
  from fdw_eu.mr_joined_events_colocated e
  where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
  group by e.user_segment, e.user_status
  union all
  select 'us'::text, e.user_segment, e.user_status,
         count(*), sum(e.value::numeric)
  from fdw_us.mr_joined_events_colocated e
  where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
  group by e.user_segment, e.user_status
  union all
  select 'apac'::text, e.user_segment, e.user_status,
         count(*), sum(e.value::numeric)
  from fdw_apac.mr_joined_events_colocated e
  where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
  group by e.user_segment, e.user_status
)
select user_segment, user_status,
       sum(events_count)::bigint as events_count,
       round(sum(total_value), 6) as total_value
from regional_result
group by user_segment, user_status
order by total_value desc, user_segment, user_status
limit 100;
