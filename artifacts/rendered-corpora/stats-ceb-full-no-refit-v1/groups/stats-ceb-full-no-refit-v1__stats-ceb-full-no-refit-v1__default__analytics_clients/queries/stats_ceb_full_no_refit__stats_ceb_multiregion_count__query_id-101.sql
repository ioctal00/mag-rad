with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND c.Score = 0
  AND c.CreationDate <= CAST('2014-09-10 02:47:53' AS timestamp)
  AND p.Score >= 0
  AND p.Score <= 19
  AND p.CommentCount <= 10
  AND p.CreationDate <= CAST('2014-08-28 13:31:33' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND u.DownVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = v.PostId
  AND p.Id = c.PostId
  AND c.Score = 0
  AND c.CreationDate <= CAST('2014-09-10 02:47:53' AS timestamp)
  AND p.Score >= 0
  AND p.Score <= 19
  AND p.CommentCount <= 10
  AND p.CreationDate <= CAST('2014-08-28 13:31:33' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-12 00:00:00' AS timestamp)
  AND u.DownVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
