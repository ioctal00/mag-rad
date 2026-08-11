with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.postHistory AS ph, stats_eu.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = ph.UserId
  AND u.Reputation >= 1
  AND u.Reputation <= 487
  AND u.UpVotes <= 27
  AND u.CreationDate >= CAST('2010-10-22 22:40:35' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-10 17:01:31' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.postHistory AS ph, stats_us.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = ph.UserId
  AND u.Reputation >= 1
  AND u.Reputation <= 487
  AND u.UpVotes <= 27
  AND u.CreationDate >= CAST('2010-10-22 22:40:35' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-10 17:01:31' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
