with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.postHistory AS ph, stats_eu.users AS u
WHERE c.UserId = u.Id
  AND ph.UserId = u.Id
  AND c.CreationDate >= CAST('2010-08-09 07:24:50' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-10 03:46:02' AS timestamp)
  AND u.Reputation >= 1
  AND u.Views <= 80
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-08-02 20:31:12' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.postHistory AS ph, stats_us.users AS u
WHERE c.UserId = u.Id
  AND ph.UserId = u.Id
  AND c.CreationDate >= CAST('2010-08-09 07:24:50' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-10 03:46:02' AS timestamp)
  AND u.Reputation >= 1
  AND u.Views <= 80
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-08-02 20:31:12' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
