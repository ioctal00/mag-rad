with regional_result as (
  select 'eu'::text as source_region, count(*) as events_count,
         count(distinct e.tenant_id) as tenant_count,
         count(distinct e.user_id) as user_count,
         sum(e.value::numeric) as total_value
  from fdw_eu.mr_joined_events_repartition e
  where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
  union all
  select 'us'::text, count(*), count(distinct e.tenant_id),
         count(distinct e.user_id), sum(e.value::numeric)
  from fdw_us.mr_joined_events_repartition e
  where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
  union all
  select 'apac'::text, count(*), count(distinct e.tenant_id),
         count(distinct e.user_id), sum(e.value::numeric)
  from fdw_apac.mr_joined_events_repartition e
  where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
)
select sum(events_count)::bigint as events_count,
       sum(tenant_count)::bigint as tenant_count,
       sum(user_count)::bigint as user_count,
       round(sum(total_value), 6) as total_value,
       round(sum(total_value) / nullif(sum(events_count), 0), 6) as avg_value
from regional_result;
