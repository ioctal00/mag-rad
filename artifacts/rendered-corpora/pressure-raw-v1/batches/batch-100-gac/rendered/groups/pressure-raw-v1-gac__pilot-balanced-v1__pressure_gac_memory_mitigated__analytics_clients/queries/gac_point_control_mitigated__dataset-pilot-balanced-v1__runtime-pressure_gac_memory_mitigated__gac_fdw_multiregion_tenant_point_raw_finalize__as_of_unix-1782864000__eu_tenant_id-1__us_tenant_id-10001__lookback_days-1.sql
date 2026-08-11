with regional_events as materialized (
  select
    'eu'::text as source_region,
    e.tenant_id,
    e.value
  from fdw_eu.events e
  where e.tenant_id = 1::bigint
    and e.created_at >= coalesce(to_timestamp(nullif(1782864000, 0)), now()) - make_interval(days => 1::int)
  union all
  select
    'us'::text as source_region,
    e.tenant_id,
    e.value
  from fdw_us.events e
  where e.tenant_id = 10001::bigint
    and e.created_at >= coalesce(to_timestamp(nullif(1782864000, 0)), now()) - make_interval(days => 1::int)
)
select
  source_region,
  tenant_id,
  count(*) as events_count,
  sum(value) as total_value,
  avg(value) as avg_value
from regional_events
group by source_region, tenant_id
order by source_region, tenant_id;
