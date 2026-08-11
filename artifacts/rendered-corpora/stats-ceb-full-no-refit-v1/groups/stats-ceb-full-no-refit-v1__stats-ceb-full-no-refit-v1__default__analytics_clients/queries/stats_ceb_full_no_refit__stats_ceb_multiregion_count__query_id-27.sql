with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = c.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = v.UserId
  AND c.Score = 0
  AND c.CreationDate <= CAST('2014-09-13 20:12:15' AS timestamp)
  AND p.CreationDate >= CAST('2010-07-27 01:51:15' AS timestamp)
  AND v.BountyAmount <= 50
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND u.UpVotes >= 0
  AND u.UpVotes <= 12
  AND u.CreationDate >= CAST('2010-07-19 19:09:39' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = c.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = v.UserId
  AND c.Score = 0
  AND c.CreationDate <= CAST('2014-09-13 20:12:15' AS timestamp)
  AND p.CreationDate >= CAST('2010-07-27 01:51:15' AS timestamp)
  AND v.BountyAmount <= 50
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND u.UpVotes >= 0
  AND u.UpVotes <= 12
  AND u.CreationDate >= CAST('2010-07-19 19:09:39' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
