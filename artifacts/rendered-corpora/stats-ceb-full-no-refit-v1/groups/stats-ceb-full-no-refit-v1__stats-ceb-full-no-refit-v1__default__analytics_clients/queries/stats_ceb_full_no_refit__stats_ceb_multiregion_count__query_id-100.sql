with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND p.Score >= 0
  AND p.Score <= 16
  AND p.ViewCount >= 0
  AND p.CreationDate <= CAST('2014-09-09 12:00:50' AS timestamp)
  AND u.Reputation >= 1
  AND u.CreationDate >= CAST('2010-07-19 19:08:49' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-28 12:15:56' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND p.Score >= 0
  AND p.Score <= 16
  AND p.ViewCount >= 0
  AND p.CreationDate <= CAST('2014-09-09 12:00:50' AS timestamp)
  AND u.Reputation >= 1
  AND u.CreationDate >= CAST('2010-07-19 19:08:49' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-28 12:15:56' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
