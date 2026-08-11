with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.badges AS b
WHERE c.UserId = b.UserId
  AND c.Score = 0
  AND b.Date <= CAST('2014-09-11 14:33:06' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.badges AS b
WHERE c.UserId = b.UserId
  AND c.Score = 0
  AND b.Date <= CAST('2014-09-11 14:33:06' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
