with regional_candidates as (
  (
select 'eu'::text as source_region, e.tenant_id as key_1,
       e.user_id as key_2, null::timestamptz as bucket_at,
       round(
         (e.value::double precision / (1 + (e.tenant_id % 17))::double precision)::numeric,
         6
       )::double precision as metric,
       e.event_id, e.created_at
from fdw_eu.events e
where e.created_at >= timestamptz '2026-06-30 00:00:00+00'
order by metric desc, key_1, key_2, event_id

limit 500)
  union all
  (
select 'us'::text as source_region, e.tenant_id as key_1,
       e.user_id as key_2, null::timestamptz as bucket_at,
       round(
         (e.value::double precision / (1 + (e.tenant_id % 17))::double precision)::numeric,
         6
       )::double precision as metric,
       e.event_id, e.created_at
from fdw_us.events e
where e.created_at >= timestamptz '2026-06-30 00:00:00+00'
order by metric desc, key_1, key_2, event_id

limit 500)

  union all
  (
select 'apac'::text as source_region, e.tenant_id as key_1,
       e.user_id as key_2, null::timestamptz as bucket_at,
       round(
         (e.value::double precision / (1 + (e.tenant_id % 17))::double precision)::numeric,
         6
       )::double precision as metric,
       e.event_id, e.created_at
from fdw_apac.events e
where e.created_at >= timestamptz '2026-06-30 00:00:00+00'
order by metric desc, key_1, key_2, event_id

limit 500)

)
select source_region, key_1, key_2, bucket_at, metric, event_id, created_at
from regional_candidates

order by metric desc, source_region, key_1, key_2, bucket_at, event_id

limit 500;
