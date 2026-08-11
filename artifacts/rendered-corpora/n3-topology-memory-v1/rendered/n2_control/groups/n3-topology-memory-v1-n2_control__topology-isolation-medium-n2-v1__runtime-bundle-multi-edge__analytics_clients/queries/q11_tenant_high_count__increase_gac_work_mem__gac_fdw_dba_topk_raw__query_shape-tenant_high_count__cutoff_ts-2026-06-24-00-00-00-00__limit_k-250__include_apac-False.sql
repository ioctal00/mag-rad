with events_all as materialized (
  select 'eu'::text as source_region, e.event_id, e.tenant_id, e.user_id,
         e.value, e.created_at
  from fdw_eu.events e
  where e.created_at >= timestamptz '2026-06-24 00:00:00+00'
  union all
  select 'us'::text as source_region, e.event_id, e.tenant_id, e.user_id,
         e.value, e.created_at
  from fdw_us.events e
  where e.created_at >= timestamptz '2026-06-24 00:00:00+00'

)

select source_region, tenant_id as key_1, null::bigint as key_2,
       null::timestamptz as bucket_at, count(*)::double precision as metric,
       null::bigint as event_id, null::timestamptz as created_at
from events_all
where value >= 750.0
group by source_region, tenant_id
order by metric desc, source_region, key_1

limit 250;
