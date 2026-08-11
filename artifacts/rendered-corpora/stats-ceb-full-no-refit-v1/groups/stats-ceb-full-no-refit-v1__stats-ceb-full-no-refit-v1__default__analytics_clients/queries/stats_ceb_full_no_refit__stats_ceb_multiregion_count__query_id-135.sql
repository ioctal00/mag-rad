with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = ph.UserId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND c.Score = 0
  AND p.PostTypeId = 1
  AND p.ViewCount >= 0
  AND p.ViewCount <= 4157
  AND p.FavoriteCount = 0
  AND p.CreationDate <= CAST('2014-09-08 09:58:16' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postHistory AS ph,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = ph.UserId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND c.Score = 0
  AND p.PostTypeId = 1
  AND p.ViewCount >= 0
  AND p.ViewCount <= 4157
  AND p.FavoriteCount = 0
  AND p.CreationDate <= CAST('2014-09-08 09:58:16' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
