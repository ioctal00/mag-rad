select
  user_segment,
  user_status,
  home_region,
  sum(events_count) as events_count,
  sum(tenant_count) as tenant_count,
  sum(total_value) as total_value,
  sum(total_value) / nullif(sum(events_count), 0) as avg_value
from etl.global_user_topk_rollup
where event_day >= current_date - 7::int
group by user_segment, user_status, home_region
order by total_value desc, user_segment, user_status, home_region
limit 25;
