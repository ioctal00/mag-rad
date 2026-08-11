with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE v.UserId = u.Id
  AND c.UserId = u.Id
  AND ph.UserId = u.Id
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-19 19:56:21' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 13:36:12' AS timestamp)
  AND u.Views <= 433
  AND u.DownVotes >= 0
  AND u.CreationDate <= CAST('2014-09-12 21:37:39' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE v.UserId = u.Id
  AND c.UserId = u.Id
  AND ph.UserId = u.Id
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-19 19:56:21' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 13:36:12' AS timestamp)
  AND u.Views <= 433
  AND u.DownVotes >= 0
  AND u.CreationDate <= CAST('2014-09-12 21:37:39' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
