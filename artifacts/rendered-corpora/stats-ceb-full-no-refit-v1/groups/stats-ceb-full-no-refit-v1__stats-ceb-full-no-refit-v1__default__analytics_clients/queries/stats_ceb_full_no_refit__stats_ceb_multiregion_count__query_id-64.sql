with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE p.Id = pl.PostId
  AND p.Id = ph.PostId
  AND p.Id = c.PostId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.CreationDate <= CAST('2014-09-11 13:24:22' AS timestamp)
  AND p.PostTypeId = 1
  AND p.Score = 2
  AND p.FavoriteCount <= 12
  AND pl.CreationDate >= CAST('2010-08-13 11:42:08' AS timestamp)
  AND pl.CreationDate <= CAST('2014-08-29 00:27:05' AS timestamp)
  AND ph.CreationDate >= CAST('2011-01-03 23:47:35' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-08 12:48:36' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-27 00:00:00' AS timestamp)
  AND u.Reputation >= 1
  AND u.DownVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE p.Id = pl.PostId
  AND p.Id = ph.PostId
  AND p.Id = c.PostId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.CreationDate <= CAST('2014-09-11 13:24:22' AS timestamp)
  AND p.PostTypeId = 1
  AND p.Score = 2
  AND p.FavoriteCount <= 12
  AND pl.CreationDate >= CAST('2010-08-13 11:42:08' AS timestamp)
  AND pl.CreationDate <= CAST('2014-08-29 00:27:05' AS timestamp)
  AND ph.CreationDate >= CAST('2011-01-03 23:47:35' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-08 12:48:36' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-27 00:00:00' AS timestamp)
  AND u.Reputation >= 1
  AND u.DownVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
