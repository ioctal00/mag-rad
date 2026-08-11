select
  t.region,
  t.tenant_tier,
  t.tenant_status,
  date_trunc('day', e.created_at) as day,
  max(t.dimension_version) as max_dimension_version,
  count(distinct e.tenant_id) as tenant_count,
  count(*) as events_count,
  sum(e.value) as total_value
from events e
join tenants t on e.tenant_id = t.tenant_id
where e.created_at >= now() - (:lookback_days || ' days')::interval
group by t.region, t.tenant_tier, t.tenant_status, day
order by day, t.region, t.tenant_tier, t.tenant_status;
