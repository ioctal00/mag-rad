with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.votes AS v, stats_eu.users AS u
WHERE u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.CreationDate >= CAST('2010-10-01 20:45:26' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-05 12:51:17' AS timestamp)
  AND v.BountyAmount <= 100
  AND u.UpVotes = 0
  AND u.CreationDate <= CAST('2014-09-12 03:25:34' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.votes AS v, stats_us.users AS u
WHERE u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.CreationDate >= CAST('2010-10-01 20:45:26' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-05 12:51:17' AS timestamp)
  AND v.BountyAmount <= 100
  AND u.UpVotes = 0
  AND u.CreationDate <= CAST('2014-09-12 03:25:34' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
