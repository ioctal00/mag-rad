with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.badges AS b, stats_eu.users AS u
WHERE c.UserId = u.Id
  AND b.UserId = u.Id
  AND c.CreationDate >= CAST('2010-08-12 20:27:30' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-12 12:49:19' AS timestamp)
  AND u.Views >= 0
  AND u.DownVotes >= 0
  AND u.DownVotes <= 2
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.badges AS b, stats_us.users AS u
WHERE c.UserId = u.Id
  AND b.UserId = u.Id
  AND c.CreationDate >= CAST('2010-08-12 20:27:30' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-12 12:49:19' AS timestamp)
  AND u.Views >= 0
  AND u.DownVotes >= 0
  AND u.DownVotes <= 2
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
