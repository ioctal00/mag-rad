with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE b.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND p.AnswerCount >= 0
  AND p.FavoriteCount >= 0
  AND p.CreationDate <= CAST('2014-09-03 03:32:35' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-12 22:21:49' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph,
  stats_us.posts AS p,
  stats_us.users AS u,
  stats_us.badges AS b
WHERE b.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND p.AnswerCount >= 0
  AND p.FavoriteCount >= 0
  AND p.CreationDate <= CAST('2014-09-03 03:32:35' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-12 22:21:49' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
