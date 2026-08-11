with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = b.UserId
  AND u.Id = ph.UserId
  AND u.Id = c.UserId
  AND c.CreationDate <= CAST('2014-08-28 00:18:24' AS timestamp)
  AND b.Date >= CAST('2010-09-15 02:50:48' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 1443
  AND u.DownVotes >= 0
  AND u.DownVotes <= 3
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postHistory AS ph,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = b.UserId
  AND u.Id = ph.UserId
  AND u.Id = c.UserId
  AND c.CreationDate <= CAST('2014-08-28 00:18:24' AS timestamp)
  AND b.Date >= CAST('2010-09-15 02:50:48' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 1443
  AND u.DownVotes >= 0
  AND u.DownVotes <= 3
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
