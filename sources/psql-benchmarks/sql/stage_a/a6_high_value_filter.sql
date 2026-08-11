select
  tenant_id,
  count(*) as high_value_events
from events
where value > :min_value
  and created_at >= now() - (:lookback_days || ' days')::interval
group by tenant_id
order by high_value_events desc, tenant_id;
