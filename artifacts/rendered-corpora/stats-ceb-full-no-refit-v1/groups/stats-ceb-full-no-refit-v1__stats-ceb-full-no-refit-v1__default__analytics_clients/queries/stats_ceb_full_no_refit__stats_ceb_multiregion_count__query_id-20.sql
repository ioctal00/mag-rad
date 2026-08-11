with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph, stats_eu.posts AS p, stats_eu.users AS u
WHERE ph.PostId = p.Id
  AND p.OwnerUserId = u.Id
  AND ph.CreationDate <= CAST('2014-08-17 21:24:11' AS timestamp)
  AND p.CreationDate >= CAST('2010-07-26 19:26:37' AS timestamp)
  AND p.CreationDate <= CAST('2014-08-22 14:43:39' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 6524
  AND u.Views >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph, stats_us.posts AS p, stats_us.users AS u
WHERE ph.PostId = p.Id
  AND p.OwnerUserId = u.Id
  AND ph.CreationDate <= CAST('2014-08-17 21:24:11' AS timestamp)
  AND p.CreationDate >= CAST('2010-07-26 19:26:37' AS timestamp)
  AND p.CreationDate <= CAST('2014-08-22 14:43:39' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 6524
  AND u.Views >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
