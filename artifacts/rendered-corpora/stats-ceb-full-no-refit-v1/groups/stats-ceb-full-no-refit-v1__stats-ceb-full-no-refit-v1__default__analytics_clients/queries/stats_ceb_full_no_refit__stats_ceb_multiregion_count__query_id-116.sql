with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = b.UserId
  AND u.Id = ph.UserId
  AND u.Id = c.UserId
  AND c.Score = 2
  AND ph.CreationDate >= CAST('2010-08-19 12:45:55' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-03 21:46:37' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 1183
  AND u.Views >= 0
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
  AND c.Score = 2
  AND ph.CreationDate >= CAST('2010-08-19 12:45:55' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-03 21:46:37' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 1183
  AND u.Views >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
