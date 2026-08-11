with events_all as (
  select e.created_at
  from fdw_eu.events e
  union all
  select e.created_at
  from fdw_us.events e
)
select
  count(*)::numeric as events_count,
  min(created_at) as first_event_at,
  max(created_at) as last_event_at
from events_all;
