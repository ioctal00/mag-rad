with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.votes AS v, stats_eu.users AS u
WHERE u.Id = c.UserId
  AND u.Id = v.UserId
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
  AND u.CreationDate >= CAST('2010-07-19 20:11:48' AS timestamp)
  AND u.CreationDate <= CAST('2014-07-09 20:37:10' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.votes AS v, stats_us.users AS u
WHERE u.Id = c.UserId
  AND u.Id = v.UserId
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
  AND u.CreationDate >= CAST('2010-07-19 20:11:48' AS timestamp)
  AND u.CreationDate <= CAST('2014-07-09 20:37:10' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
