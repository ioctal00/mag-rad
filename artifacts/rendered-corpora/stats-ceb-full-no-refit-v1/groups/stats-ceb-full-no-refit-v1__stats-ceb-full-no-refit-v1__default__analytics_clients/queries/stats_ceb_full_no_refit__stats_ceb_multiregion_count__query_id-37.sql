with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v
WHERE pl.PostId = c.PostId
  AND c.PostId = ph.PostId
  AND ph.PostId = v.PostId
  AND ph.CreationDate >= CAST('2011-05-07 21:47:19' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-10 13:19:54' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v
WHERE pl.PostId = c.PostId
  AND c.PostId = ph.PostId
  AND ph.PostId = v.PostId
  AND ph.CreationDate >= CAST('2011-05-07 21:47:19' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-10 13:19:54' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
