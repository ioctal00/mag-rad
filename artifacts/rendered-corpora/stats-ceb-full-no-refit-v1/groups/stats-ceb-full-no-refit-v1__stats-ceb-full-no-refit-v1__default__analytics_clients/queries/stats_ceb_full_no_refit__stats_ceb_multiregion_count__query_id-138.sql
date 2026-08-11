with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.tags AS t,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.votes AS v,
  stats_eu.badges AS b
WHERE u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = v.UserId
  AND p.Id = t.ExcerptPostId
  AND p.CommentCount >= 0
  AND p.CommentCount <= 13
  AND u.Reputation >= 1
  AND b.Date <= CAST('2014-09-06 17:33:22' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.tags AS t,
  stats_us.posts AS p,
  stats_us.users AS u,
  stats_us.votes AS v,
  stats_us.badges AS b
WHERE u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = v.UserId
  AND p.Id = t.ExcerptPostId
  AND p.CommentCount >= 0
  AND p.CommentCount <= 13
  AND u.Reputation >= 1
  AND b.Date <= CAST('2014-09-06 17:33:22' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
