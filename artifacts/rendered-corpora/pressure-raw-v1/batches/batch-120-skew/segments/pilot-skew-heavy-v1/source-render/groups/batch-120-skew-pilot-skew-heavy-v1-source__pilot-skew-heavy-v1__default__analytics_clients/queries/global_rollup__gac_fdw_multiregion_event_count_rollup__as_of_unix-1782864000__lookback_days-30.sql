with events_all as (
  select
    'eu'::text as region_id,
    e.created_at
  from fdw_eu.events e
  union all
  select
    'us'::text as region_id,
    e.created_at
  from fdw_us.events e
)
select
  region_id,
  count(*) as event_count
from events_all
where created_at >= coalesce(to_timestamp(nullif(1782864000, 0)), now()) - make_interval(days => 30::int)
group by region_id
order by region_id;
