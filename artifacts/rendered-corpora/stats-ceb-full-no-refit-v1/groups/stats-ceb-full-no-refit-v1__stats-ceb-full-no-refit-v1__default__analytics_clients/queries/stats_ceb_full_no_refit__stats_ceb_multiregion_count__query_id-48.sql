with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = b.UserId
  AND b.UserId = ph.UserId
  AND ph.UserId = v.UserId
  AND v.UserId = c.UserId
  AND c.CreationDate >= CAST('2010-07-20 21:37:31' AS timestamp)
  AND ph.PostHistoryTypeId = 12
  AND u.UpVotes = 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postHistory AS ph,
  stats_us.badges AS b,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = b.UserId
  AND b.UserId = ph.UserId
  AND ph.UserId = v.UserId
  AND v.UserId = c.UserId
  AND c.CreationDate >= CAST('2010-07-20 21:37:31' AS timestamp)
  AND ph.PostHistoryTypeId = 12
  AND u.UpVotes = 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
