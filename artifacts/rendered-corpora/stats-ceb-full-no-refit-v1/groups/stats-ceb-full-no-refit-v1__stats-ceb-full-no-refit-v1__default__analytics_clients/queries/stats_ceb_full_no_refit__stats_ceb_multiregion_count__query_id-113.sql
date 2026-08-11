with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = b.UserId
  AND u.Id = ph.UserId
  AND u.Id = c.UserId
  AND c.CreationDate <= CAST('2014-09-10 00:33:30' AS timestamp)
  AND u.DownVotes <= 0
  AND u.UpVotes <= 47
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
  AND c.CreationDate <= CAST('2014-09-10 00:33:30' AS timestamp)
  AND u.DownVotes <= 0
  AND u.UpVotes <= 47
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
