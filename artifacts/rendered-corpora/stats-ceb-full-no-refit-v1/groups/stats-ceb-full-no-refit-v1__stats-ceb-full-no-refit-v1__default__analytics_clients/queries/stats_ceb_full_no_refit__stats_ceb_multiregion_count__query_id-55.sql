with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.tags AS t,
  stats_eu.posts AS p,
  stats_eu.users AS u,
  stats_eu.postHistory AS ph,
  stats_eu.badges AS b
WHERE p.Id = t.ExcerptPostId
  AND u.Id = ph.UserId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND p.CommentCount >= 0
  AND u.DownVotes <= 0
  AND b.Date <= CAST('2014-08-22 02:21:55' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.tags AS t,
  stats_us.posts AS p,
  stats_us.users AS u,
  stats_us.postHistory AS ph,
  stats_us.badges AS b
WHERE p.Id = t.ExcerptPostId
  AND u.Id = ph.UserId
  AND u.Id = b.UserId
  AND u.Id = p.OwnerUserId
  AND p.CommentCount >= 0
  AND u.DownVotes <= 0
  AND b.Date <= CAST('2014-08-22 02:21:55' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
