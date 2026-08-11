with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v
WHERE p.Id = pl.PostId
  AND p.Id = v.PostId
  AND p.Id = ph.PostId
  AND p.Id = c.PostId
  AND c.Score = 0
  AND p.FavoriteCount >= 0
  AND p.CreationDate >= CAST('2010-07-23 02:00:12' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-08 13:52:41' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-10-06 21:41:26' AS timestamp)
  AND v.VoteTypeId = 2
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v
WHERE p.Id = pl.PostId
  AND p.Id = v.PostId
  AND p.Id = ph.PostId
  AND p.Id = c.PostId
  AND c.Score = 0
  AND p.FavoriteCount >= 0
  AND p.CreationDate >= CAST('2010-07-23 02:00:12' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-08 13:52:41' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-10-06 21:41:26' AS timestamp)
  AND v.VoteTypeId = 2
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
