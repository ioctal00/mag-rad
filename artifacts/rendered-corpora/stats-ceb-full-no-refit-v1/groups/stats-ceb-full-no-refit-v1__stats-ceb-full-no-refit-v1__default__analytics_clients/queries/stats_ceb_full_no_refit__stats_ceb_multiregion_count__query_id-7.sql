with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.posts AS p, stats_eu.postLinks AS pl
WHERE c.UserId = p.OwnerUserId
  AND p.Id = pl.PostId
  AND p.CommentCount <= 18
  AND p.CreationDate >= CAST('2010-07-23 07:27:31' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-09 01:43:00' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.posts AS p, stats_us.postLinks AS pl
WHERE c.UserId = p.OwnerUserId
  AND p.Id = pl.PostId
  AND p.CommentCount <= 18
  AND p.CreationDate >= CAST('2010-07-23 07:27:31' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-09 01:43:00' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
