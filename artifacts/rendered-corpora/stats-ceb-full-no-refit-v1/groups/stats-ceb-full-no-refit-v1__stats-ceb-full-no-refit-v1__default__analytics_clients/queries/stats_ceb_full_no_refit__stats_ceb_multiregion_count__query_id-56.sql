with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.tags AS t,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.votes AS v,
  stats_eu.badges AS b
WHERE p.Id = t.ExcerptPostId
  AND u.Id = v.UserId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.DownVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.tags AS t,
  stats_us.posts AS p,
  stats_us.users AS u,
  stats_us.votes AS v,
  stats_us.badges AS b
WHERE p.Id = t.ExcerptPostId
  AND u.Id = v.UserId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.DownVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
