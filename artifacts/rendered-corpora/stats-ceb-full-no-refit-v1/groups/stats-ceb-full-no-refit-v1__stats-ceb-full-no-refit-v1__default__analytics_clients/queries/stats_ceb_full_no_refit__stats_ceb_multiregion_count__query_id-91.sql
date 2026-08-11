with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph, stats_eu.posts AS p, stats_eu.users AS u
WHERE p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND ph.CreationDate >= CAST('2010-08-21 05:30:40' AS timestamp)
  AND p.Score >= 0
  AND u.Reputation >= 1
  AND u.UpVotes <= 198
  AND u.CreationDate >= CAST('2010-07-19 20:49:05' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph, stats_us.posts AS p, stats_us.users AS u
WHERE p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND ph.CreationDate >= CAST('2010-08-21 05:30:40' AS timestamp)
  AND p.Score >= 0
  AND u.Reputation >= 1
  AND u.UpVotes <= 198
  AND u.CreationDate >= CAST('2010-07-19 20:49:05' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
