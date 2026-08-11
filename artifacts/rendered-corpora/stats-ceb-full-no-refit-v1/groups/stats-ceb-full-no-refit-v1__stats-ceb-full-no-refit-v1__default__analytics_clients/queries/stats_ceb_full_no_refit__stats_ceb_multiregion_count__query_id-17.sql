with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.posts AS p, stats_eu.tags AS t, stats_eu.votes AS v
WHERE p.Id = t.ExcerptPostId
  AND p.OwnerUserId = v.UserId
  AND p.CreationDate >= CAST('2010-07-20 02:01:05' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.posts AS p, stats_us.tags AS t, stats_us.votes AS v
WHERE p.Id = t.ExcerptPostId
  AND p.OwnerUserId = v.UserId
  AND p.CreationDate >= CAST('2010-07-20 02:01:05' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
