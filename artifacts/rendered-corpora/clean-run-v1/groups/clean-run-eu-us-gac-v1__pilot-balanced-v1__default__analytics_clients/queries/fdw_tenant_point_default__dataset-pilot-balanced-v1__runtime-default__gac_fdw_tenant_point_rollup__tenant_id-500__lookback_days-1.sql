select
  e.tenant_id,
  count(*) as events_count,
  sum(e.value) as total_value,
  avg(e.value) as avg_value,
  max(e.created_at) as last_event_at
from fdw_eu.events e
where e.tenant_id = 500::bigint
  and e.created_at >= now() - make_interval(days => 1::int)
group by e.tenant_id;
