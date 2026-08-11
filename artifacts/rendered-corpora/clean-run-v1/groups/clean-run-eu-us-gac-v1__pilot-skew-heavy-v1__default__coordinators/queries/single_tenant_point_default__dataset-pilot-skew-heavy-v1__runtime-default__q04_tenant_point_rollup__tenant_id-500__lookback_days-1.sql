select
  tenant_id,
  count(*) as events_count,
  sum(value) as total_value,
  avg(value) as avg_value,
  max(created_at) as last_event_at
from events
where tenant_id = 500::bigint
  and created_at >= now() - make_interval(days => 1::int)
group by tenant_id;
