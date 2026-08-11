with eu_result as (
  
  select count(*) as result_count
FROM stats_eu.comments AS c,
  stats_eu.posts AS p,
  stats_eu.postHistory AS ph,
  stats_eu.votes AS v,
  stats_eu.users AS u
WHERE v.UserId = u.Id
  AND c.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND c.Score = 2
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 9
  AND p.CreationDate >= CAST('2010-07-20 18:17:25' AS timestamp)
  AND p.CreationDate <= CAST('2014-08-26 12:57:22' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-02 07:58:47' AS timestamp)
  AND v.BountyAmount >= 0
  AND v.CreationDate >= CAST('2010-05-19 00:00:00' AS timestamp)
  AND u.UpVotes <= 230
  AND u.CreationDate >= CAST('2010-09-22 01:07:10' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-15 05:52:23' AS timestamp)
),
us_result as (
  
  select count(*) as result_count
FROM stats_us.comments AS c,
  stats_us.posts AS p,
  stats_us.postHistory AS ph,
  stats_us.votes AS v,
  stats_us.users AS u
WHERE v.UserId = u.Id
  AND c.UserId = u.Id
  AND p.OwnerUserId = u.Id
  AND ph.UserId = u.Id
  AND c.Score = 2
  AND p.AnswerCount >= 0
  AND p.AnswerCount <= 9
  AND p.CreationDate >= CAST('2010-07-20 18:17:25' AS timestamp)
  AND p.CreationDate <= CAST('2014-08-26 12:57:22' AS timestamp)
  AND ph.CreationDate <= CAST('2014-09-02 07:58:47' AS timestamp)
  AND v.BountyAmount >= 0
  AND v.CreationDate >= CAST('2010-05-19 00:00:00' AS timestamp)
  AND u.UpVotes <= 230
  AND u.CreationDate >= CAST('2010-09-22 01:07:10' AS timestamp)
  AND u.CreationDate <= CAST('2014-08-15 05:52:23' AS timestamp)
)
select 'eu'::text as source_region, result_count
from eu_result
union all
select 'us'::text as source_region, result_count
from us_result
order by source_region;
