select tenant_id,
       user_id,
       sum(value) as total_value
from events
where created_at >= now() - make_interval(days => 30::int)
group by tenant_id, user_id
order by total_value desc, tenant_id, user_id
limit 25;
