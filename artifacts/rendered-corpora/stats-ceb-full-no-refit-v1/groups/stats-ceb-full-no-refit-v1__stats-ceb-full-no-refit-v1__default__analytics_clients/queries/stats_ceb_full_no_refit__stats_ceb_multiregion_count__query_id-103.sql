with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.votes AS v,
  stats_eu.posts AS p,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = v.UserId
  AND p.PostTypeId = 1
  AND p.CommentCount >= 0
  AND p.CommentCount <= 15
  AND u.Reputation >= 1
  AND u.DownVotes >= 0
  AND u.DownVotes <= 1
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.votes AS v,
  stats_us.posts AS p,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = v.UserId
  AND p.PostTypeId = 1
  AND p.CommentCount >= 0
  AND p.CommentCount <= 15
  AND u.Reputation >= 1
  AND u.DownVotes >= 0
  AND u.DownVotes <= 1
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
