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
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-26 17:09:48' AS timestamp)
  AND p.PostTypeId = 1
  AND p.AnswerCount >= 0
  AND p.CommentCount >= 0
  AND p.CommentCount <= 14
  AND pl.CreationDate >= CAST('2010-10-27 10:02:57' AS timestamp)
  AND pl.CreationDate <= CAST('2014-09-04 17:23:50' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-11 20:09:41' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-21 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-14 00:00:00' AS timestamp)
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
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-07-26 17:09:48' AS timestamp)
  AND p.PostTypeId = 1
  AND p.AnswerCount >= 0
  AND p.CommentCount >= 0
  AND p.CommentCount <= 14
  AND pl.CreationDate >= CAST('2010-10-27 10:02:57' AS timestamp)
  AND pl.CreationDate <= CAST('2014-09-04 17:23:50' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-11 20:09:41' AS timestamp)
  AND v.CreationDate >= CAST('2010-07-21 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-14 00:00:00' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
