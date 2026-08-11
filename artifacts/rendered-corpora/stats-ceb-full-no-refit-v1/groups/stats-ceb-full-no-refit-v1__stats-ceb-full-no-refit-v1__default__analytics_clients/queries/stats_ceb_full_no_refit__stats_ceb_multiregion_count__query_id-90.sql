with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph, stats_eu.posts AS p, stats_eu.users AS u
WHERE p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND ph.CreationDate >= CAST('2011-05-20 18:43:03' AS timestamp)
  AND p.FavoriteCount <= 5
  AND u.Views >= 0
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-11-27 21:46:49' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-18 13:00:22' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph, stats_us.posts AS p, stats_us.users AS u
WHERE p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND ph.CreationDate >= CAST('2011-05-20 18:43:03' AS timestamp)
  AND p.FavoriteCount <= 5
  AND u.Views >= 0
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-11-27 21:46:49' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-18 13:00:22' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
