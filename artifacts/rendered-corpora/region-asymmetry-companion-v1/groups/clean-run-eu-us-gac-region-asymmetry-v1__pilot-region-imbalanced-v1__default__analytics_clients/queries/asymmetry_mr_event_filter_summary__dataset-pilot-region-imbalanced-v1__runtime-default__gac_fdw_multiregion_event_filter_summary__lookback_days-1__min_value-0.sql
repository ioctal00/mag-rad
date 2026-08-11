with regional_filtered as (
  select
    'eu'::text as source_region,
    count(*) as events_count,
    sum(e.value) as total_value,
    avg(e.value) as avg_value,
    min(e.created_at) as first_event_at,
    max(e.created_at) as last_event_at
  from fdw_eu.events e
  where e.created_at >= now() - make_interval(days => 1::int)
    and e.value >= 0::double precision
  union all
  select
    'us'::text as source_region,
    count(*) as events_count,
    sum(e.value) as total_value,
    avg(e.value) as avg_value,
    min(e.created_at) as first_event_at,
    max(e.created_at) as last_event_at
  from fdw_us.events e
  where e.created_at >= now() - make_interval(days => 1::int)
    and e.value >= 0::double precision
)
select
  count(*) as regions_touched,
  sum(events_count) as events_count,
  sum(total_value) as total_value,
  sum(total_value) / nullif(sum(events_count), 0) as avg_value,
  min(first_event_at) as first_event_at,
  max(last_event_at) as last_event_at
from regional_filtered
where events_count > 0;
