with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = ph.UserId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND c.CreationDate >= CAST('2010-08-19 09:33:49' AS timestamp)
  AND c.CreationDate <= CAST('2014-08-28 06:54:21' AS timestamp)
  AND p.PostTypeId = 1
  AND p.ViewCount >= 0
  AND p.ViewCount <= 25597
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
  AND p.FavoriteCount >= 0
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 123
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postHistory AS ph,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = ph.UserId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND u.Id = c.UserId
  AND c.CreationDate >= CAST('2010-08-19 09:33:49' AS timestamp)
  AND c.CreationDate <= CAST('2014-08-28 06:54:21' AS timestamp)
  AND p.PostTypeId = 1
  AND p.ViewCount >= 0
  AND p.ViewCount <= 25597
  AND p.CommentCount >= 0
  AND p.CommentCount <= 11
  AND p.FavoriteCount >= 0
  AND u.DownVotes <= 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 123
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
