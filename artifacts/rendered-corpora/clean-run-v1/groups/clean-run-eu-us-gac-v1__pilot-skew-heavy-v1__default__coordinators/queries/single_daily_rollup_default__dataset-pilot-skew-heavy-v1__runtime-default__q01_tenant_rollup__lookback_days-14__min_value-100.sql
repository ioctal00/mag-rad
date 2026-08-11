select tenant_id,
       count(*) as events_count,
       sum(value) as total_value
from events
where created_at >= now() - make_interval(days => 14::int)
  and value >= 100::double precision
group by tenant_id
order by total_value desc, tenant_id;
