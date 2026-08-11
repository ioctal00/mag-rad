with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE p.Id = pl.RelatedPostId
  AND b.UserId = u.Id
  AND c.UserId = u.Id
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND p.Id = ph.PostId
  AND p.Score <= 40
  AND p.CommentCount >= 0
  AND p.CreationDate >= CAST('2010-07-28 17:40:56' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-11 04:22:44' AS timestamp)
  AND pl.LinkTypeId = 1
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE p.Id = pl.RelatedPostId
  AND b.UserId = u.Id
  AND c.UserId = u.Id
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND p.Id = ph.PostId
  AND p.Score <= 40
  AND p.CommentCount >= 0
  AND p.CreationDate >= CAST('2010-07-28 17:40:56' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-11 04:22:44' AS timestamp)
  AND pl.LinkTypeId = 1
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
