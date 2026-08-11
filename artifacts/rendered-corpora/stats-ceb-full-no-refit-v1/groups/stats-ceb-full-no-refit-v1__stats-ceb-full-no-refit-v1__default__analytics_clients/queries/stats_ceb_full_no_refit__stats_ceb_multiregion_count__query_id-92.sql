with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph, stats_eu.posts AS p, stats_eu.users AS u
WHERE ph.PostId = p.Id
  AND p.OwnerUserId = u.Id
  AND p.CreationDate >= CAST('2010-08-17 19:08:05' AS timestamp)
  AND p.CreationDate <= CAST('2014-08-31 06:58:12' AS timestamp)
  AND u.UpVotes >= 0
  AND u.UpVotes <= 9
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph, stats_us.posts AS p, stats_us.users AS u
WHERE ph.PostId = p.Id
  AND p.OwnerUserId = u.Id
  AND p.CreationDate >= CAST('2010-08-17 19:08:05' AS timestamp)
  AND p.CreationDate <= CAST('2014-08-31 06:58:12' AS timestamp)
  AND u.UpVotes >= 0
  AND u.UpVotes <= 9
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
