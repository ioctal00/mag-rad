with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = pl.RelatedPostId
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND u.Id = b.UserId
  AND p.Score >= -1
  AND p.Score <= 14
  AND pl.CreationDate <= CAST('2014-06-25 13:05:06' AS timestamp)
  AND v.CreationDate >= CAST('2009-02-02 00:00:00' AS timestamp)
  AND b.Date >= CAST('2010-08-04 08:50:31' AS timestamp)
  AND b.Date <= CAST('2014-09-02 02:51:22' AS timestamp)
  AND u.DownVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = pl.RelatedPostId
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND u.Id = b.UserId
  AND p.Score >= -1
  AND p.Score <= 14
  AND pl.CreationDate <= CAST('2014-06-25 13:05:06' AS timestamp)
  AND v.CreationDate >= CAST('2009-02-02 00:00:00' AS timestamp)
  AND b.Date >= CAST('2010-08-04 08:50:31' AS timestamp)
  AND b.Date <= CAST('2014-09-02 02:51:22' AS timestamp)
  AND u.DownVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
