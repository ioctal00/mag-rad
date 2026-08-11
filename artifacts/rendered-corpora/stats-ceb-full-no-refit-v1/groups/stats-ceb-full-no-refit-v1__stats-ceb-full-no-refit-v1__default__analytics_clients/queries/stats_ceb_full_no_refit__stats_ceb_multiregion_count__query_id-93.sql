with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.votes AS v, stats_eu.posts AS p, stats_eu.users AS u
WHERE v.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND p.PostTypeId = 2
  AND p.CreationDate <= CAST('2014-08-26 22:40:26' AS timestamp)
  AND u.Views >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.votes AS v, stats_us.posts AS p, stats_us.users AS u
WHERE v.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND p.PostTypeId = 2
  AND p.CreationDate <= CAST('2014-08-26 22:40:26' AS timestamp)
  AND u.Views >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
