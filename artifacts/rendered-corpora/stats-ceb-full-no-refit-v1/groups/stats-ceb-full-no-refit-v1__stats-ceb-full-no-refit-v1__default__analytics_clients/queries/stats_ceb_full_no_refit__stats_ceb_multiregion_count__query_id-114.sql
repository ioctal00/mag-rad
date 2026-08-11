with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = b.UserId
  AND u.Id = ph.UserId
  AND u.Id = c.UserId
  AND ph.PostHistoryTypeId = 2
  AND ph.CreationDate <= CAST('2014-08-01 13:56:22' AS timestamp)
  AND b.Date <= CAST('2014-09-02 23:33:16' AS timestamp)
  AND u.Views >= 0
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 62
  AND u.CreationDate >= CAST('2010-07-27 17:10:30' AS timestamp)
  AND u.CreationDate <= CAST('2014-07-31 18:48:36' AS timestamp)
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
  AND ph.PostHistoryTypeId = 2
  AND ph.CreationDate <= CAST('2014-08-01 13:56:22' AS timestamp)
  AND b.Date <= CAST('2014-09-02 23:33:16' AS timestamp)
  AND u.Views >= 0
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 62
  AND u.CreationDate >= CAST('2010-07-27 17:10:30' AS timestamp)
  AND u.CreationDate <= CAST('2014-07-31 18:48:36' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
