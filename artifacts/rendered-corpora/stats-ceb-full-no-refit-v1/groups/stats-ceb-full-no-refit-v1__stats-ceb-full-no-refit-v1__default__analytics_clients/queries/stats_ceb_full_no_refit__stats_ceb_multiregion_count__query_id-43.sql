with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE u.Id = p.OwnerUserId
  AND p.OwnerUserId = ph.UserId
  AND ph.UserId = b.UserId
  AND ph.PostHistoryTypeId = 3
  AND p.Score >= -7
  AND u.Reputation >= 1
  AND u.UpVotes >= 0
  AND u.UpVotes <= 117
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph,
  stats_us.posts AS p,
  stats_us.users AS u,
  stats_us.badges AS b
WHERE u.Id = p.OwnerUserId
  AND p.OwnerUserId = ph.UserId
  AND ph.UserId = b.UserId
  AND ph.PostHistoryTypeId = 3
  AND p.Score >= -7
  AND u.Reputation >= 1
  AND u.UpVotes >= 0
  AND u.UpVotes <= 117
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
