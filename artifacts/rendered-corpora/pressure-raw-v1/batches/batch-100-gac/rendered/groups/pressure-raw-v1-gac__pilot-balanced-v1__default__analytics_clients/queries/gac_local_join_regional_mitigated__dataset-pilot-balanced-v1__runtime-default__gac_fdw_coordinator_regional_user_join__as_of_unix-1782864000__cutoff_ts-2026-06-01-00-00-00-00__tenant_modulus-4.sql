with regional_groups as (
  select
    u.user_segment,
    u.user_status,
    count(*) as events_count,
    round(sum(e.value::numeric), 6) as total_value
  from fdw_eu.events e
  join fdw_eu.users u
    on u.tenant_id = e.tenant_id
   and u.user_id = e.user_id
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and mod(e.tenant_id, 4::bigint) = 0
  group by u.user_segment, u.user_status
  union all
  select
    u.user_segment,
    u.user_status,
    count(*) as events_count,
    round(sum(e.value::numeric), 6) as total_value
  from fdw_us.events e
  join fdw_us.users u
    on u.tenant_id = e.tenant_id
   and u.user_id = e.user_id
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and mod(e.tenant_id, 4::bigint) = 0
  group by u.user_segment, u.user_status
)
select
  user_segment,
  user_status,
  sum(events_count) as events_count,
  round(sum(total_value), 6) as total_value
from regional_groups
group by user_segment, user_status
order by total_value desc, user_segment, user_status;
