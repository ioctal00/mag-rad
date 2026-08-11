with regional_events as (
  select
    'eu'::text as source_region,
    e.event_id,
    e.tenant_id,
    e.user_id,
    e.value,
    e.created_at,
    repeat(
      md5(e.event_id::text || ':' || e.tenant_id::text || ':' || e.user_id::text),
      16::int
    )::varchar(512) as synthetic_payload
  from fdw_eu.events e
  where e.created_at >= now() - make_interval(days => 7::int)
    and e.value >= 900::double precision
  union all
  select
    'us'::text as source_region,
    e.event_id,
    e.tenant_id,
    e.user_id,
    e.value,
    e.created_at,
    repeat(
      md5(e.event_id::text || ':' || e.tenant_id::text || ':' || e.user_id::text),
      16::int
    )::varchar(512) as synthetic_payload
  from fdw_us.events e
  where e.created_at >= now() - make_interval(days => 7::int)
    and e.value >= 900::double precision
)
select
  source_region,
  event_id,
  tenant_id,
  user_id,
  value,
  created_at,
  synthetic_payload
from regional_events
order by created_at desc, source_region, tenant_id, event_id
limit 100;
