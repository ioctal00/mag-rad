with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.votes AS v
WHERE p.Id = c.PostId
  AND c.PostId = pl.PostId
  AND pl.PostId = v.PostId
  AND c.CreationDate >= CAST('2010-08-02 23:52:10' AS timestamp)
  AND p.Score >= -3
  AND v.VoteTypeId = 2
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.votes AS v
WHERE p.Id = c.PostId
  AND c.PostId = pl.PostId
  AND pl.PostId = v.PostId
  AND c.CreationDate >= CAST('2010-08-02 23:52:10' AS timestamp)
  AND p.Score >= -3
  AND v.VoteTypeId = 2
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
