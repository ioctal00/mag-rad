with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND u.Id = b.UserId
  AND p.Id = ph.PostId
  AND p.AnswerCount >= 0
  AND p.CommentCount >= 0
  AND b.Date <= CAST('2014-09-11 21:46:02' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 642
  AND u.DownVotes >= 0
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
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND u.Id = b.UserId
  AND p.Id = ph.PostId
  AND p.AnswerCount >= 0
  AND p.CommentCount >= 0
  AND b.Date <= CAST('2014-09-11 21:46:02' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 642
  AND u.DownVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
