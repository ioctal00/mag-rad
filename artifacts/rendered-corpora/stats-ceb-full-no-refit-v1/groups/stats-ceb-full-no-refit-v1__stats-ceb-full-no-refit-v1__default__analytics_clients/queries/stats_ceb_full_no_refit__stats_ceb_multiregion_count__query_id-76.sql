with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.badges AS b,
  stats_eu.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND p.Id = c.PostId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND p.PostTypeId = 1
  AND p.ViewCount <= 4159
  AND p.CommentCount >= 0
  AND p.CommentCount <= 12
  AND ph.PostHistoryTypeId = 2
  AND v.VoteTypeId = 2
  AND u.Views <= 86
  AND u.DownVotes >= 0
  AND u.DownVotes <= 1
  AND u.UpVotes <= 6
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.badges AS b,
  stats_us.users AS u
WHERE u.Id = p.OwnerUserId
  AND u.Id = b.UserId
  AND p.Id = c.PostId
  AND p.Id = ph.PostId
  AND p.Id = v.PostId
  AND p.PostTypeId = 1
  AND p.ViewCount <= 4159
  AND p.CommentCount >= 0
  AND p.CommentCount <= 12
  AND ph.PostHistoryTypeId = 2
  AND v.VoteTypeId = 2
  AND u.Views <= 86
  AND u.DownVotes >= 0
  AND u.DownVotes <= 1
  AND u.UpVotes <= 6
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
