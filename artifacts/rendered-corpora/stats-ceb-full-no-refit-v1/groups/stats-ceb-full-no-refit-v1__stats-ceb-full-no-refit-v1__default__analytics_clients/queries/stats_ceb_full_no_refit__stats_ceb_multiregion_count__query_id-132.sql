with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE v.UserId = u.Id
  AND c.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND p.ViewCount >= 0
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 5
  AND ph.PostHistoryTypeId = 2
  AND ph.CreationDate >= CAST('2010-11-05 01:25:39' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-09 07:14:12' AS timestamp)
  AND v.BountyAmount >= 0
  AND v.BountyAmount <= 100
  AND v.CreationDate >= CAST('2010-07-26 00:00:00' AS timestamp)
  AND u.Views >= 0
  AND u.Views <= 13
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE v.UserId = u.Id
  AND c.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND p.ViewCount >= 0
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 5
  AND ph.PostHistoryTypeId = 2
  AND ph.CreationDate >= CAST('2010-11-05 01:25:39' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-09 07:14:12' AS timestamp)
  AND v.BountyAmount >= 0
  AND v.BountyAmount <= 100
  AND v.CreationDate >= CAST('2010-07-26 00:00:00' AS timestamp)
  AND u.Views >= 0
  AND u.Views <= 13
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
