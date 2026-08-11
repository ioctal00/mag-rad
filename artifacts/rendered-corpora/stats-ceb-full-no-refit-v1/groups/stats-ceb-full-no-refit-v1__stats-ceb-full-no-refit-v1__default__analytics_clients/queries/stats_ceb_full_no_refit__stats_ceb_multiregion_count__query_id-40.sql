with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postLinks AS pl,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE p.Id = pl.RelatedPostId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND pl.LinkTypeId = 1
  AND p.Score >= -1
  AND p.CommentCount <= 8
  AND p.CreationDate >= CAST('2010-07-21 12:30:43' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-07 01:11:03' AS timestamp)
  AND u.Views <= 40
  AND u.CreationDate >= CAST('2010-07-26 19:11:25' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-11 22:26:42' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postLinks AS pl,
  stats_us.posts AS p,
  stats_us.users AS u,
  stats_us.badges AS b
WHERE p.Id = pl.RelatedPostId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND pl.LinkTypeId = 1
  AND p.Score >= -1
  AND p.CommentCount <= 8
  AND p.CreationDate >= CAST('2010-07-21 12:30:43' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-07 01:11:03' AS timestamp)
  AND u.Views <= 40
  AND u.CreationDate >= CAST('2010-07-26 19:11:25' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-11 22:26:42' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
