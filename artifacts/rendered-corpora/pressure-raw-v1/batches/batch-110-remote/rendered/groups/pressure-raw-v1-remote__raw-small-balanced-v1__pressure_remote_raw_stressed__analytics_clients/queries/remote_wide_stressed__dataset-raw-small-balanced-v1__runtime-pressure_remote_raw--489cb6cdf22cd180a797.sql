with regional_events as (
  select
    'eu'::text as source_region,
    e.event_id,
    e.tenant_id,
    e.user_id,
    e.value,
    e.created_at,
    e.synthetic_payload
  from (
    select
      event_id,
      tenant_id,
      user_id,
      value,
      created_at,
      repeat(
        md5(event_id::text || ':' || tenant_id::text || ':' || user_id::text),
        8::int
      )::varchar(256) as synthetic_payload
    from fdw_eu.events
    where created_at >= coalesce(to_timestamp(nullif(1782864000, 0)), now()) - make_interval(days => 7::int)
      and value >= 0::double precision
    order by created_at desc, tenant_id, event_id
    limit 10000
  ) e
  union all
  select
    'us'::text as source_region,
    e.event_id,
    e.tenant_id,
    e.user_id,
    e.value,
    e.created_at,
    e.synthetic_payload
  from (
    select
      event_id,
      tenant_id,
      user_id,
      value,
      created_at,
      repeat(
        md5(event_id::text || ':' || tenant_id::text || ':' || user_id::text),
        8::int
      )::varchar(256) as synthetic_payload
    from fdw_us.events
    where created_at >= coalesce(to_timestamp(nullif(1782864000, 0)), now()) - make_interval(days => 7::int)
      and value >= 0::double precision
    order by created_at desc, tenant_id, event_id
    limit 10000
  ) e
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
limit 10000;
