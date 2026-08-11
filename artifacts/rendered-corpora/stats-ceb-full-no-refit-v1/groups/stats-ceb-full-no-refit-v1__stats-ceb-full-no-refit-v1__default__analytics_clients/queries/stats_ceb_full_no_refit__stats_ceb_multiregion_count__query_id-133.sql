with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE ph.UserId = u.Id
  AND v.UserId = u.Id
  AND c.UserId = u.Id
  AND b.UserId = u.Id
  AND b.Date >= CAST('2010-09-26 12:17:14' AS timestamp)
  AND v.BountyAmount >= 0
  AND v.CreationDate >= CAST('2010-07-20 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
  AND u.DownVotes >= 0
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 31
  AND u.CreationDate <= CAST('2014-08-06 20:38:52' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postHistory AS ph,
  stats_us.badges AS b,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE ph.UserId = u.Id
  AND v.UserId = u.Id
  AND c.UserId = u.Id
  AND b.UserId = u.Id
  AND b.Date >= CAST('2010-09-26 12:17:14' AS timestamp)
  AND v.BountyAmount >= 0
  AND v.CreationDate >= CAST('2010-07-20 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
  AND u.DownVotes >= 0
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 31
  AND u.CreationDate <= CAST('2014-08-06 20:38:52' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
