select
  count(*) as events_count,
  avg(value) as avg_value,
  min(value) as min_value,
  max(value) as max_value
from events;
