with regional_candidates as (
  (
    select
      'eu'::text as source_region,
      e.event_id,
      e.tenant_id,
      e.user_id,
      e.value
    from fdw_eu.events e
    where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    order by e.value desc, e.tenant_id, e.event_id
    limit 5000
  )
  union all
  (
    select
      'us'::text as source_region,
      e.event_id,
      e.tenant_id,
      e.user_id,
      e.value
    from fdw_us.events e
    where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    order by e.value desc, e.tenant_id, e.event_id
    limit 5000
  )
)
select
  source_region,
  event_id,
  tenant_id,
  user_id,
  value
from regional_candidates
order by value desc, source_region, tenant_id, event_id
limit 5000;
