with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.badges AS b
WHERE p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND b.UserId = c.UserId
  AND c.CreationDate >= CAST('2010-07-26 20:21:15' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-13 18:12:10' AS timestamp)
  AND p.Score <= 61
  AND p.ViewCount <= 3627
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 5
  AND p.CommentCount <= 8
  AND p.FavoriteCount >= 0
  AND v.VoteTypeId = 2
  AND v.CreationDate >= CAST('2010-07-27 00:00:00' AS timestamp)
  AND b.Date >= CAST('2010-07-30 03:49:24' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.badges AS b
WHERE p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND b.UserId = c.UserId
  AND c.CreationDate >= CAST('2010-07-26 20:21:15' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-13 18:12:10' AS timestamp)
  AND p.Score <= 61
  AND p.ViewCount <= 3627
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 5
  AND p.CommentCount <= 8
  AND p.FavoriteCount >= 0
  AND v.VoteTypeId = 2
  AND v.CreationDate >= CAST('2010-07-27 00:00:00' AS timestamp)
  AND b.Date >= CAST('2010-07-30 03:49:24' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
