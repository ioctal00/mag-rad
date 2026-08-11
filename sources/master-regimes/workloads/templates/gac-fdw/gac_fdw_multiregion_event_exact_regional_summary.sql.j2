with regional_summary as (
  select
    count(*) as events_count,
    min(e.created_at) as first_event_at,
    max(e.created_at) as last_event_at
  from fdw_eu.events e
  union all
  select
    count(*) as events_count,
    min(e.created_at) as first_event_at,
    max(e.created_at) as last_event_at
  from fdw_us.events e
)
select
  sum(events_count)::numeric as events_count,
  min(first_event_at) as first_event_at,
  max(last_event_at) as last_event_at
from regional_summary;
