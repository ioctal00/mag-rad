with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.posts AS p, stats_eu.postLinks AS pl, stats_eu.users AS u
WHERE p.Id = pl.PostId
  AND p.OwnerUserId = u.Id
  AND p.CommentCount <= 17
  AND u.CreationDate <= CAST('2014-09-12 07:12:16' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.posts AS p, stats_us.postLinks AS pl, stats_us.users AS u
WHERE p.Id = pl.PostId
  AND p.OwnerUserId = u.Id
  AND p.CommentCount <= 17
  AND u.CreationDate <= CAST('2014-09-12 07:12:16' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
