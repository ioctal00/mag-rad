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
  AND c.CreationDate >= CAST('2010-08-01 12:12:41' AS timestamp)
  AND p.Score <= 44
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 3
  AND p.CreationDate >= CAST('2010-08-11 13:53:56' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-03 11:52:36' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate <= CAST('2014-08-11 17:26:31' AS timestamp)
  AND ph.CreationDate >= CAST('2010-09-20 19:11:45' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
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
  AND c.CreationDate >= CAST('2010-08-01 12:12:41' AS timestamp)
  AND p.Score <= 44
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 3
  AND p.CreationDate >= CAST('2010-08-11 13:53:56' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-03 11:52:36' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate <= CAST('2014-08-11 17:26:31' AS timestamp)
  AND ph.CreationDate >= CAST('2010-09-20 19:11:45' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
