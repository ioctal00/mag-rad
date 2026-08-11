with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.votes AS v, stats_eu.posts AS p, stats_eu.users AS u
WHERE v.PostId = p.Id
  AND v.UserId = u.Id
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND p.Score >= -1
  AND p.CreationDate >= CAST('2010-10-21 13:21:24' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-09 15:12:22' AS timestamp)
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-07-27 17:15:57' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-03 12:47:42' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.votes AS v, stats_us.posts AS p, stats_us.users AS u
WHERE v.PostId = p.Id
  AND v.UserId = u.Id
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND p.Score >= -1
  AND p.CreationDate >= CAST('2010-10-21 13:21:24' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-09 15:12:22' AS timestamp)
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-07-27 17:15:57' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-03 12:47:42' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
