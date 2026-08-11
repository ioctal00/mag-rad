with regional_hot_workers as (
  select
    'eu'::text as source_region,
    e.tenant_id,
    count(*) as events_count,
    sum(e.value) as total_value,
    sum(
      (e.value * e.value + e.user_id % 97) + (e.value * e.value + e.user_id % 98) + (e.value * e.value + e.user_id % 99) + (e.value * e.value + e.user_id % 100) + (e.value * e.value + e.user_id % 101) + (e.value * e.value + e.user_id % 102) + (e.value * e.value + e.user_id % 103) + (e.value * e.value + e.user_id % 104) + (e.value * e.value + e.user_id % 105) + (e.value * e.value + e.user_id % 106) + (e.value * e.value + e.user_id % 107) + (e.value * e.value + e.user_id % 108) + (e.value * e.value + e.user_id % 109) + (e.value * e.value + e.user_id % 110) + (e.value * e.value + e.user_id % 111) + (e.value * e.value + e.user_id % 112) + (e.value * e.value + e.user_id % 113) + (e.value * e.value + e.user_id % 114) + (e.value * e.value + e.user_id % 115) + (e.value * e.value + e.user_id % 116) + (e.value * e.value + e.user_id % 117) + (e.value * e.value + e.user_id % 118) + (e.value * e.value + e.user_id % 119) + (e.value * e.value + e.user_id % 120) + (e.value * e.value + e.user_id % 121) + (e.value * e.value + e.user_id % 122) + (e.value * e.value + e.user_id % 123) + (e.value * e.value + e.user_id % 124) + (e.value * e.value + e.user_id % 125) + (e.value * e.value + e.user_id % 126) + (e.value * e.value + e.user_id % 127) + (e.value * e.value + e.user_id % 128)
    ) as worker_checksum
  from fdw_eu.events e
  where e.tenant_id between 1 and 10
  group by e.tenant_id
  union all
  select
    'us'::text as source_region,
    e.tenant_id,
    count(*) as events_count,
    sum(e.value) as total_value,
    sum(
      (e.value * e.value + e.user_id % 97) + (e.value * e.value + e.user_id % 98) + (e.value * e.value + e.user_id % 99) + (e.value * e.value + e.user_id % 100) + (e.value * e.value + e.user_id % 101) + (e.value * e.value + e.user_id % 102) + (e.value * e.value + e.user_id % 103) + (e.value * e.value + e.user_id % 104) + (e.value * e.value + e.user_id % 105) + (e.value * e.value + e.user_id % 106) + (e.value * e.value + e.user_id % 107) + (e.value * e.value + e.user_id % 108) + (e.value * e.value + e.user_id % 109) + (e.value * e.value + e.user_id % 110) + (e.value * e.value + e.user_id % 111) + (e.value * e.value + e.user_id % 112) + (e.value * e.value + e.user_id % 113) + (e.value * e.value + e.user_id % 114) + (e.value * e.value + e.user_id % 115) + (e.value * e.value + e.user_id % 116) + (e.value * e.value + e.user_id % 117) + (e.value * e.value + e.user_id % 118) + (e.value * e.value + e.user_id % 119) + (e.value * e.value + e.user_id % 120) + (e.value * e.value + e.user_id % 121) + (e.value * e.value + e.user_id % 122) + (e.value * e.value + e.user_id % 123) + (e.value * e.value + e.user_id % 124) + (e.value * e.value + e.user_id % 125) + (e.value * e.value + e.user_id % 126) + (e.value * e.value + e.user_id % 127) + (e.value * e.value + e.user_id % 128)
    ) as worker_checksum
  from fdw_us.events e
  where e.tenant_id between 10001 and 10010
  group by e.tenant_id
)
select
  source_region,
  sum(events_count) as events_count,
  sum(total_value) as total_value,
  sum(worker_checksum) as worker_checksum
from regional_hot_workers
group by source_region
order by source_region;
