with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.badges AS b
WHERE p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND b.UserId = c.UserId
  AND c.CreationDate >= CAST('2010-07-22 01:19:43' AS timestamp)
  AND p.Score >= -1
  AND p.ViewCount >= 0
  AND p.CommentCount <= 9
  AND ph.CreationDate >= CAST('2010-09-20 17:45:15' AS timestamp)
  AND ph.CreationDate <= CAST('2014-08-07 01:00:45' AS timestamp)
  AND v.VoteTypeId = 15
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.badges AS b
WHERE p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND b.UserId = c.UserId
  AND c.CreationDate >= CAST('2010-07-22 01:19:43' AS timestamp)
  AND p.Score >= -1
  AND p.ViewCount >= 0
  AND p.CommentCount <= 9
  AND ph.CreationDate >= CAST('2010-09-20 17:45:15' AS timestamp)
  AND ph.CreationDate <= CAST('2014-08-07 01:00:45' AS timestamp)
  AND v.VoteTypeId = 15
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
