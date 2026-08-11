select
  e.event_id,
  e.tenant_id,
  e.user_id,
  e.user_segment,
  e.user_status,
  e.value
from fdw_eu.mr_joined_events_colocated e
where e.created_at >= coalesce(
  to_timestamp(nullif(1782864000, 0)),
  now()
) - make_interval(days => 1::int)
  and (0::bigint = 0 or e.tenant_id = 0::bigint)
  and mod(e.tenant_id, 16::bigint) = 0
  and e.user_id <= 5::bigint
order by e.event_id, e.tenant_id, e.user_id
limit 100;
