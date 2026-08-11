with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postLinks AS pl,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE p.Id = pl.RelatedPostId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND pl.CreationDate <= CAST('2014-08-17 01:23:50' AS timestamp)
  AND p.Score >= -1
  AND p.Score <= 10
  AND p.AnswerCount <= 5
  AND p.CommentCount = 2
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 6
  AND u.Views <= 33
  AND u.DownVotes >= 0
  AND u.CreationDate >= CAST('2010-08-19 17:31:36' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-06 07:23:12' AS timestamp)
  AND b.Date <= CAST('2014-09-10 22:50:06' AS timestamp)
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
  AND pl.CreationDate <= CAST('2014-08-17 01:23:50' AS timestamp)
  AND p.Score >= -1
  AND p.Score <= 10
  AND p.AnswerCount <= 5
  AND p.CommentCount = 2
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 6
  AND u.Views <= 33
  AND u.DownVotes >= 0
  AND u.CreationDate >= CAST('2010-08-19 17:31:36' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-06 07:23:12' AS timestamp)
  AND b.Date <= CAST('2014-09-10 22:50:06' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
