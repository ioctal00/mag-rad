with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.users AS u
WHERE p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND p.OwnerUserId = u.Id
  AND c.CreationDate >= CAST('2010-07-21 11:05:37' AS timestamp)
  AND c.CreationDate <= CAST('2014-08-25 17:59:25' AS timestamp)
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-08-21 21:27:38' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.users AS u
WHERE p.Id = c.PostId
  AND p.Id = pl.RelatedPostId
  AND p.OwnerUserId = u.Id
  AND c.CreationDate >= CAST('2010-07-21 11:05:37' AS timestamp)
  AND c.CreationDate <= CAST('2014-08-25 17:59:25' AS timestamp)
  AND u.UpVotes >= 0
  AND u.CreationDate >= CAST('2010-08-21 21:27:38' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
