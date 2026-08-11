select
  e.event_id,
  e.tenant_id,
  e.user_id,
  e.value,
  e.created_at,
  repeat(
    md5(e.event_id::text || ':' || e.tenant_id::text || ':' || e.user_id::text),
    64::int
  )::varchar(512) as synthetic_payload
from fdw_eu.events e
where e.created_at >= now() - make_interval(days => 7::int)
  and e.value >= 500::double precision
order by e.created_at desc, e.tenant_id, e.event_id
limit 250;
