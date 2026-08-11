with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v
WHERE p.Id = pl.PostId
  AND p.Id = v.PostId
  AND p.Id = ph.PostId
  AND p.Id = c.PostId
  AND c.CreationDate <= CAST('2014-09-10 02:42:35' AS timestamp)
  AND p.Score >= -1
  AND p.ViewCount <= 5896
  AND p.AnswerCount >= 0
  AND p.CreationDate >= CAST('2010-07-29 15:57:21' AS timestamp)
  AND v.VoteTypeId = 2
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v
WHERE p.Id = pl.PostId
  AND p.Id = v.PostId
  AND p.Id = ph.PostId
  AND p.Id = c.PostId
  AND c.CreationDate <= CAST('2014-09-10 02:42:35' AS timestamp)
  AND p.Score >= -1
  AND p.ViewCount <= 5896
  AND p.AnswerCount >= 0
  AND p.CreationDate >= CAST('2010-07-29 15:57:21' AS timestamp)
  AND v.VoteTypeId = 2
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
