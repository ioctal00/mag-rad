with events_all as materialized (
  select 'eu'::text as source_region, e.event_id, e.tenant_id, e.user_id,
         e.value, e.created_at
  from fdw_eu.events e
  where e.created_at >= timestamptz '2026-06-29 00:00:00+00'
  union all
  select 'us'::text as source_region, e.event_id, e.tenant_id, e.user_id,
         e.value, e.created_at
  from fdw_us.events e
  where e.created_at >= timestamptz '2026-06-29 00:00:00+00'

  union all
  select 'apac'::text as source_region, e.event_id, e.tenant_id, e.user_id,
         e.value, e.created_at
  from fdw_apac.events e
  where e.created_at >= timestamptz '2026-06-29 00:00:00+00'

)

select source_region, tenant_id as key_1, user_id as key_2,
       null::timestamptz as bucket_at,
       round(ln(1.0 + abs(value::double precision))::numeric, 6)::double precision
         as metric, event_id, created_at
from events_all
order by metric desc, source_region, key_1, key_2, event_id

limit 50;
