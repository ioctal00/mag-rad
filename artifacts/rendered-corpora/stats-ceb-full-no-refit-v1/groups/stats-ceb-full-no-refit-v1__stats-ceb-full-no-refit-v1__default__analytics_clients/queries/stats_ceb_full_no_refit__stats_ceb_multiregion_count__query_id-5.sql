with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c, stats_eu.votes AS v
WHERE c.UserId = v.UserId
  AND c.Score = 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c, stats_us.votes AS v
WHERE c.UserId = v.UserId
  AND c.Score = 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
