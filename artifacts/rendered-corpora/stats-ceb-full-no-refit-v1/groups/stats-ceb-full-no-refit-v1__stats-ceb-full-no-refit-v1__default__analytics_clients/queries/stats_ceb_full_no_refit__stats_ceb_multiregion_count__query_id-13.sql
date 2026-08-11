with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.votes AS v, stats_eu.users AS u
WHERE u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.CreationDate >= CAST('2010-08-10 17:55:45' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 691
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.votes AS v, stats_us.users AS u
WHERE u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.CreationDate >= CAST('2010-08-10 17:55:45' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 691
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
