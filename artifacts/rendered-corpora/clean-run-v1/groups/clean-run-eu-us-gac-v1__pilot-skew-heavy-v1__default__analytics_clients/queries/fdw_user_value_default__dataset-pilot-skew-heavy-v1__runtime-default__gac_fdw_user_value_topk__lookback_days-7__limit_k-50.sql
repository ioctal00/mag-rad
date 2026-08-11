select
  e.tenant_id,
  e.user_id,
  count(*) as events_count,
  sum(e.value) as total_value,
  avg(e.value) as avg_value,
  max(e.created_at) as last_event_at
from fdw_eu.events e
where e.created_at >= now() - make_interval(days => 7::int)
group by e.tenant_id, e.user_id
order by total_value desc, e.tenant_id, e.user_id
limit 50;
