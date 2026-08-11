with regional_candidates as (
  (
select 'eu'::text as source_region, e.tenant_id as key_1,
       e.user_id as key_2, null::timestamptz as bucket_at,
       e.value::double precision as metric, e.event_id, e.created_at
from fdw_eu.events e
where e.created_at >= timestamptz '2026-06-29 00:00:00+00'
order by metric asc, key_1, key_2, event_id

limit 100)
  union all
  (
select 'us'::text as source_region, e.tenant_id as key_1,
       e.user_id as key_2, null::timestamptz as bucket_at,
       e.value::double precision as metric, e.event_id, e.created_at
from fdw_us.events e
where e.created_at >= timestamptz '2026-06-29 00:00:00+00'
order by metric asc, key_1, key_2, event_id

limit 100)

)
select source_region, key_1, key_2, bucket_at, metric, event_id, created_at
from regional_candidates

order by metric asc, source_region, key_1, key_2, bucket_at, event_id

limit 100;
