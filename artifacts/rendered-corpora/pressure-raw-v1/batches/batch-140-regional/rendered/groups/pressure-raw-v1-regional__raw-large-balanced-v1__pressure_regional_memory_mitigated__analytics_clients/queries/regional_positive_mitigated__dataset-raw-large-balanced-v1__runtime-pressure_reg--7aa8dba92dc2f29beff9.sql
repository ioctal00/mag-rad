select
  e.tenant_id,
  e.user_id,
  count(*) as events_count,
  round(sum(e.value::numeric), 6) as total_value,
  round(avg(e.value::numeric), 6) as avg_value,
  max(e.created_at) as last_event_at
from fdw_eu.events e
where e.created_at >= timestamptz '2026-06-24 00:00:00+00'
  and mod(e.tenant_id, 1::bigint) = 0
group by e.tenant_id, e.user_id
order by total_value desc, e.tenant_id, e.user_id
limit 25000;
