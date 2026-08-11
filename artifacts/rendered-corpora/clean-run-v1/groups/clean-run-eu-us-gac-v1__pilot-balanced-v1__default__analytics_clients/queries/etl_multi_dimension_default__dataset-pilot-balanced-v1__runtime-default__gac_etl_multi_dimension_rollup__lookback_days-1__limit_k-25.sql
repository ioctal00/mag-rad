select
  tenant_tier,
  user_segment,
  event_day,
  sum(events_count) as events_count,
  sum(total_value) as total_value,
  sum(total_value) / nullif(sum(events_count), 0) as avg_value
from etl.multi_dimension_rollup
where event_day >= current_date - 1::int
group by tenant_tier, user_segment, event_day
order by event_day, total_value desc, tenant_tier, user_segment
limit 25;
