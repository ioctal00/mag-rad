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
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-20 06:26:28' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 18:45:09' AS timestamp)
  AND p.PostTypeId = 1
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 2
  AND ph.PostHistoryTypeId = 5
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-09-18 01:58:41' AS timestamp)
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
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-20 06:26:28' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 18:45:09' AS timestamp)
  AND p.PostTypeId = 1
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 2
  AND ph.PostHistoryTypeId = 5
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-09-18 01:58:41' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
