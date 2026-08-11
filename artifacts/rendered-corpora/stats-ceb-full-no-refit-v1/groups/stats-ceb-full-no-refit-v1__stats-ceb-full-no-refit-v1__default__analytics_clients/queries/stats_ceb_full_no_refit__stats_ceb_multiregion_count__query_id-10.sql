with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.posts AS p, stats_eu.users AS u
WHERE c.UserId = u.Id
  AND u.Id = p.OwnerUserId
  AND c.CreationDate >= CAST('2010-08-05 00:36:02' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-08 16:50:49' AS timestamp)
  AND p.ViewCount >= 0
  AND p.ViewCount <= 2897
  AND p.CommentCount >= 0
  AND p.CommentCount <= 16
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 10
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.posts AS p, stats_us.users AS u
WHERE c.UserId = u.Id
  AND u.Id = p.OwnerUserId
  AND c.CreationDate >= CAST('2010-08-05 00:36:02' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-08 16:50:49' AS timestamp)
  AND p.ViewCount >= 0
  AND p.ViewCount <= 2897
  AND p.CommentCount >= 0
  AND p.CommentCount <= 16
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 10
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
