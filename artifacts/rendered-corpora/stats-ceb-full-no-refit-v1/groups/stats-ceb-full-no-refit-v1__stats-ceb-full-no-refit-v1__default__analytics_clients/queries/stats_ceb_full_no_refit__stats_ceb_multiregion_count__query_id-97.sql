with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.CreationDate >= CAST('2010-07-27 12:03:40' AS timestamp)
  AND p.Score >= 0
  AND p.Score <= 28
  AND p.ViewCount >= 0
  AND p.ViewCount <= 6517
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 5
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 8
  AND p.CreationDate >= CAST('2010-07-27 11:29:20' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-13 02:50:15' AS timestamp)
  AND u.Views >= 0
  AND u.CreationDate >= CAST('2010-07-27 09:38:05' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.CreationDate >= CAST('2010-07-27 12:03:40' AS timestamp)
  AND p.Score >= 0
  AND p.Score <= 28
  AND p.ViewCount >= 0
  AND p.ViewCount <= 6517
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 5
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 8
  AND p.CreationDate >= CAST('2010-07-27 11:29:20' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-13 02:50:15' AS timestamp)
  AND u.Views >= 0
  AND u.CreationDate >= CAST('2010-07-27 09:38:05' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
