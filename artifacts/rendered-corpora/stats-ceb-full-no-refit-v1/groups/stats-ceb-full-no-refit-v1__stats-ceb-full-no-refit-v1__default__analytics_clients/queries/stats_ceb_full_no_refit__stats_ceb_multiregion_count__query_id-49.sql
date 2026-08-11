with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = p.OwnerUserId
  AND p.OwnerUserId = v.UserId
  AND v.UserId = b.UserId
  AND c.Score = 1
  AND p.Score >= -1
  AND p.Score <= 29
  AND p.CreationDate >= CAST('2010-07-19 20:40:36' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-10 20:52:30' AS timestamp)
  AND v.BountyAmount <= 50
  AND b.Date <= CAST('2014-08-25 19:05:46' AS timestamp)
  AND u.DownVotes <= 11
  AND u.CreationDate >= CAST('2010-07-31 17:32:56' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-07 16:06:26' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = c.UserId
  AND c.UserId = p.OwnerUserId
  AND p.OwnerUserId = v.UserId
  AND v.UserId = b.UserId
  AND c.Score = 1
  AND p.Score >= -1
  AND p.Score <= 29
  AND p.CreationDate >= CAST('2010-07-19 20:40:36' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-10 20:52:30' AS timestamp)
  AND v.BountyAmount <= 50
  AND b.Date <= CAST('2014-08-25 19:05:46' AS timestamp)
  AND u.DownVotes <= 11
  AND u.CreationDate >= CAST('2010-07-31 17:32:56' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-07 16:06:26' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
