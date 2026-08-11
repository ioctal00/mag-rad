with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = c.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = ph.UserId
  AND u.Id = b.UserId
  AND c.CreationDate >= CAST('2010-07-31 05:18:59' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-12 07:59:13' AS timestamp)
  AND p.Score >= -2
  AND p.ViewCount >= 0
  AND p.ViewCount <= 18281
  AND ph.PostHistoryTypeId = 2
  AND b.Date >= CAST('2010-10-20 08:33:44' AS timestamp)
  AND u.Views >= 0
  AND u.Views <= 75
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postHistory AS ph,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = c.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = ph.UserId
  AND u.Id = b.UserId
  AND c.CreationDate >= CAST('2010-07-31 05:18:59' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-12 07:59:13' AS timestamp)
  AND p.Score >= -2
  AND p.ViewCount >= 0
  AND p.ViewCount <= 18281
  AND ph.PostHistoryTypeId = 2
  AND b.Date >= CAST('2010-10-20 08:33:44' AS timestamp)
  AND u.Views >= 0
  AND u.Views <= 75
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
