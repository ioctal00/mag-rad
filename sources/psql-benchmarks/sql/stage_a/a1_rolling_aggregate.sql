select
  date_trunc('day', created_at) as day,
  sum(value) as total_value,
  count(*) as events_count
from events
where created_at >= now() - (:lookback_days || ' days')::interval
group by day
order by day;
