select
  tenant_id,
  date_trunc('day', created_at) as day,
  sum(value) as total_value
from events
where tenant_id = :tenant_id
  and created_at >= now() - (:lookback_days || ' days')::interval
group by tenant_id, day
order by day;
