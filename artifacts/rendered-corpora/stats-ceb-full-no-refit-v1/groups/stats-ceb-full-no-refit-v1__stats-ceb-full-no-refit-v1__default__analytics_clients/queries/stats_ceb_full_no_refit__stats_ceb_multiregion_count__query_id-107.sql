with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = b.UserId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.Score = 1
  AND c.CreationDate >= CAST('2010-08-27 14:12:07' AS timestamp)
  AND v.VoteTypeId = 5
  AND v.CreationDate >= CAST('2010-07-19 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-13 00:00:00' AS timestamp)
  AND b.Date <= CAST('2014-08-19 10:32:13' AS timestamp)
  AND u.Reputation >= 1
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = b.UserId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.Score = 1
  AND c.CreationDate >= CAST('2010-08-27 14:12:07' AS timestamp)
  AND v.VoteTypeId = 5
  AND v.CreationDate >= CAST('2010-07-19 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-13 00:00:00' AS timestamp)
  AND b.Date <= CAST('2014-08-19 10:32:13' AS timestamp)
  AND u.Reputation >= 1
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
