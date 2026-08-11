with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.votes AS v, stats_eu.posts AS p, stats_eu.users AS u
WHERE v.UserId = p.OwnerUserId
  AND p.OwnerUserId = u.Id
  AND p.CommentCount >= 0
  AND p.CommentCount <= 12
  AND u.CreationDate >= CAST('2010-07-22 04:38:06' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-08 15:55:02' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.votes AS v, stats_us.posts AS p, stats_us.users AS u
WHERE v.UserId = p.OwnerUserId
  AND p.OwnerUserId = u.Id
  AND p.CommentCount >= 0
  AND p.CommentCount <= 12
  AND u.CreationDate >= CAST('2010-07-22 04:38:06' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-08 15:55:02' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
