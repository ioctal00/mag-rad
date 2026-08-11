with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.votes AS v, stats_eu.badges AS b, stats_eu.users AS u
WHERE u.Id = v.UserId
  AND v.UserId = b.UserId
  AND v.BountyAmount >= 0
  AND v.BountyAmount <= 50
  AND u.DownVotes = 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.votes AS v, stats_us.badges AS b, stats_us.users AS u
WHERE u.Id = v.UserId
  AND v.UserId = b.UserId
  AND v.BountyAmount >= 0
  AND v.BountyAmount <= 50
  AND u.DownVotes = 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
