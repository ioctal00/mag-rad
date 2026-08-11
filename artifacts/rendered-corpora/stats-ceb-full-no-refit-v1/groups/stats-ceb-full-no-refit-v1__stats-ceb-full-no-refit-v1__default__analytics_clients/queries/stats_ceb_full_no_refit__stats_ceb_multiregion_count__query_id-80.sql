with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.posts AS p, stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND c.UserId = u.Id
  AND c.CreationDate >= CAST('2010-07-27 17:46:38' AS timestamp)
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
  AND p.CreationDate >= CAST('2010-07-26 09:46:48' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-13 10:09:50' AS timestamp)
  AND u.Reputation >= 1
  AND u.CreationDate >= CAST('2010-08-03 19:42:40' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-12 02:20:03' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.posts AS p, stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND c.UserId = u.Id
  AND c.CreationDate >= CAST('2010-07-27 17:46:38' AS timestamp)
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
  AND p.CreationDate >= CAST('2010-07-26 09:46:48' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-13 10:09:50' AS timestamp)
  AND u.Reputation >= 1
  AND u.CreationDate >= CAST('2010-08-03 19:42:40' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-12 02:20:03' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
