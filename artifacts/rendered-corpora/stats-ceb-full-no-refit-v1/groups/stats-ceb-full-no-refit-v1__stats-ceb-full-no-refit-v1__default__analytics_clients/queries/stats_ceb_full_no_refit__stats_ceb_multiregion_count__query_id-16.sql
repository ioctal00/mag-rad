with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.badges AS b, stats_eu.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = b.UserId
  AND c.Score = 0
  AND b.Date >= CAST('2010-07-19 20:54:06' AS timestamp)
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 17
  AND u.CreationDate >= CAST('2010-08-06 07:03:05' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-08 04:18:44' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.badges AS b, stats_us.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = b.UserId
  AND c.Score = 0
  AND b.Date >= CAST('2010-07-19 20:54:06' AS timestamp)
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 17
  AND u.CreationDate >= CAST('2010-08-06 07:03:05' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-08 04:18:44' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
