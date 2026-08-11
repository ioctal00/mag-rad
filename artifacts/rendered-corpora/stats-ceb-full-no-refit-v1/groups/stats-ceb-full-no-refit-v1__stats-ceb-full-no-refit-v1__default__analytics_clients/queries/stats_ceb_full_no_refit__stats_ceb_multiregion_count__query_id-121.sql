with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.badges AS b
WHERE b.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND ph.PostHistoryTypeId = 2
  AND ph.CreationDate >= CAST('2011-01-08 03:03:48' AS timestamp)
  AND ph.CreationDate <= CAST('2014-08-25 14:04:43' AS timestamp)
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 12
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 89
  AND p.CreationDate <= CAST('2014-09-02 10:21:04' AS timestamp)
  AND u.Reputation <= 705
  AND u.CreationDate >= CAST('2010-07-28 23:56:00' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-02 10:04:41' AS timestamp)
  AND b.Date >= CAST('2010-07-20 20:47:27' AS timestamp)
  AND b.Date <= CAST('2014-09-09 13:24:28' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph,
  stats_us.posts AS p,
  stats_us.users AS u,
  stats_us.badges AS b
WHERE b.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND ph.PostHistoryTypeId = 2
  AND ph.CreationDate >= CAST('2011-01-08 03:03:48' AS timestamp)
  AND ph.CreationDate <= CAST('2014-08-25 14:04:43' AS timestamp)
  AND p.AnswerCount <= 4
  AND p.CommentCount >= 0
  AND p.CommentCount <= 12
  AND p.FavoriteCount >= 0
  AND p.FavoriteCount <= 89
  AND p.CreationDate <= CAST('2014-09-02 10:21:04' AS timestamp)
  AND u.Reputation <= 705
  AND u.CreationDate >= CAST('2010-07-28 23:56:00' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-02 10:04:41' AS timestamp)
  AND b.Date >= CAST('2010-07-20 20:47:27' AS timestamp)
  AND b.Date <= CAST('2014-09-09 13:24:28' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
