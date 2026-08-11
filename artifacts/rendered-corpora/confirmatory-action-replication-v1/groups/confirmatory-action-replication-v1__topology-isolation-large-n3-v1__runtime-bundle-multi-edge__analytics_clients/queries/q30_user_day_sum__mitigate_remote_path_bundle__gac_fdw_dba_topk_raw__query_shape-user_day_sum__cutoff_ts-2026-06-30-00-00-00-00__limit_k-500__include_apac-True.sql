with events_all as materialized (
  select 'eu'::text as source_region, e.event_id, e.tenant_id, e.user_id,
         e.value, e.created_at
  from fdw_eu.events e
  where e.created_at >= timestamptz '2026-06-30 00:00:00+00'
  union all
  select 'us'::text as source_region, e.event_id, e.tenant_id, e.user_id,
         e.value, e.created_at
  from fdw_us.events e
  where e.created_at >= timestamptz '2026-06-30 00:00:00+00'

  union all
  select 'apac'::text as source_region, e.event_id, e.tenant_id, e.user_id,
         e.value, e.created_at
  from fdw_apac.events e
  where e.created_at >= timestamptz '2026-06-30 00:00:00+00'

)

select source_region, user_id as key_1, null::bigint as key_2,
       date_trunc('day', created_at) as bucket_at,
       round(sum(value)::numeric, 6)::double precision as metric, null::bigint as event_id,
       null::timestamptz as created_at
from events_all
group by source_region, user_id, date_trunc('day', created_at)
order by metric desc, source_region, key_1, bucket_at

limit 500;
