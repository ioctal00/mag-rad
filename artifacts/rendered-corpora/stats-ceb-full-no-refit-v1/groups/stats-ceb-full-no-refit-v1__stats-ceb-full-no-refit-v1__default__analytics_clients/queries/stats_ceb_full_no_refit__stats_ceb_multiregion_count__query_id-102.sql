with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.votes AS v,
  stats_eu.posts AS p,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 7
  AND p.CreationDate <= CAST('2014-09-12 00:03:32' AS timestamp)
  AND b.Date <= CAST('2014-09-11 07:27:36' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.votes AS v,
  stats_us.posts AS p,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 7
  AND p.CreationDate <= CAST('2014-09-12 00:03:32' AS timestamp)
  AND b.Date <= CAST('2014-09-11 07:27:36' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
