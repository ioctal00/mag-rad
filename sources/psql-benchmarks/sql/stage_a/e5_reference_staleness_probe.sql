select
  t.region,
  t.tenant_tier,
  t.tenant_status,
  max(t.dimension_version) as max_dimension_version,
  max(t.updated_at) as newest_tenant_updated_at,
  count(distinct e.tenant_id) as tenant_count,
  count(*) as events_count,
  sum(e.value) as total_value
from events e
join tenants t on t.tenant_id = e.tenant_id
where e.created_at >= now() - (:lookback_days || ' days')::interval
  and t.tenant_tier = :'tenant_tier'
  and t.tenant_status = :'tenant_status'
group by t.region, t.tenant_tier, t.tenant_status
order by t.region, t.tenant_tier, t.tenant_status;
