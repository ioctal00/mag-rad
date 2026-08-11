select
  tenant_id,
  count(*) as transformed_high_value_events
from events
where sqrt(value) > :sqrt_min_value
group by tenant_id
order by transformed_high_value_events desc, tenant_id;
