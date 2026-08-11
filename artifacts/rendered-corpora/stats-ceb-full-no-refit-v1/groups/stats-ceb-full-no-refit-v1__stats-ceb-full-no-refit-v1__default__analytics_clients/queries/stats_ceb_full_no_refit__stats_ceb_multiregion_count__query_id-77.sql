with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND p.Id = c.PostId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND p.ViewCount >= 0
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 7
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 17
  AND v.VoteTypeId = 5
  AND b.Date >= CAST('2010-08-01 02:54:53' AS timestamp)
  AND u.Reputation >= 1
  AND u.Views >= 0
  AND u.CreationDate >= CAST('2010-08-19 06:26:34' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-11 05:22:26' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND p.Id = c.PostId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND p.ViewCount >= 0
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 7
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 17
  AND v.VoteTypeId = 5
  AND b.Date >= CAST('2010-08-01 02:54:53' AS timestamp)
  AND u.Reputation >= 1
  AND u.Views >= 0
  AND u.CreationDate >= CAST('2010-08-19 06:26:34' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-11 05:22:26' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
