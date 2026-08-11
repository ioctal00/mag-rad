select
  u.user_segment,
  u.user_status,
  count(*) as events_count,
  count(distinct e.tenant_id) as tenant_count,
  sum(e.value) as total_value,
  avg(e.value) as avg_value
from fdw_eu.events e
join fdw_eu.users u
  on u.tenant_id = e.tenant_id
 and u.user_id = e.user_id
where e.created_at >= now() - make_interval(days => 30::int)
group by u.user_segment, u.user_status
order by total_value desc, u.user_segment, u.user_status
limit 100;
