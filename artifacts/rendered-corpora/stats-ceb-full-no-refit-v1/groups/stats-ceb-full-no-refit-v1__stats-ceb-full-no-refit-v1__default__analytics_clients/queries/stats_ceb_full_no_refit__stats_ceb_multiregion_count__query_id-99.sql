with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.Score = 0
  AND p.ViewCount >= 0
  AND u.Reputation <= 306
  AND u.UpVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.Score = 0
  AND p.ViewCount >= 0
  AND u.Reputation <= 306
  AND u.UpVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
