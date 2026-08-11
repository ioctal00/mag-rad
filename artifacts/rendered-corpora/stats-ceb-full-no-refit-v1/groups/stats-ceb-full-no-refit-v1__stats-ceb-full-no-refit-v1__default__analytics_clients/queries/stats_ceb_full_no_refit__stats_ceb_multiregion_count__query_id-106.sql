with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE v.UserId = u.Id
  AND c.UserId = u.Id
  AND ph.UserId = u.Id
  AND c.CreationDate <= CAST('2014-08-28 07:25:55' AS timestamp)
  AND ph.PostHistoryTypeId = 2
  AND u.Reputation >= 1
  AND u.Views >= 0
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 15
  AND u.CreationDate >= CAST('2010-09-03 11:45:16' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-18 17:19:53' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE v.UserId = u.Id
  AND c.UserId = u.Id
  AND ph.UserId = u.Id
  AND c.CreationDate <= CAST('2014-08-28 07:25:55' AS timestamp)
  AND ph.PostHistoryTypeId = 2
  AND u.Reputation >= 1
  AND u.Views >= 0
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 15
  AND u.CreationDate >= CAST('2010-09-03 11:45:16' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-18 17:19:53' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
