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
  AND c.Score = 0
  AND p.Score <= 21
  AND p.AnswerCount <= 3
  AND p.FavoriteCount >= 0
  AND v.CreationDate >= CAST('2010-07-19 00:00:00' AS timestamp)
  AND b.Date <= CAST('2014-09-11 18:35:08' AS timestamp)
  AND u.Reputation <= 240
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
  AND c.Score = 0
  AND p.Score <= 21
  AND p.AnswerCount <= 3
  AND p.FavoriteCount >= 0
  AND v.CreationDate >= CAST('2010-07-19 00:00:00' AS timestamp)
  AND b.Date <= CAST('2014-09-11 18:35:08' AS timestamp)
  AND u.Reputation <= 240
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
