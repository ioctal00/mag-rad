with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.posts AS p, stats_eu.postHistory AS ph
WHERE p.Id = c.PostId
  AND p.Id = ph.PostId
  AND p.CommentCount >= 0
  AND p.CommentCount <= 25
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.posts AS p, stats_us.postHistory AS ph
WHERE p.Id = c.PostId
  AND p.Id = ph.PostId
  AND p.CommentCount >= 0
  AND p.CommentCount <= 25
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
