select tenant_id,
       count(*) as events_count,
       sum(value) as total_value
from events
where created_at >= now() - make_interval(days => 30::int)
  and value >= 900::double precision
group by tenant_id
order by total_value desc, tenant_id;
