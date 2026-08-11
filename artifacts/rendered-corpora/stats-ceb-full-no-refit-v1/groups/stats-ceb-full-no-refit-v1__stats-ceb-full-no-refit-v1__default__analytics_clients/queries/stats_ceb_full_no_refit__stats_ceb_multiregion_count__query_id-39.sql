with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = c.UserId
  AND u.Id = ph.UserId
  AND u.Id = b.UserId
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-20 10:52:57' AS timestamp)
  AND ph.PostHistoryTypeId = 5
  AND ph.CreationDate >= CAST('2011-01-31 15:35:37' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 356
  AND u.DownVotes <= 34
  AND u.CreationDate >= CAST('2010-07-19 21:29:29' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-20 14:31:46' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postHistory AS ph,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = c.UserId
  AND u.Id = ph.UserId
  AND u.Id = b.UserId
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-20 10:52:57' AS timestamp)
  AND ph.PostHistoryTypeId = 5
  AND ph.CreationDate >= CAST('2011-01-31 15:35:37' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 356
  AND u.DownVotes <= 34
  AND u.CreationDate >= CAST('2010-07-19 21:29:29' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-20 14:31:46' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
