with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE p.Id = pl.RelatedPostId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND u.Id = ph.UserId
  AND u.Id = v.UserId
  AND p.CommentCount >= 0
  AND p.CommentCount <= 13
  AND ph.PostHistoryTypeId = 5
  AND ph.CreationDate <= CAST('2014-08-13 09:20:10' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-19 00:00:00' AS timestamp)
  AND b.Date <= CAST('2014-09-09 10:24:35' AS timestamp)
  AND u.Views >= 0
  AND u.DownVotes >= 0
  AND u.CreationDate >= CAST('2010-08-04 16:59:53' AS timestamp)
  AND u.CreationDate <= CAST('2014-07-22 15:15:22' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE p.Id = pl.RelatedPostId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND u.Id = ph.UserId
  AND u.Id = v.UserId
  AND p.CommentCount >= 0
  AND p.CommentCount <= 13
  AND ph.PostHistoryTypeId = 5
  AND ph.CreationDate <= CAST('2014-08-13 09:20:10' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-19 00:00:00' AS timestamp)
  AND b.Date <= CAST('2014-09-09 10:24:35' AS timestamp)
  AND u.Views >= 0
  AND u.DownVotes >= 0
  AND u.CreationDate >= CAST('2010-08-04 16:59:53' AS timestamp)
  AND u.CreationDate <= CAST('2014-07-22 15:15:22' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
