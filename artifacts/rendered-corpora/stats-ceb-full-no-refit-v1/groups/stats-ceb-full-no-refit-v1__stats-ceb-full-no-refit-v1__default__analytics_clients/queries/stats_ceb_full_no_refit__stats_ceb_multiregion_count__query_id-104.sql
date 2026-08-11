with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE v.UserId = u.Id
  AND c.UserId = u.Id
  AND ph.UserId = u.Id
  AND ph.CreationDate >= CAST('2010-07-28 09:11:34' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-06 06:51:53' AS timestamp)
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 72
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
  AND ph.CreationDate >= CAST('2010-07-28 09:11:34' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-06 06:51:53' AS timestamp)
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 72
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
