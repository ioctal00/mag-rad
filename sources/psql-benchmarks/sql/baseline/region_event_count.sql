select
  t.region,
  count(*) as event_count
from events e
join tenants t on t.tenant_id = e.tenant_id
group by t.region
order by t.region;
