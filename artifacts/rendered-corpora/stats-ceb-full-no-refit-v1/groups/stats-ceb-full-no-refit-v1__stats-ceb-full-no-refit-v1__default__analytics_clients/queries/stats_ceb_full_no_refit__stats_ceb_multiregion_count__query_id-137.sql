with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postLinks AS pl,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND c.CreationDate <= CAST('2014-09-13 20:12:15' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-09-03 21:00:10' AS timestamp)
  AND pl.CreationDate <= CAST('2014-07-30 21:29:52' AS timestamp)
  AND p.Score >= 0
  AND p.Score <= 23
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 10
  AND p.FavoriteCount <= 9
  AND p.CreationDate >= CAST('2010-07-22 12:17:20' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-12 00:27:12' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postLinks AS pl,
  stats_us.posts AS p,
  stats_us.users AS u,
  stats_us.badges AS b
WHERE u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND c.CreationDate <= CAST('2014-09-13 20:12:15' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-09-03 21:00:10' AS timestamp)
  AND pl.CreationDate <= CAST('2014-07-30 21:29:52' AS timestamp)
  AND p.Score >= 0
  AND p.Score <= 23
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 10
  AND p.FavoriteCount <= 9
  AND p.CreationDate >= CAST('2010-07-22 12:17:20' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-12 00:27:12' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
