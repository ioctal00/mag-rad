select
  tenant_id,
  user_id,
  sum(value) as total_value
from events
where created_at >= now() - (:lookback_days || ' days')::interval
group by tenant_id, user_id
order by total_value desc, tenant_id, user_id
limit :limit_rows;
