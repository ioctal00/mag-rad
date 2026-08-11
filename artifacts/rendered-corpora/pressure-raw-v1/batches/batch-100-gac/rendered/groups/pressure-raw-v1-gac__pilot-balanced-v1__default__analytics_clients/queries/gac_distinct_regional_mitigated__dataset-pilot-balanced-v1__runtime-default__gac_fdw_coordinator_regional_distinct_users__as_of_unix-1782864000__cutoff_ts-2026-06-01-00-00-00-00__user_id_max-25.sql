with regional_users as (
  select e.user_id
  from fdw_eu.events e
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and e.user_id <= 25::bigint
  group by e.user_id
  union all
  select e.user_id
  from fdw_us.events e
  where e.created_at >= timestamptz '2026-06-01 00:00:00+00'
    and e.user_id <= 25::bigint
  group by e.user_id
)
select distinct user_id
from regional_users
order by user_id;
