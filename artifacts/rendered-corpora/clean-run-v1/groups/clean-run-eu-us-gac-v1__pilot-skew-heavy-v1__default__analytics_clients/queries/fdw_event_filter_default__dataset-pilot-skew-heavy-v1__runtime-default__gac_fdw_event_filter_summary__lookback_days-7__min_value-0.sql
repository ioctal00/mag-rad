select
  count(*) as events_count,
  sum(e.value) as total_value,
  avg(e.value) as avg_value,
  min(e.value) as min_value,
  max(e.value) as max_value
from fdw_eu.events e
where e.created_at >= now() - make_interval(days => 7::int)
  and e.value >= 0::double precision;
