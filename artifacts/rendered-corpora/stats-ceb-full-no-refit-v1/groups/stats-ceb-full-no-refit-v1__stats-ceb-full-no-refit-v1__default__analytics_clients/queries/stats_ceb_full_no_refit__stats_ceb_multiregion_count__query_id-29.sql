with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.votes AS v,
  stats_eu.posts AS p,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE p.Id = v.PostId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND p.PostTypeId = 1
  AND p.Score >= -1
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 20
  AND b.Date >= CAST('2010-07-20 19:02:22' AS timestamp)
  AND b.Date <= CAST('2014-09-03 23:36:09' AS timestamp)
  AND u.DownVotes <= 2
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-11-26 03:34:11' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.votes AS v,
  stats_us.posts AS p,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE p.Id = v.PostId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND p.PostTypeId = 1
  AND p.Score >= -1
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 20
  AND b.Date >= CAST('2010-07-20 19:02:22' AS timestamp)
  AND b.Date <= CAST('2014-09-03 23:36:09' AS timestamp)
  AND u.DownVotes <= 2
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-11-26 03:34:11' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
