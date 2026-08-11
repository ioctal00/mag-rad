with regional_summary as (
  select
    'eu'::text as source_region,
    count(*) as events_count,
    sum(e.value) as total_value,
    avg(e.value) as avg_value,
    min(e.created_at) as first_event_at,
    max(e.created_at) as last_event_at
  from fdw_eu.events e
  union all
  select
    'us'::text as source_region,
    count(*) as events_count,
    sum(e.value) as total_value,
    avg(e.value) as avg_value,
    min(e.created_at) as first_event_at,
    max(e.created_at) as last_event_at
  from fdw_us.events e
)
select
  count(*) as regions_touched,
  sum(events_count) as events_count,
  sum(total_value) as total_value,
  sum(total_value) / nullif(sum(events_count), 0) as avg_value,
  min(first_event_at) as first_event_at,
  max(last_event_at) as last_event_at
from regional_summary
where events_count > 0;
