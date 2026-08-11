with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = p.OwnerUserId
  AND p.OwnerUserId = v.UserId
  AND v.UserId = b.UserId
  AND c.Score = 1
  AND p.Score >= -2
  AND p.Score <= 23
  AND p.ViewCount <= 2432
  AND p.CommentCount = 0
  AND p.FavoriteCount >= 0
  AND u.Reputation >= 1
  AND u.Reputation <= 113
  AND u.Views >= 0
  AND u.Views <= 51
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = p.OwnerUserId
  AND p.OwnerUserId = v.UserId
  AND v.UserId = b.UserId
  AND c.Score = 1
  AND p.Score >= -2
  AND p.Score <= 23
  AND p.ViewCount <= 2432
  AND p.CommentCount = 0
  AND p.FavoriteCount >= 0
  AND u.Reputation >= 1
  AND u.Reputation <= 113
  AND u.Views >= 0
  AND u.Views <= 51
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
