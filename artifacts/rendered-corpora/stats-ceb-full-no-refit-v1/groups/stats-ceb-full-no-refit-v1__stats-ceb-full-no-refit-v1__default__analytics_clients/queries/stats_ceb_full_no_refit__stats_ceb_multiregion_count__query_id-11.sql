with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.posts AS p, stats_eu.users AS u
WHERE c.UserId = u.Id
  AND u.Id = p.OwnerUserId
  AND c.Score = 0
  AND p.Score >= 0
  AND p.Score <= 15
  AND p.ViewCount >= 0
  AND p.ViewCount <= 3002
  AND p.AnswerCount <= 3
  AND p.CommentCount <= 10
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-08-23 16:21:10' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-02 09:50:06' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.posts AS p, stats_us.users AS u
WHERE c.UserId = u.Id
  AND u.Id = p.OwnerUserId
  AND c.Score = 0
  AND p.Score >= 0
  AND p.Score <= 15
  AND p.ViewCount >= 0
  AND p.ViewCount <= 3002
  AND p.AnswerCount <= 3
  AND p.CommentCount <= 10
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-08-23 16:21:10' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-02 09:50:06' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
