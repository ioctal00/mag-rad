with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE u.Id = ph.UserId
  AND u.Id = v.UserId
  AND u.Id = b.UserId
  AND ph.PostHistoryTypeId = 2
  AND u.Views = 5
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 224
  AND u.CreationDate <= CAST('2014-09-04 04:41:22' AS timestamp)
  AND b.Date >= CAST('2010-07-19 19:39:10' AS timestamp)
  AND b.Date <= CAST('2014-09-05 18:37:48' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u,
  stats_us.badges AS b
WHERE u.Id = ph.UserId
  AND u.Id = v.UserId
  AND u.Id = b.UserId
  AND ph.PostHistoryTypeId = 2
  AND u.Views = 5
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 224
  AND u.CreationDate <= CAST('2014-09-04 04:41:22' AS timestamp)
  AND b.Date >= CAST('2010-07-19 19:39:10' AS timestamp)
  AND b.Date <= CAST('2014-09-05 18:37:48' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
