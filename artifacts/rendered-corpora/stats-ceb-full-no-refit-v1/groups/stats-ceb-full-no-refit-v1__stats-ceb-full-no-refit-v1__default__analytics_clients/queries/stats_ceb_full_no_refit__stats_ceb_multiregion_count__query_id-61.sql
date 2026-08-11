with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND p.Id = v.PostId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND c.CreationDate >= CAST('2010-08-06 12:21:39' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 20:55:34' AS timestamp)
  AND p.Score >= 0
  AND p.Score <= 13
  AND p.FavoriteCount >= 0
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-03-11 18:50:29' AS timestamp)
  AND v.VoteTypeId = 2
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
  AND u.Reputation >= 1
  AND u.CreationDate >= CAST('2011-02-17 03:42:02' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-01 10:54:39' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND p.Id = v.PostId
  AND u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND c.CreationDate >= CAST('2010-08-06 12:21:39' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-11 20:55:34' AS timestamp)
  AND p.Score >= 0
  AND p.Score <= 13
  AND p.FavoriteCount >= 0
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-03-11 18:50:29' AS timestamp)
  AND v.VoteTypeId = 2
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
  AND u.Reputation >= 1
  AND u.CreationDate >= CAST('2011-02-17 03:42:02' AS timestamp)
  AND u.CreationDate <= CAST('2014-09-01 10:54:39' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
