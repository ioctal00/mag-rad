with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = c.UserId
  AND u.Id = v.UserId
  AND u.Id = b.UserId
  AND c.Score = 0
  AND v.BountyAmount >= 0
  AND v.BountyAmount <= 300
  AND v.CreationDate >= CAST('2010-07-29 00:00:00' AS timestamp)
  AND u.UpVotes >= 0
  AND u.UpVotes <= 18
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = c.UserId
  AND u.Id = v.UserId
  AND u.Id = b.UserId
  AND c.Score = 0
  AND v.BountyAmount >= 0
  AND v.BountyAmount <= 300
  AND v.CreationDate >= CAST('2010-07-29 00:00:00' AS timestamp)
  AND u.UpVotes >= 0
  AND u.UpVotes <= 18
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
