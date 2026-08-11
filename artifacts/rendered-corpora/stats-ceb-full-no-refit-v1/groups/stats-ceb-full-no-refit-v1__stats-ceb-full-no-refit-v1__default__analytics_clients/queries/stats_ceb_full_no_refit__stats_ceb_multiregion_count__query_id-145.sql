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
  AND p.PostTypeId = 1
  AND p.AnswerCount >= 0
  AND p.CreationDate >= CAST('2010-07-21 15:23:53' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-11 23:26:14' AS timestamp)
  AND pl.CreationDate >= CAST('2010-11-16 01:27:37' AS timestamp)
  AND pl.CreationDate <= CAST('2014-08-21 15:25:23' AS timestamp)
  AND ph.PostHistoryTypeId = 5
  AND v.CreationDate >= CAST('2010-07-21 00:00:00' AS timestamp)
  AND u.UpVotes >= 0
  AND u.CreationDate <= CAST('2014-09-11 20:31:48' AS timestamp)
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
  AND p.PostTypeId = 1
  AND p.AnswerCount >= 0
  AND p.CreationDate >= CAST('2010-07-21 15:23:53' AS timestamp)
  AND p.CreationDate <= CAST('2014-09-11 23:26:14' AS timestamp)
  AND pl.CreationDate >= CAST('2010-11-16 01:27:37' AS timestamp)
  AND pl.CreationDate <= CAST('2014-08-21 15:25:23' AS timestamp)
  AND ph.PostHistoryTypeId = 5
  AND v.CreationDate >= CAST('2010-07-21 00:00:00' AS timestamp)
  AND u.UpVotes >= 0
  AND u.CreationDate <= CAST('2014-09-11 20:31:48' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
