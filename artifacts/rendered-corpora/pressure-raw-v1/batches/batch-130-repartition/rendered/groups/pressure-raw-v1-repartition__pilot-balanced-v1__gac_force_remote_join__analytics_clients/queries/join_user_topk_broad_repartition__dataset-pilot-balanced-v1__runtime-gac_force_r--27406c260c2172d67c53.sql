select
  e.tenant_id,
  e.user_id,
  e.user_segment,
  e.user_status,
  count(*) as events_count,
  round(sum(e.value::numeric), 6) as total_value
from fdw_eu.mr_joined_events_repartition e
where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and (0::bigint = 0 or e.tenant_id = 0::bigint)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint
group by e.tenant_id, e.user_id, e.user_segment, e.user_status
order by total_value desc, e.tenant_id, e.user_id
limit 100;
