select
  count(*) as events_count,
  avg(e.value) as avg_value,
  min(e.value) as min_value,
  max(e.value) as max_value
from fdw_eu.events e;
