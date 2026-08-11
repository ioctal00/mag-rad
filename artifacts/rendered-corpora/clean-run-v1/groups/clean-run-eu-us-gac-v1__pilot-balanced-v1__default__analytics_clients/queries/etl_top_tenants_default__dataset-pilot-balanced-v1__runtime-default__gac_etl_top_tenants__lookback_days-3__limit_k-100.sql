select
  tenant_id,
  sum(events_count) as events_count,
  sum(total_value) as total_value,
  avg(avg_value) as mean_tenant_avg_value,
  max(last_event_at) as last_event_at
from etl.daily_tenant_rollup
where event_day >= current_date - 3::int
group by tenant_id
order by total_value desc, tenant_id
limit 100;
