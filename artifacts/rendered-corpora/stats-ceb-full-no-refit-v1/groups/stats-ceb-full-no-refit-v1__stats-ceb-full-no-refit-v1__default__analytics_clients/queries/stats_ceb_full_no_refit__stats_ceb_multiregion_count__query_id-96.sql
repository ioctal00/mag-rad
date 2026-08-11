with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.posts AS p
WHERE ph.PostId = p.Id
  AND c.PostId = p.Id
  AND v.PostId = p.Id
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-08-26 06:55:11' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-05 06:39:25' AS timestamp)
  AND v.VoteTypeId = 2
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
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-08-26 06:55:11' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-05 06:39:25' AS timestamp)
  AND v.VoteTypeId = 2
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
