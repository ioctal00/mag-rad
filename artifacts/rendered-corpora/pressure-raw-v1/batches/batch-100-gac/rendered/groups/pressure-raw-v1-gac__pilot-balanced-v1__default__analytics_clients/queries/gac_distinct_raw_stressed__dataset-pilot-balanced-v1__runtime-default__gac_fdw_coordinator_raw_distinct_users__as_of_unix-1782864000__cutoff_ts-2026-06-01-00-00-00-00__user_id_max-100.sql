with events_all as materialized (
  select e.user_id
  from fdw_eu.events e
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and e.user_id <= 100::bigint
  union all
  select e.user_id
  from fdw_us.events e
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and e.user_id <= 100::bigint
)
select distinct user_id
from events_all
order by user_id;
