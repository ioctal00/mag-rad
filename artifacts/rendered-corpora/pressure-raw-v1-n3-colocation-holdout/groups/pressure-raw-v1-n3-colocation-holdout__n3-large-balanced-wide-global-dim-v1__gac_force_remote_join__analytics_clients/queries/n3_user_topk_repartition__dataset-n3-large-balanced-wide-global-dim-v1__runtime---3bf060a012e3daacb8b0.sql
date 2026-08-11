with regional_result as (
  select 'eu'::text as source_region, e.tenant_id, e.user_id,
         e.user_segment, e.user_status, count(*) as events_count,
         sum(e.value::numeric) as total_value
  from fdw_eu.mr_joined_events_repartition e
  where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
  group by e.tenant_id, e.user_id, e.user_segment, e.user_status
  union all
  select 'us'::text, e.tenant_id, e.user_id,
         e.user_segment, e.user_status, count(*), sum(e.value::numeric)
  from fdw_us.mr_joined_events_repartition e
  where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
  group by e.tenant_id, e.user_id, e.user_segment, e.user_status
  union all
  select 'apac'::text, e.tenant_id, e.user_id,
         e.user_segment, e.user_status, count(*), sum(e.value::numeric)
  from fdw_apac.mr_joined_events_repartition e
  where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
  group by e.tenant_id, e.user_id, e.user_segment, e.user_status
)
select tenant_id, user_id, user_segment, user_status,
       sum(events_count)::bigint as events_count,
       round(sum(total_value), 6) as total_value
from regional_result
group by tenant_id, user_id, user_segment, user_status
order by total_value desc, tenant_id, user_id
limit 100;
