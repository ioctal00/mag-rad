with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE b.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND ph.PostHistoryTypeId = 5
  AND p.ViewCount >= 0
  AND p.ViewCount <= 2024
  AND u.Reputation >= 1
  AND u.Reputation <= 750
  AND b.Date >= CAST('2010-07-20 10:34:10' AS timestamp)
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
  AND ph.PostHistoryTypeId = 5
  AND p.ViewCount >= 0
  AND p.ViewCount <= 2024
  AND u.Reputation >= 1
  AND u.Reputation <= 750
  AND b.Date >= CAST('2010-07-20 10:34:10' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
