with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE p.Id = pl.RelatedPostId
  AND b.UserId = u.Id
  AND c.UserId = u.Id
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND p.Id = ph.PostId
  AND c.Score = 0
  AND p.ViewCount >= 0
  AND p.AnswerCount <= 5
  AND p.CommentCount <= 12
  AND p.FavoriteCount >= 0
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-02-16 20:04:50' AS timestamp)
  AND pl.CreationDate <= CAST('2014-09-01 16:48:04' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-19 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-08-31 00:00:00' AS timestamp)
  AND b.Date >= CAST('2010-08-06 10:36:45' AS timestamp)
  AND b.Date <= CAST('2014-09-12 07:19:35' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE p.Id = pl.RelatedPostId
  AND b.UserId = u.Id
  AND c.UserId = u.Id
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND p.Id = ph.PostId
  AND c.Score = 0
  AND p.ViewCount >= 0
  AND p.AnswerCount <= 5
  AND p.CommentCount <= 12
  AND p.FavoriteCount >= 0
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-02-16 20:04:50' AS timestamp)
  AND pl.CreationDate <= CAST('2014-09-01 16:48:04' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-19 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-08-31 00:00:00' AS timestamp)
  AND b.Date >= CAST('2010-08-06 10:36:45' AS timestamp)
  AND b.Date <= CAST('2014-09-12 07:19:35' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
