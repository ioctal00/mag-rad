with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postLinks AS pl,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE p.Id = pl.PostId
  AND p.Id = ph.PostId
  AND p.Id = c.PostId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-08-02 20:27:48' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-10 16:09:23' AS timestamp)
  AND p.PostTypeId = 1
  AND p.Score = 4
  AND p.ViewCount <= 4937
  AND pl.CreationDate >= CAST('2011-11-03 05:09:35' AS timestamp)
  AND ph.PostHistoryTypeId = 1
  AND u.Reputation <= 270
  AND u.Views >= 0
  AND u.Views <= 51
  AND u.DownVotes >= 0
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postLinks AS pl,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE p.Id = pl.PostId
  AND p.Id = ph.PostId
  AND p.Id = c.PostId
  AND u.Id = c.UserId
  AND u.Id = v.UserId
  AND c.Score = 0
  AND c.CreationDate >= CAST('2010-08-02 20:27:48' AS timestamp)
  AND c.CreationDate <= CAST('2014-09-10 16:09:23' AS timestamp)
  AND p.PostTypeId = 1
  AND p.Score = 4
  AND p.ViewCount <= 4937
  AND pl.CreationDate >= CAST('2011-11-03 05:09:35' AS timestamp)
  AND ph.PostHistoryTypeId = 1
  AND u.Reputation <= 270
  AND u.Views >= 0
  AND u.Views <= 51
  AND u.DownVotes >= 0
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
