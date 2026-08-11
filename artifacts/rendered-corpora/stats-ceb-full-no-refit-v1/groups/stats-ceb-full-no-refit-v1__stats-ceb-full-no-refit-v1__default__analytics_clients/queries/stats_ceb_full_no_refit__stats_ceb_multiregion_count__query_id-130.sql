with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.users AS u
WHERE pl.RelatedPostId = p.Id
  AND u.Id = c.UserId
  AND c.PostId = p.Id
  AND ph.PostId = p.Id
  AND c.CreationDate >= CAST('2010-07-11 12:25:05' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 13:43:09' AS timestamp)
  AND p.CommentCount >= 0
  AND p.CommentCount <= 14
  AND pl.LinkTypeId = 1
  AND ph.CreationDate >= CAST('2010-08-06 03:14:53' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 491
  AND u.DownVotes >= 0
  AND u.DownVotes <= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.users AS u
WHERE pl.RelatedPostId = p.Id
  AND u.Id = c.UserId
  AND c.PostId = p.Id
  AND ph.PostId = p.Id
  AND c.CreationDate >= CAST('2010-07-11 12:25:05' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 13:43:09' AS timestamp)
  AND p.CommentCount >= 0
  AND p.CommentCount <= 14
  AND pl.LinkTypeId = 1
  AND ph.CreationDate >= CAST('2010-08-06 03:14:53' AS timestamp)
  AND u.Reputation >= 1
  AND u.Reputation <= 491
  AND u.DownVotes >= 0
  AND u.DownVotes <= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
