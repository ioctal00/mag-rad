DO $$
DECLARE
  constraint_row record;
BEGIN
  FOR constraint_row IN
    SELECT conrelid::regclass AS table_name, conname
    FROM pg_constraint
    WHERE contype = 'f'
      AND connamespace = 'stats'::regnamespace
  LOOP
    EXECUTE format(
      'ALTER TABLE %s DROP CONSTRAINT %I',
      constraint_row.table_name,
      constraint_row.conname
    );
  END LOOP;
END
$$;

ALTER TABLE stats.comments DROP CONSTRAINT IF EXISTS comments_pkey;
ALTER TABLE stats.votes DROP CONSTRAINT IF EXISTS votes_pkey;
ALTER TABLE stats.posthistory DROP CONSTRAINT IF EXISTS posthistory_pkey;
ALTER TABLE stats.postlinks DROP CONSTRAINT IF EXISTS postlinks_pkey;

CREATE INDEX IF NOT EXISTS comments_id_idx ON stats.comments (id);
CREATE INDEX IF NOT EXISTS votes_id_idx ON stats.votes (id);
CREATE INDEX IF NOT EXISTS posthistory_id_idx ON stats.posthistory (id);
CREATE INDEX IF NOT EXISTS postlinks_id_idx ON stats.postlinks (id);

SET citus.shard_count = 32;

SELECT create_reference_table('stats.users');
SELECT create_reference_table('stats.badges');
-- excerptpostid is nullable in the pinned snapshot, so tags cannot use it as
-- a Citus distribution column without changing source data semantics.
SELECT create_reference_table('stats.tags');
SELECT create_distributed_table('stats.posts', 'id');
SELECT create_distributed_table(
  'stats.comments',
  'postid',
  colocate_with => 'stats.posts'
);
SELECT create_distributed_table(
  'stats.votes',
  'postid',
  colocate_with => 'stats.posts'
);
SELECT create_distributed_table(
  'stats.posthistory',
  'postid',
  colocate_with => 'stats.posts'
);
SELECT create_distributed_table(
  'stats.postlinks',
  'postid',
  colocate_with => 'stats.posts'
);

ANALYZE stats.users;
ANALYZE stats.badges;
ANALYZE stats.posts;
ANALYZE stats.comments;
ANALYZE stats.votes;
ANALYZE stats.posthistory;
ANALYZE stats.postlinks;
ANALYZE stats.tags;
