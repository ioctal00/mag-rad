with regional_hot_workers as (
  select
    'eu'::text as source_region,
    e.tenant_id,
    count(*) as events_count,
    sum(
      ((e.user_id % 97)::bigint) + ((e.user_id % 98)::bigint) + ((e.user_id % 99)::bigint) + ((e.user_id % 100)::bigint) + ((e.user_id % 101)::bigint) + ((e.user_id % 102)::bigint) + ((e.user_id % 103)::bigint) + ((e.user_id % 104)::bigint) + ((e.user_id % 105)::bigint) + ((e.user_id % 106)::bigint) + ((e.user_id % 107)::bigint) + ((e.user_id % 108)::bigint) + ((e.user_id % 109)::bigint) + ((e.user_id % 110)::bigint) + ((e.user_id % 111)::bigint) + ((e.user_id % 112)::bigint) + ((e.user_id % 113)::bigint) + ((e.user_id % 114)::bigint) + ((e.user_id % 115)::bigint) + ((e.user_id % 116)::bigint) + ((e.user_id % 117)::bigint) + ((e.user_id % 118)::bigint) + ((e.user_id % 119)::bigint) + ((e.user_id % 120)::bigint) + ((e.user_id % 121)::bigint) + ((e.user_id % 122)::bigint) + ((e.user_id % 123)::bigint) + ((e.user_id % 124)::bigint) + ((e.user_id % 125)::bigint) + ((e.user_id % 126)::bigint) + ((e.user_id % 127)::bigint) + ((e.user_id % 128)::bigint)
    ) as worker_checksum
  from fdw_eu.events e
  where e.tenant_id between 1 and 20
  group by e.tenant_id
  union all
  select
    'us'::text as source_region,
    e.tenant_id,
    count(*) as events_count,
    sum(
      ((e.user_id % 97)::bigint) + ((e.user_id % 98)::bigint) + ((e.user_id % 99)::bigint) + ((e.user_id % 100)::bigint) + ((e.user_id % 101)::bigint) + ((e.user_id % 102)::bigint) + ((e.user_id % 103)::bigint) + ((e.user_id % 104)::bigint) + ((e.user_id % 105)::bigint) + ((e.user_id % 106)::bigint) + ((e.user_id % 107)::bigint) + ((e.user_id % 108)::bigint) + ((e.user_id % 109)::bigint) + ((e.user_id % 110)::bigint) + ((e.user_id % 111)::bigint) + ((e.user_id % 112)::bigint) + ((e.user_id % 113)::bigint) + ((e.user_id % 114)::bigint) + ((e.user_id % 115)::bigint) + ((e.user_id % 116)::bigint) + ((e.user_id % 117)::bigint) + ((e.user_id % 118)::bigint) + ((e.user_id % 119)::bigint) + ((e.user_id % 120)::bigint) + ((e.user_id % 121)::bigint) + ((e.user_id % 122)::bigint) + ((e.user_id % 123)::bigint) + ((e.user_id % 124)::bigint) + ((e.user_id % 125)::bigint) + ((e.user_id % 126)::bigint) + ((e.user_id % 127)::bigint) + ((e.user_id % 128)::bigint)
    ) as worker_checksum
  from fdw_us.events e
  where e.tenant_id between 10001 and 10020
  group by e.tenant_id
)
select
  source_region,
  sum(events_count) as events_count,
  sum(worker_checksum) as worker_checksum
from regional_hot_workers
group by source_region
order by source_region;
