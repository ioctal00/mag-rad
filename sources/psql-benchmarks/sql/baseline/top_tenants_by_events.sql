select
  tenant_id,
  count(*) as event_count
from events
group by tenant_id
order by event_count desc, tenant_id
limit :limit_rows;
