with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND p.Id = pl.PostId
  AND p.Id = ph.PostId
  AND c.CreationDate >= CAST('2010-07-26 19:37:03' AS timestamp)
  AND p.Score >= -2
  AND p.CommentCount <= 18
  AND p.CreationDate >= CAST('2010-07-21 13:50:08' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-11 00:53:10' AS timestamp)
  AND pl.CreationDate <= CAST('2014-08-05 18:27:51' AS timestamp)
  AND ph.CreationDate >= CAST('2010-11-27 03:38:45' AS timestamp)
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND p.Id = pl.PostId
  AND p.Id = ph.PostId
  AND c.CreationDate >= CAST('2010-07-26 19:37:03' AS timestamp)
  AND p.Score >= -2
  AND p.CommentCount <= 18
  AND p.CreationDate >= CAST('2010-07-21 13:50:08' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-11 00:53:10' AS timestamp)
  AND pl.CreationDate <= CAST('2014-08-05 18:27:51' AS timestamp)
  AND ph.CreationDate >= CAST('2010-11-27 03:38:45' AS timestamp)
  AND u.DownVotes >= 0
  AND u.UpVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
