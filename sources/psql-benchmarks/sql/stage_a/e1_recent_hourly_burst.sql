select
  date_trunc('hour', created_at) as hour,
  count(*) as events
from events
where created_at >= now() - (:lookback_hours || ' hours')::interval
group by hour
order by hour;
