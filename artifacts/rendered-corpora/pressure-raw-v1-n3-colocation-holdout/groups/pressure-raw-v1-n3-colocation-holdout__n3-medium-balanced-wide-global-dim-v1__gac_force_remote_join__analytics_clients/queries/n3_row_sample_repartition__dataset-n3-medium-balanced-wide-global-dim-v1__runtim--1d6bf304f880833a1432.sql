with regional_result as (
  select * from (
    select 'eu'::text as source_region, e.event_id, e.tenant_id, e.user_id,
           e.user_segment, e.user_status, e.value
    from fdw_eu.mr_joined_events_repartition e
    where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
    order by e.event_id, e.tenant_id, e.user_id
    limit 100
  ) eu_rows
  union all
  select * from (
    select 'us'::text, e.event_id, e.tenant_id, e.user_id,
           e.user_segment, e.user_status, e.value
    from fdw_us.mr_joined_events_repartition e
    where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
    order by e.event_id, e.tenant_id, e.user_id
    limit 100
  ) us_rows
  union all
  select * from (
    select 'apac'::text, e.event_id, e.tenant_id, e.user_id,
           e.user_segment, e.user_status, e.value
    from fdw_apac.mr_joined_events_repartition e
    where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
    order by e.event_id, e.tenant_id, e.user_id
    limit 100
  ) apac_rows
)
select source_region, event_id, tenant_id, user_id, user_segment, user_status, value
from regional_result
order by event_id, source_region, tenant_id, user_id
limit 100;
