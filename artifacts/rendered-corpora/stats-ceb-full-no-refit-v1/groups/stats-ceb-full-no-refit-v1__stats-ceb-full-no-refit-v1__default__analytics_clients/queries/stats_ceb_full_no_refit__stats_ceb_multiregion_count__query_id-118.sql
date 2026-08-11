with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND ph.CreationDate <= CAST('2014-07-28 13:25:35' AS timestamp)
  AND p.PostTypeId = 1
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND v.CreationDate >= CAST('2010-07-20 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-03 00:00:00' AS timestamp)
  AND u.DownVotes = 0
  AND u.CreationDate <= CAST('2014-08-08 07:03:29' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND ph.CreationDate <= CAST('2014-07-28 13:25:35' AS timestamp)
  AND p.PostTypeId = 1
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 4
  AND v.CreationDate >= CAST('2010-07-20 00:00:00' AS timestamp)
  AND v.CreationDate <= CAST('2014-09-03 00:00:00' AS timestamp)
  AND u.DownVotes = 0
  AND u.CreationDate <= CAST('2014-08-08 07:03:29' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
