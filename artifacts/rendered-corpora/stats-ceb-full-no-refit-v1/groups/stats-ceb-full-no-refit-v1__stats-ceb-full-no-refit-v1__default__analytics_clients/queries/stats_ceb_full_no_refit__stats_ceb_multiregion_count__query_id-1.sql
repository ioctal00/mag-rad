with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.badges AS b, stats_eu.users AS u
WHERE b.UserId = u.Id
  AND u.UpVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.badges AS b, stats_us.users AS u
WHERE b.UserId = u.Id
  AND u.UpVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
