with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.posts AS p, stats_eu.postLinks AS pl
WHERE c.UserId = p.OwnerUserId
  AND p.Id = pl.PostId
  AND c.Score = 0
  AND p.CreationDate >= CAST('2010-09-06 00:58:21' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-12 10:02:21' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-07-09 22:35:44' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.posts AS p, stats_us.postLinks AS pl
WHERE c.UserId = p.OwnerUserId
  AND p.Id = pl.PostId
  AND c.Score = 0
  AND p.CreationDate >= CAST('2010-09-06 00:58:21' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-12 10:02:21' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-07-09 22:35:44' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
