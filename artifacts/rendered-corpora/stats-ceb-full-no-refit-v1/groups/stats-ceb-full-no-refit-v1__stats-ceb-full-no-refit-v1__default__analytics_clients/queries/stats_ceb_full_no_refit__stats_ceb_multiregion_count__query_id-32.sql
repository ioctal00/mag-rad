with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = v.UserId
  AND v.UserId = ph.UserId
  AND ph.UserId = c.UserId
  AND c.CreationDate >= CAST('2010-08-12 20:33:46' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-13 19:26:55' AS timestamp)
  AND ph.CreationDate >= CAST('2011-04-11 14:46:09' AS timestamp)
  AND ph.CreationDate <= CAST('2014-08-17 16:37:23' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-26 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND u.Views >= 0
  AND u.Views <= 783
  AND u.DownVotes >= 0
  AND u.DownVotes <= 1
  AND u.UpVotes <= 123
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = v.UserId
  AND v.UserId = ph.UserId
  AND ph.UserId = c.UserId
  AND c.CreationDate >= CAST('2010-08-12 20:33:46' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-13 19:26:55' AS timestamp)
  AND ph.CreationDate >= CAST('2011-04-11 14:46:09' AS timestamp)
  AND ph.CreationDate <= CAST('2014-08-17 16:37:23' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-26 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND u.Views >= 0
  AND u.Views <= 783
  AND u.DownVotes >= 0
  AND u.DownVotes <= 1
  AND u.UpVotes <= 123
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
