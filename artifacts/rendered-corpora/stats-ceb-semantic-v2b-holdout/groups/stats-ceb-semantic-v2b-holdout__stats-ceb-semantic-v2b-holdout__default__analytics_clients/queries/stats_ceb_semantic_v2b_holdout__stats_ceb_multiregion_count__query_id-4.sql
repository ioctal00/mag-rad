with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.postHistory AS ph
WHERE c.UserId = ph.UserId
  AND ph.PostHistoryTypeId = 1
  AND ph.CreationDate >= CAST('2010-09-14 11:59:07' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.postHistory AS ph
WHERE c.UserId = ph.UserId
  AND ph.PostHistoryTypeId = 1
  AND ph.CreationDate >= CAST('2010-09-14 11:59:07' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
