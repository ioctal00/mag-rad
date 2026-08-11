with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.posts AS p, stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND c.UserId = u.Id
  AND c.Score = 0
  AND p.AnswerCount <= 5
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
  AND p.FavoriteCount <= 27
  AND u.Reputation >= 1
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.posts AS p, stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND c.UserId = u.Id
  AND c.Score = 0
  AND p.AnswerCount <= 5
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
  AND p.FavoriteCount <= 27
  AND u.Reputation >= 1
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
