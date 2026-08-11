with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.posts AS p
WHERE pl.PostId = p.Id
  AND c.PostId = p.Id
  AND v.PostId = p.Id
  AND ph.PostId = p.Id
  AND c.Score = 0
  AND pl.CreationDate >= CAST('2011-11-21 22:39:41' AS timestamp)
  AND pl.CreationDate <= CAST('2014-09-01 16:29:56' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-22 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-14 00:00:00' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.posts AS p
WHERE pl.PostId = p.Id
  AND c.PostId = p.Id
  AND v.PostId = p.Id
  AND ph.PostId = p.Id
  AND c.Score = 0
  AND pl.CreationDate >= CAST('2011-11-21 22:39:41' AS timestamp)
  AND pl.CreationDate <= CAST('2014-09-01 16:29:56' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-22 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-14 00:00:00' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
