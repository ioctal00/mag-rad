with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.posts AS p, stats_eu.postLinks AS pl, stats_eu.postHistory AS ph
WHERE p.Id = pl.PostId
  AND pl.PostId = ph.PostId
  AND p.CreationDate >= CAST('2010-07-19 20:08:37' AS timestamp)
  AND ph.CreationDate >= CAST('2010-07-20 00:30:00' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.posts AS p, stats_us.postLinks AS pl, stats_us.postHistory AS ph
WHERE p.Id = pl.PostId
  AND pl.PostId = ph.PostId
  AND p.CreationDate >= CAST('2010-07-19 20:08:37' AS timestamp)
  AND ph.CreationDate >= CAST('2010-07-20 00:30:00' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
