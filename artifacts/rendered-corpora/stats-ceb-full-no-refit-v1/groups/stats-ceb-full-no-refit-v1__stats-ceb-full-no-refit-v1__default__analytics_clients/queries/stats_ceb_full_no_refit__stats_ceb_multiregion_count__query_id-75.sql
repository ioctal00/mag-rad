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
  AND c.CreationDate <= CAST('2014-09-09 19:58:29' AS timestamp)
  AND p.Score >= -4
  AND p.ViewCount >= 0
  AND p.ViewCount <= 5977
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
  AND p.CreationDate >= CAST('2011-01-25 08:31:41' AS timestamp)
  AND u.Reputation <= 312
  AND u.DownVotes <= 0
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
  AND c.CreationDate <= CAST('2014-09-09 19:58:29' AS timestamp)
  AND p.Score >= -4
  AND p.ViewCount >= 0
  AND p.ViewCount <= 5977
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
  AND p.CreationDate >= CAST('2011-01-25 08:31:41' AS timestamp)
  AND u.Reputation <= 312
  AND u.DownVotes <= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
