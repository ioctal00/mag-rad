with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.badges AS b, stats_eu.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = b.UserId
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-24 06:46:49' AS timestamp)
  AND b.Date >= CAST('2010-07-19 20:34:06' AS timestamp)
  AND b.Date <= CAST('2014-09-12 15:11:36' AS timestamp)
  AND u.UpVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.badges AS b, stats_us.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = b.UserId
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-24 06:46:49' AS timestamp)
  AND b.Date >= CAST('2010-07-19 20:34:06' AS timestamp)
  AND b.Date <= CAST('2014-09-12 15:11:36' AS timestamp)
  AND u.UpVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
