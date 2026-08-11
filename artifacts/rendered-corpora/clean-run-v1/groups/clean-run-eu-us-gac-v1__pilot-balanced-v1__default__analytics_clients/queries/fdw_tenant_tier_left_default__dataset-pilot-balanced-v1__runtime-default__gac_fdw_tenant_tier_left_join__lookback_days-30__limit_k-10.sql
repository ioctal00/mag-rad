select
  coalesce(t.tenant_tier, 'unknown') as tenant_tier,
  date_trunc('day', e.created_at) as event_day,
  count(*) as events_count,
  count(distinct e.tenant_id) as tenant_count,
  sum(e.value) as total_value,
  avg(e.value) as avg_value
from fdw_eu.events e
left join fdw_eu.tenants t
  on t.tenant_id = e.tenant_id
where e.created_at >= now() - make_interval(days => 30::int)
group by coalesce(t.tenant_tier, 'unknown'), date_trunc('day', e.created_at)
order by event_day, total_value desc, tenant_tier
limit 10;
