select
  tenant_id,
  count(*) as event_count,
  avg(value) as avg_value,
  min(created_at) as first_event_at,
  max(created_at) as last_event_at
from events
where tenant_id = :tenant_id
  and created_at >= now() - (:lookback_days || ' days')::interval
group by tenant_id;
