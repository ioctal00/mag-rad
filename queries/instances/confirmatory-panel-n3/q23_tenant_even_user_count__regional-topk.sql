with regional_candidates as (
  (
select 'eu'::text as source_region, e.tenant_id as key_1,
       null::bigint as key_2, null::timestamptz as bucket_at,
       count(*)::double precision as metric, null::bigint as event_id,
       null::timestamptz as created_at
from fdw_eu.events e
where e.created_at >= timestamptz '2026-06-24 00:00:00+00' and e.user_id % 2 = 0
group by e.tenant_id
order by metric desc, key_1

limit 100)
  union all
  (
select 'us'::text as source_region, e.tenant_id as key_1,
       null::bigint as key_2, null::timestamptz as bucket_at,
       count(*)::double precision as metric, null::bigint as event_id,
       null::timestamptz as created_at
from fdw_us.events e
where e.created_at >= timestamptz '2026-06-24 00:00:00+00' and e.user_id % 2 = 0
group by e.tenant_id
order by metric desc, key_1

limit 100)

  union all
  (
select 'apac'::text as source_region, e.tenant_id as key_1,
       null::bigint as key_2, null::timestamptz as bucket_at,
       count(*)::double precision as metric, null::bigint as event_id,
       null::timestamptz as created_at
from fdw_apac.events e
where e.created_at >= timestamptz '2026-06-24 00:00:00+00' and e.user_id % 2 = 0
group by e.tenant_id
order by metric desc, key_1

limit 100)

)
select source_region, key_1, key_2, bucket_at, metric, event_id, created_at
from regional_candidates

order by metric desc, source_region, key_1, key_2, bucket_at, event_id

limit 100;
