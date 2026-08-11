with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postLinks AS pl,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE p.Id = pl.RelatedPostId
  AND p.Id = c.PostId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-04-12 15:23:59' AS timestamp)
  AND p.Score = 1
  AND p.ViewCount >= 0
  AND p.FavoriteCount >= 0
  AND u.CreationDate >= CAST('2011-02-08 18:11:37' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postLinks AS pl,
  stats_us.posts AS p,
  stats_us.users AS u,
  stats_us.badges AS b
WHERE p.Id = pl.RelatedPostId
  AND p.Id = c.PostId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-04-12 15:23:59' AS timestamp)
  AND p.Score = 1
  AND p.ViewCount >= 0
  AND p.FavoriteCount >= 0
  AND u.CreationDate >= CAST('2011-02-08 18:11:37' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
