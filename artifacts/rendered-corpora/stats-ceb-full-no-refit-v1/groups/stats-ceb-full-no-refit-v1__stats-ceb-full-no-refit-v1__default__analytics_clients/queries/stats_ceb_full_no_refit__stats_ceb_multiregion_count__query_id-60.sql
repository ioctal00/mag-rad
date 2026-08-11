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
  AND u.Views <= 190
  AND u.CreationDate >= CAST('2010-07-20 08:05:39' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-27 09:31:28' AS timestamp)
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
  AND u.Views <= 190
  AND u.CreationDate >= CAST('2010-07-20 08:05:39' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-27 09:31:28' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
