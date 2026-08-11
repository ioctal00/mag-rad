with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.badges AS b, stats_eu.posts AS p
WHERE b.UserId = p.OwnerUserId
  AND b.Date <= CAST('2014-09-11 08:55:52' AS timestamp)
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 17
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.badges AS b, stats_us.posts AS p
WHERE b.UserId = p.OwnerUserId
  AND b.Date <= CAST('2014-09-11 08:55:52' AS timestamp)
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 17
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
