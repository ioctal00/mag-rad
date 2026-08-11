with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.posts AS p
WHERE ph.PostId = p.Id
  AND c.PostId = p.Id
  AND v.PostId = p.Id
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.posts AS p
WHERE ph.PostId = p.Id
  AND c.PostId = p.Id
  AND v.PostId = p.Id
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
