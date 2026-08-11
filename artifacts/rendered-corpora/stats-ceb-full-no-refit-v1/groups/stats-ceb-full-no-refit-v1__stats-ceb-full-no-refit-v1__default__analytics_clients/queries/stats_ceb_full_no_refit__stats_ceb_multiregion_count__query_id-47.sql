with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = p.OwnerUserId
  AND p.OwnerUserId = ph.UserId
  AND ph.UserId = v.UserId
  AND p.Score <= 13
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.FavoriteCount <= 2
  AND ph.PostHistoryTypeId = 3
  AND v.BountyAmount <= 50
  AND u.DownVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = p.OwnerUserId
  AND p.OwnerUserId = ph.UserId
  AND ph.UserId = v.UserId
  AND p.Score <= 13
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.FavoriteCount <= 2
  AND ph.PostHistoryTypeId = 3
  AND v.BountyAmount <= 50
  AND u.DownVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
