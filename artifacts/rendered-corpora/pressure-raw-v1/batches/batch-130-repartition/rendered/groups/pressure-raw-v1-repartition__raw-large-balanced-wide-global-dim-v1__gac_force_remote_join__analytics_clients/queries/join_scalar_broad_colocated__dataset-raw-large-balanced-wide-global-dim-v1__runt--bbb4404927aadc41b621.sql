select
  count(*) as events_count,
  count(distinct e.tenant_id) as tenant_count,
  count(distinct e.user_id) as user_count,
  round(sum(e.value::numeric), 6) as total_value,
  round(avg(e.value::numeric), 6) as avg_value
from fdw_eu.mr_joined_events_colocated e
where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 30::int)
  and (0::bigint = 0 or e.tenant_id = 0::bigint)
  and mod(e.tenant_id, 1::bigint) = 0
  and e.user_id <= 2147483647::bigint;
