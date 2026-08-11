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
  AND c.Score = 0
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CreationDate <= CAST('2014-09-12 15:56:19' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-03-07 16:05:24' AS timestamp)
  AND v.BountyAmount <= 100
  AND v.CreationDate >= CAST('2009-02-03 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
  AND u.Views <= 160
  AND u.CreationDate >= CAST('2010-07-27 12:58:30' AS timestamp)
  AND u.CreationDate <= CAST('2014-07-12 20:08:07' AS timestamp)
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
  AND c.Score = 0
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND p.CreationDate <= CAST('2014-09-12 15:56:19' AS timestamp)
  AND pl.LinkTypeId = 1
  AND pl.CreationDate >= CAST('2011-03-07 16:05:24' AS timestamp)
  AND v.BountyAmount <= 100
  AND v.CreationDate >= CAST('2009-02-03 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-11 00:00:00' AS timestamp)
  AND u.Views <= 160
  AND u.CreationDate >= CAST('2010-07-27 12:58:30' AS timestamp)
  AND u.CreationDate <= CAST('2014-07-12 20:08:07' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
