with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.postHistory AS ph,
  stats_eu.posts AS p,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND ph.CreationDate >= CAST('2010-07-21 00:44:08' AS timestamp)
  AND p.ViewCount >= 0
  AND p.CommentCount >= 0
  AND v.VoteTypeId = 2
  AND u.Views >= 0
  AND u.Views <= 34
  AND u.UpVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.postHistory AS ph,
  stats_us.posts AS p,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND ph.CreationDate >= CAST('2010-07-21 00:44:08' AS timestamp)
  AND p.ViewCount >= 0
  AND p.CommentCount >= 0
  AND v.VoteTypeId = 2
  AND u.Views >= 0
  AND u.Views <= 34
  AND u.UpVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
