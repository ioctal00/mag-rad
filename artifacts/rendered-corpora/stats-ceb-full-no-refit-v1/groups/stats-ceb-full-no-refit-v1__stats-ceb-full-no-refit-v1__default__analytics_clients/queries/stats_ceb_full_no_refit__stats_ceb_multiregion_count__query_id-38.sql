with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = c.UserId
  AND u.Id = ph.UserId
  AND u.Id = b.UserId
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-09-05 16:04:35' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 04:35:36' AS timestamp)
  AND ph.PostHistoryTypeId = 1
  AND ph.CreationDate >= CAST('2010-07-26 20:01:58' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-13 17:29:23' AS timestamp)
  AND b.Date <= CAST('2014-09-04 08:54:56' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postHistory AS ph,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = c.UserId
  AND u.Id = ph.UserId
  AND u.Id = b.UserId
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-09-05 16:04:35' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 04:35:36' AS timestamp)
  AND ph.PostHistoryTypeId = 1
  AND ph.CreationDate >= CAST('2010-07-26 20:01:58' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-13 17:29:23' AS timestamp)
  AND b.Date <= CAST('2014-09-04 08:54:56' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
