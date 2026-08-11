with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE u.Id = b.UserId
  AND u.Id = ph.UserId
  AND u.Id = v.UserId
  AND ph.PostHistoryTypeId = 1
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND u.Reputation <= 126
  AND u.Views <= 11
  AND u.CreationDate >= CAST('2010-08-02 16:17:58' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-12 00:16:30' AS timestamp)
  AND b.Date <= CAST('2014-09-03 16:13:12' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u,
  stats_us.badges AS b
WHERE u.Id = b.UserId
  AND u.Id = ph.UserId
  AND u.Id = v.UserId
  AND ph.PostHistoryTypeId = 1
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND u.Reputation <= 126
  AND u.Views <= 11
  AND u.CreationDate >= CAST('2010-08-02 16:17:58' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-12 00:16:30' AS timestamp)
  AND b.Date <= CAST('2014-09-03 16:13:12' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
