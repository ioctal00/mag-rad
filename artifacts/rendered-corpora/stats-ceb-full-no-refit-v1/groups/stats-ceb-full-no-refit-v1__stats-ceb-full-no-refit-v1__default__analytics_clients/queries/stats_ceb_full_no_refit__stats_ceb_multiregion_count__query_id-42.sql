with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE p.Id = ph.PostId
  AND u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.PostTypeId = 1
  AND p.Score >= -1
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE p.Id = ph.PostId
  AND u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.PostTypeId = 1
  AND p.Score >= -1
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
