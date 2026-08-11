with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.votes AS v,
  stats_eu.posts AS p,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = v.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND p.Score >= 0
  AND p.Score <= 30
  AND p.CommentCount = 0
  AND p.CreationDate >= CAST('2010-07-27 15:30:31' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-04 17:45:10' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.votes AS v,
  stats_us.posts AS p,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = v.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND p.Score >= 0
  AND p.Score <= 30
  AND p.CommentCount = 0
  AND p.CreationDate >= CAST('2010-07-27 15:30:31' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-04 17:45:10' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
