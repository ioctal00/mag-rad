with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.votes AS v,
  stats_eu.users AS u,
  stats_eu.posts AS p
WHERE c.PostId = p.Id
  AND u.Id = c.UserId
  AND v.PostId = p.Id
  AND c.Score = 0
  AND u.Views >= 0
  AND u.Views <= 74
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.votes AS v,
  stats_us.users AS u,
  stats_us.posts AS p
WHERE c.PostId = p.Id
  AND u.Id = c.UserId
  AND v.PostId = p.Id
  AND c.Score = 0
  AND u.Views >= 0
  AND u.Views <= 74
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
