select
  count(*) as events_count,
  sum(value) as total_value,
  avg(value) as avg_value,
  min(value) as min_value,
  max(value) as max_value
from events
where created_at >= now() - make_interval(days => 1::int)
  and value >= 100::double precision;
