with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND p.Score <= 52
  AND p.AnswerCount >= 0
  AND v.CreationDate >= CAST('2010-07-20 00:00:00' AS timestamp)
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-10-05 05:52:35' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-08 15:55:02' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND p.Score <= 52
  AND p.AnswerCount >= 0
  AND v.CreationDate >= CAST('2010-07-20 00:00:00' AS timestamp)
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-10-05 05:52:35' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-08 15:55:02' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
