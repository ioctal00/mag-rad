select
  t.tenant_tier,
  u.user_segment,
  date_trunc('day', e.created_at) as event_day,
  count(*) as events_count,
  sum(e.value) as total_value,
  avg(e.value) as avg_value
from fdw_eu.events e
join fdw_eu.tenants t
  on t.tenant_id = e.tenant_id
join fdw_eu.users u
  on u.tenant_id = e.tenant_id
 and u.user_id = e.user_id
where e.created_at >= now() - make_interval(days => 30::int)
group by t.tenant_tier, u.user_segment, date_trunc('day', e.created_at)
order by event_day, total_value desc, t.tenant_tier, u.user_segment
limit 50;
