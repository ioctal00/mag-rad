with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph, stats_eu.posts AS p, stats_eu.users AS u
WHERE p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND p.Score >= -1
  AND p.CommentCount >= 0
  AND p.CommentCount <= 23
  AND u.DownVotes = 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 244
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph, stats_us.posts AS p, stats_us.users AS u
WHERE p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND p.Score >= -1
  AND p.CommentCount >= 0
  AND p.CommentCount <= 23
  AND u.DownVotes = 0
  AND u.UpVotes >= 0
  AND u.UpVotes <= 244
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
