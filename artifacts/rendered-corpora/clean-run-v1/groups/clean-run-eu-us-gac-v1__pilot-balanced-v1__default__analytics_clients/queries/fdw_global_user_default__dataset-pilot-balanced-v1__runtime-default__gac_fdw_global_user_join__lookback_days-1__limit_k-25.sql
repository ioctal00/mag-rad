select
  gu.user_segment,
  gu.user_status,
  gu.home_region,
  count(*) as events_count,
  count(distinct e.tenant_id) as tenant_count,
  sum(e.value) as total_value,
  avg(e.value) as avg_value
from fdw_eu.events e
join fdw_eu.global_users gu
  on gu.tenant_id = e.tenant_id
 and gu.user_id = e.user_id
where e.created_at >= now() - make_interval(days => 1::int)
group by gu.user_segment, gu.user_status, gu.home_region
order by total_value desc, gu.user_segment, gu.user_status, gu.home_region
limit 25;
