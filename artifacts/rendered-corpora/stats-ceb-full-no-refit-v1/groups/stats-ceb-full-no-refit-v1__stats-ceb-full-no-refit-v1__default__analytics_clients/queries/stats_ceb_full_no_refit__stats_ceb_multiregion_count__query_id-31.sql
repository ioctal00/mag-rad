with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.votes AS v,
  stats_eu.posts AS p,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = v.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND v.CreationDate <= CAST('2014-09-06 00:00:00' AS timestamp)
  AND p.Score <= 48
  AND p.AnswerCount <= 8
  AND b.Date >= CAST('2011-01-03 20:50:19' AS timestamp)
  AND b.Date <= CAST('2014-09-02 15:35:07' AS timestamp)
  AND u.CreationDate >= CAST('2010-11-16 06:03:04' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.votes AS v,
  stats_us.posts AS p,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = v.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND v.CreationDate <= CAST('2014-09-06 00:00:00' AS timestamp)
  AND p.Score <= 48
  AND p.AnswerCount <= 8
  AND b.Date >= CAST('2011-01-03 20:50:19' AS timestamp)
  AND b.Date <= CAST('2014-09-02 15:35:07' AS timestamp)
  AND u.CreationDate >= CAST('2010-11-16 06:03:04' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
